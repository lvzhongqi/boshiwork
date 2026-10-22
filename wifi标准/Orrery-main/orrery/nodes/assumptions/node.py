"""extract_assumptions: read the assumption space out of the document.

Artifacts: assumptions.json (world / fixed / variable) and quotes.md. The node
reports which dimensions the protocol's security is stated against, not whether
any goal holds.

One of the four document readers: it mounts ``READER_TOOLS`` unchanged and
renders the same analysis corpus as extract_properties into system block 0, so
the four share one cached copy. The vocabulary is inlined in the prompt, not
fetched by a tool, which keeps that tool array byte-identical.

Assumption targets are flow-model names, so this runs after extract_flow —
NSSK's session key ``CK`` lives only in the flow model. Submissions pass the
artifact's own gate (validate_world, then validate_assumptions), turning a bad
one into a repair round. A user-supplied assumptions.json skips extraction and
goes through that same gate.
"""

from __future__ import annotations

import json

from orrery.agent.compose import localized, render_prompt, render_system, resume_user
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.agent.tools import READER_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.infra.llm.client import Effort
from orrery.modules.document.corpus import inline_analysis_corpus
from orrery.modules.libschema.io import parse_assumptions
from orrery.modules.libschema.validate import validate_assumptions, validate_world
from orrery.version import VOCAB_VERSION
from orrery.nodes.apply.realizers import VOCAB
from orrery.nodes.world.builders import WORLD_VOCAB
from orrery.nodes.assumptions.reference import (
    assumption_reference, world_reference,
)
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.nodes.claims.load import load_claim_input
from orrery.services.events import NodeProgress
from orrery.services.store.atomic import write_json, write_text
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

# The target keys any axis can ask for, read off the vocabulary so the schema
# tracks newly declared axes. An ``entity_pair`` field (channel's ``link``) is a
# two-name list, every other kind is one name; which keys a given subtype needs
# is validate_assumptions' business. A field name declared with two kinds has no
# single JSON type, so it raises here, at import.
def _target_kinds() -> dict[str, str]:
    kinds: dict[str, str] = {}
    for axis in VOCAB.axes():
        for st in VOCAB.dimension_values(axis):
            for k, spec in VOCAB.params(axis, st).items():
                seen = kinds.setdefault(k, spec["kind"])
                if seen != spec["kind"]:
                    raise NodeError(
                        f"[extract_assumptions] target field {k!r} is declared "
                        f"{seen!r} on one subtype and {spec['kind']!r} on "
                        f"{axis}.{st}; one field name, one kind")
    return kinds


_TARGET_KINDS = _target_kinds()


def _validated(doc):
    """Both gates in file order: the world section first, since it says what the
    assumption targets denote, then the assumptions."""
    validate_world(doc, WORLD_VOCAB)
    validate_assumptions(doc, VOCAB)
    return doc

def _field_schema(kind: str) -> dict:
    """One target field's JSON type from its declared kind: entity_pair is the
    directed link as [sender, receiver], every other kind is one name."""
    if kind == "entity_pair":
        return {"type": "array", "items": {"type": "string"},
                "minItems": 2, "maxItems": 2,
                "description": "the directed link as [sender, receiver]"}
    return {"type": "string"}


_TARGET = {
    "type": "object",
    "description": "which object in the flow model this assumption is about; the keys a subtype needs are listed with it in the reference",
    "properties": {
        k: _field_schema(kind) for k, kind in sorted(_TARGET_KINDS.items())},
    "additionalProperties": False,
}

# The world section's own target shape. The world axes take their own params
# (role_binding names a principal, the global axes take none), so it is built
# from WORLD_VOCAB; _TARGET above is keyed on the assumption vocabulary.
_WORLD_TARGET_KINDS = {
    k: spec["kind"]
    for axis in WORLD_VOCAB.axes()
    for st in WORLD_VOCAB.subtypes(axis)
    for k, spec in WORLD_VOCAB.params(axis, st).items()
}

_WORLD_TARGET = {
    "type": "object",
    "description": "which object this world entry is about; role_binding names one principal with 'of', the axes that speak about the world as a whole take no target",
    "properties": {
        k: _field_schema(kind) for k, kind in sorted(_WORLD_TARGET_KINDS.items())},
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "world": {
            "type": "array",
            "description": "what the model's domain is: how many principals, which seats each may take, how the sessions are laid out. Only entries that differ from the flow state; an axis you leave out already takes it. Never a scenario condition — a run analyses one world",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "unique key, lower_snake_case, e.g. world_role_binding_A"},
                    "axis": {"type": "string", "enum": list(WORLD_VOCAB.axes())},
                    "subtype": {"type": "string", "description": "one value of that axis, never its flow state"},
                    "target": _WORLD_TARGET,
                },
                "required": ["id", "axis", "subtype"],
                "additionalProperties": False,
            },
        },
        "fixed": {
            "type": "array",
            "description": "assumptions the document states once for the whole protocol",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "unique key, lower_snake_case, e.g. data_ltk_B"},
                    "axis": {"type": "string", "enum": list(VOCAB.axes())},
                    "subtype": {"type": "string", "description": "one value of that axis"},
                    "target": _TARGET,
                },
                "required": ["id", "axis", "subtype"],
                "additionalProperties": False,
            },
        },
        "variable": {
            "type": "array",
            "description": "dimensions the document leaves open, each with the values a scenario may take; include the flow-state value when a scenario may leave the dimension unchanged",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "unique key, lower_snake_case"},
                    "axis": {"type": "string", "enum": list(VOCAB.axes())},
                    "target": _TARGET,
                    "subtypes": {
                        "type": "array", "minItems": 2,
                        "items": {"type": "string"},
                        "description": "at least two possible values; include the flow-state subtype when the document's ordinary world leaves this dimension unchanged",
                    },
                },
                "required": ["id", "axis", "subtypes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["world", "fixed", "variable"],
    "additionalProperties": False,
}


def build_prompt(*, corpus: str, protocol: str, knowledge_json: str = "{}",
                 flow_pv: str = "", step_messages: str = "",
                 lang: str = "en") -> Prompt:
    """This node's one request. No I/O and no LLM, so the prompt preview renders
    exactly what a run sends.

    The analysis corpus is system block 0, byte-identical with properties'
    block; the vocabulary goes in block 1, after that shared cache breakpoint."""
    return Prompt(
        system=render_system(__file__, localized("main.sys.md", lang),
                             cut_after=["document"], document=corpus,
                             reference=assumption_reference(),
                             world_reference=world_reference()),
        user=render_prompt(__file__, localized("main.user.md", lang),
                           protocol=protocol, knowledge_json=knowledge_json,
                           flow_pv=flow_pv, step_messages=step_messages),
        tools=tuple(READER_TOOLS),
        submit=SubmitSpec(kind="tool", schema=_SCHEMA),
        label="extract_assumptions",
    )


class AssumptionsNode(Node):
    name = "extract_assumptions"
    short = "assumptions"
    task = (
        "Extract the assumption space from the document: what it fixes once, "
        "and which dimensions it leaves open per scenario")
    model_driven = True
    depends_on = ("extract_flow", "extract_principals")
    # Whether the document fixes a dimension or leaves it open is rarely stated
    # in those words, and getting it wrong moves an axis between the world model
    # and the scenario fan-out, changing what every later verdict means.
    effort = Effort.HIGH

    def is_done(self, env: RunEnv) -> bool:
        return env.layout.has(self.name, "assumptions.json")

    async def run(self, env: RunEnv) -> None:
        if env.doc_set is None:
            raise NodeError(f"{self.name} failed: no document set upstream")
        out = env.layout.node_dir(self.name)

        if env.assumptions_input is not None:
            # Nothing to extract, but the artifact still goes through the gate
            # the extracted one passes, so claims has one input path.
            doc = _validated(
                parse_assumptions(load_claim_input(env.assumptions_input,
                                                   "assumptions", self.name),
                                  where="assumptions"))
            if env.bus is not None:
                env.bus.emit(NodeProgress(
                    run=env.layout.run_name, node=self.name,
                    text="assumptions.json was supplied, so nothing was extracted from the document"))
            write_json(out / "assumptions.json", doc.to_json())
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
            # The acceptance test is the gate the artifact has to pass anyway;
            # running it here turns a bad submission into a repair round instead
            # of a run that dies two nodes later.
            problems = []
            if not (fences.get("quotes") or "").strip():
                problems.append(
                    "the reply carrying the submit call has no ```quotes block. "
                    "Write the supporting quotes as a ```quotes fenced block in "
                    "the reply text, then call submit in that same reply.")
            try:
                _validated(parse_assumptions({**s, "vocab_version": VOCAB_VERSION},
                                             where="assumptions"))
            except Exception as e:
                problems.append(f"the submission does not pass the assumption gate: {e}")
            return problems

        result = await run_agent(
            env.llm(), system=prompt.system, user=user,
            tools=list(prompt.tools), ctx=ctx, submit=submit, accept=_accept,
            budget=env.budget(), writer=writer, resume_from=resume,
            effort=self.effort, emitter=env.emitter(self.name),
        )
        if result.status != "ok":
            raise NodeError(f"{self.name}: {result.status}: {result.failure}")

        doc = _validated(parse_assumptions({**result.submission,
                                            "vocab_version": VOCAB_VERSION},
                                           where="assumptions"))
        # quotes first, then the file is_done gates on: a kill in between leaves
        # the run resumable rather than done with the evidence missing.
        write_text(out / "quotes.md", result.fences["quotes"] + "\n")
        write_json(out / "assumptions.json", doc.to_json())
