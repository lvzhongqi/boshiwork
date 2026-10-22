"""extract_properties: read the security goals out of the document.

Artifacts: properties.json (one goal per entry, in the closed goal vocabulary)
and quotes.md. A property is a goal, not a verdict — what the document claims
the protocol achieves; whether it holds is the scenario stage's answer.

One of the four document readers: it mounts ``READER_TOOLS`` unchanged and
renders the same analysis corpus as extract_assumptions, so the four share one
cached copy; the goal vocabulary is inlined to keep that tool array identical.

Goals name flow-model values, so this runs after extract_flow — NSSK's secrecy
goal is about ``CK``, which principals.json never mentions. Submissions pass
validate_properties, so a bad one becomes a repair round. A user-supplied
properties.json skips extraction and goes through that same gate.
"""

from __future__ import annotations

from orrery.agent.compose import localized, render_prompt, render_system, resume_user
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.agent.tools import READER_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.infra.llm.client import Effort
from orrery.modules.document.corpus import inline_analysis_corpus
from orrery.modules.libschema.io import parse_properties
from orrery.modules.libschema.validate import validate_properties
from orrery.version import VOCAB_VERSION
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.nodes.claims.load import load_claim_input
from orrery.nodes.inject.injectors import PROP_VOCAB
from orrery.nodes.properties.reference import property_reference
from orrery.services.events import NodeProgress
from orrery.services.store.atomic import write_json, write_text
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

_SCHEMA = {
    "type": "object",
    "properties": {
        "properties": {
            "type": "array",
            "description": "one entry per security goal the document states",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "unique key, lower_snake_case, e.g. secrecy_CK or auth_A_B_CK"},
                    "type": {"type": "string", "enum": list(PROP_VOCAB.types())},
                    "subtype": {"type": "string", "description": "one subtype of that type; omit only where the type offers none"},
                    "values": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "string"},
                        "description": "the flow-model names this goal is about, spelled exactly as the .pv spells them",
                    },
                    "parties": {
                        "type": "object",
                        "description": "who the goal is for; the shape is the one listed with the type (holders, asserter_subject, or subjects)",
                        "properties": {
                            "holders": {"type": "array", "items": {"type": "string"}},
                            "asserter": {"type": "string"},
                            "subject": {"type": "string"},
                            "subjects": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["id", "type", "values", "parties"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["properties"],
    "additionalProperties": False,
}


def build_prompt(*, corpus: str, protocol: str, knowledge_json: str = "{}",
                 flow_pv: str = "", step_messages: str = "",
                 lang: str = "en") -> Prompt:
    """This node's one request. No I/O and no LLM, so the prompt preview renders
    exactly what a run sends.

    The analysis corpus is system block 0, byte-identical with the assumptions
    reader's block; the goal vocabulary goes after that cache breakpoint."""
    return Prompt(
        system=render_system(__file__, localized("main.sys.md", lang),
                             cut_after=["document"], document=corpus,
                             reference=property_reference()),
        user=render_prompt(__file__, localized("main.user.md", lang),
                           protocol=protocol, knowledge_json=knowledge_json,
                           flow_pv=flow_pv, step_messages=step_messages),
        tools=tuple(READER_TOOLS),
        submit=SubmitSpec(kind="tool", schema=_SCHEMA),
        label="extract_properties",
    )


class PropertiesNode(Node):
    name = "extract_properties"
    short = "properties"
    task = (
        "Extract the security goals the document states, in the goal "
        "vocabulary, with the flow-model values each one is about")
    model_driven = True
    depends_on = ("extract_flow", "extract_principals")
    effort = Effort.HIGH

    def is_done(self, env: RunEnv) -> bool:
        return env.layout.has(self.name, "properties.json")

    async def run(self, env: RunEnv) -> None:
        if env.doc_set is None:
            raise NodeError(f"{self.name} failed: no document set upstream")
        out = env.layout.node_dir(self.name)

        if env.properties_input is not None:
            doc = validate_properties(
                parse_properties(load_claim_input(env.properties_input,
                                                  "properties", self.name),
                                 where="properties"), PROP_VOCAB)
            if env.bus is not None:
                env.bus.emit(NodeProgress(
                    run=env.layout.run_name, node=self.name,
                    text="properties.json was supplied, so nothing was extracted from the document"))
            write_json(out / "properties.json", doc.to_json())
            return

        flow_pv = env.layout.flow_pv
        if not flow_pv.exists():
            raise NodeError(f"{self.name} failed: the upstream flow model does not exist")
        try:
            knowledge = (env.layout.node_dir("extract_principals")
                         / "principals.json").read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise NodeError(f"{self.name} failed: an upstream artifact is missing; {e}") from None

        prompt = build_prompt(
            corpus=inline_analysis_corpus(
                env.doc_set, env.config["document"]["inline_max_chars"]),
            protocol=env.protocol_id, knowledge_json=knowledge,
            flow_pv=flow_pv.read_text(encoding="utf-8"),
            step_messages=env.facts(self.name),
            lang=env.config.get("prompt_lang", "en"),
        )
        submit = prompt.submit
        transcript = env.layout.node_transcript(self.name)
        resume = resume_messages(transcript)
        writer = TranscriptWriter(transcript)
        if resume is None:
            writer.meta(node=self.name,
                        model=env.config["llm"].get("model", "?"),
                        effort=self.effort)
            user = prompt.user
        else:
            user = resume_user(submit)

        ctx = ToolContext(
            node=self.name, doc_set=env.doc_set,
            artifacts_root=env.layout.run_dir,
            tool_return_chars=env.config["agent"]["tool_return_chars"],
        )

        async def _accept(s, fences):
            problems = []
            if not (fences.get("quotes") or "").strip():
                problems.append(
                    "the reply carrying the submit call has no ```quotes block. "
                    "Write the supporting quotes as a ```quotes fenced block in "
                    "the reply text, then call submit in that same reply.")
            try:
                validate_properties(
                    parse_properties({**s, "vocab_version": VOCAB_VERSION},
                                     where="properties"), PROP_VOCAB)
            except Exception as e:
                problems.append(f"the submission does not pass the goal gate: {e}")
            return problems

        result = await run_agent(
            env.llm(), system=prompt.system, user=user,
            tools=list(prompt.tools), ctx=ctx, submit=submit, accept=_accept,
            budget=env.budget(), writer=writer, resume_from=resume,
            effort=self.effort, emitter=env.emitter(self.name),
        )
        if result.status != "ok":
            raise NodeError(f"{self.name}: {result.status}: {result.failure}")

        doc = validate_properties(
            parse_properties({**result.submission,
                              "vocab_version": VOCAB_VERSION},
                             where="properties"), PROP_VOCAB)
        write_text(out / "quotes.md", result.fences["quotes"] + "\n")
        write_json(out / "properties.json", doc.to_json())
