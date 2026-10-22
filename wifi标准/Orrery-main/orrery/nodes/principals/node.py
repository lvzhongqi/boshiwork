"""Node 3, extract_principals: the protocol's semantic actors and pre-run values.

The artifact stops before formal modelling. It gives every important pre-run
value one stable name, a document-level description, and the other named values
it is deterministically derived from. Who holds a value, its ProVerif type,
attacker knowledge, the constructor realising a dependency and the role-process
signature all need the complete flow and belong to ``extract_flow``.

``derived_from`` is the one machine-readable relation kept. It says only that a
value may not be generated independently: ``PKA`` derived from ``SKA`` must
become a named term depending on ``SKA``, never ``new PKA``. Whether the
relation is encryption, signing, DH or a verifier is left to the description,
and the flow model selects the matching ProVerif primitive.
"""

from __future__ import annotations

import orrery.checks.rules.entities        # noqa: F401  importing registers the checks
import orrery.checks.rules.init_knowledge  # noqa: F401  importing registers the checks
from orrery.agent.compose import localized, render_prompt, render_system, resume_user
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.agent.tools import READER_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.checks.registry import must_failures, run_checks
from orrery.checks.rules.entities import ENTITY_CHECK_NAMES
from orrery.checks.rules.init_knowledge import IK_CHECK_NAMES
from orrery.infra.llm.client import Effort
from orrery.modules.document.corpus import inline_principals_corpus
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.nodes.claims.load import load_claim_input
from orrery.services.events import NodeProgress, check_sink
from orrery.services.store.atomic import write_json, write_text
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

_VALUE = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "the document's own symbol for this value, copied word "
                           "for word, keeping its case and subscripts. Where the "
                           "document names none, write <purpose>_<principal>. It "
                           "becomes a ProVerif variable name, so it starts with a "
                           "letter or underscore and continues with letters, "
                           "digits and underscores",
        },
        "derived_from": {
            "type": "array",
            "items": {"type": "string"},
            "description": "names of other values in this values list from which "
                           "this value is deterministically derived. Empty when the "
                           "value is independent. This records dependency only; the "
                           "description and document determine the cryptographic "
                           "relation, and flow chooses its ProVerif constructor",
        },
        "description": {
            "type": "string",
            "description": "a concise document-level account of what the value is, "
                           "its purpose, where it is stored or configured before the "
                           "run, and how other parties obtain it. State key usage and "
                           "the meaning of every derived_from edge without using "
                           "ProVerif type names",
        },
    },
    "required": ["name", "derived_from", "description"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        # The supporting quotes are not a parameter: they arrive as a ```quotes
        # fence in the same reply. A long passage of quoted document text inside
        # a tool argument is where the call's own syntax breaks.
        "principals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "the name the document gives this party; "
                                       "where it gives an abbreviation, use the "
                                       "abbreviation. Letters, digits and "
                                       "underscores, starting with a letter",
                    },
                    "description": {
                        "type": "string",
                        "description": "a short document-level introduction to "
                                       "this party's role, service, and protocol "
                                       "responsibilities",
                    },
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
        "values": {
            "type": "array", "items": _VALUE,
            "description": "the stable semantic inventory of important values that "
                           "exist before the protocol run, including identities, "
                           "symmetric and asymmetric keys, credentials, and "
                           "provisioned parameters",
        },
    },
    "required": ["principals", "values"],
    "additionalProperties": False,
}


def build_prompt(*, corpus: str, protocol: str, step_messages: str = "",
                 lang: str = "en") -> Prompt:
    """Build this node's one request. No I/O and no LLM, so the prompt preview
    calls it to render exactly the bytes a run sends.

    The corpus is a separate leading block, byte-identical with tag_sections so
    that reader pair shares a cache breakpoint; the {{ document }} placeholder
    at the top of main.sys.md is where it lands. There is no report_gap tool:
    everything upstream is load_document and tag_sections, and rolling either
    back re-reads the same files to the same result."""
    return Prompt(
        system=render_system(__file__, localized("main.sys.md", lang),
                              cut_after=["document"], document=corpus),
        user=render_prompt(__file__, localized("main.user.md", lang),
                           protocol=protocol, step_messages=step_messages),
        tools=tuple(READER_TOOLS),
        submit=SubmitSpec(kind="tool", schema=_SCHEMA),
        label="extract_principals",
    )


class PrincipalsNode(Node):
    name = "extract_principals"
    short = "principals"
    task = (
        "Extract the document-level principals and stable pre-run value "
        "inventory, including deterministic dependencies")
    model_driven = True
    depends_on = ("tag_sections",)
    # Judgement, not transcription: who counts as a principal turns on which
    # party performs a cryptographic operation, and what a party holds before
    # the run is more often implied than stated. It also drives tool use.
    effort = Effort.HIGH

    def is_done(self, env: RunEnv) -> bool:
        return env.layout.has(self.name, "principals.json")

    async def run(self, env: RunEnv) -> None:
        if env.principals_input is not None:
            # Supplied together with the mother model — the two are one input
            # (RunEnv.flow_input). A supplied file is trusted to be what the
            # reader meant, never to be well-formed, so it faces the same
            # checks an extracted one does.
            out = env.layout.node_dir(self.name)
            doc = load_claim_input(env.principals_input, "principals", self.name)
            sink = check_sink(env.emitter(self.name))
            problems = (must_failures(await run_checks(ENTITY_CHECK_NAMES, doc, on=sink))
                        + must_failures(await run_checks(IK_CHECK_NAMES, doc, on=sink)))
            if problems:
                raise NodeError(
                    f"{self.name} failed: the supplied principals.json does not "
                    f"pass this node's own checks: " + "; ".join(problems))
            if env.bus is not None:
                env.bus.emit(NodeProgress(
                    run=env.layout.run_name, node=self.name,
                    text="principals.json was supplied, so nothing was extracted from the document"))
            write_json(out / "principals.json", doc)
            return

        if env.doc_set is None:
            raise NodeError(f"{self.name} failed: no document set upstream (load_document did not run)")

        prompt = build_prompt(
            corpus=inline_principals_corpus(
                env.doc_set, env.config["document"]["inline_max_chars"]),
            protocol=env.protocol_id,
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
            node=self.name,
            doc_set=env.doc_set,
            artifacts_root=env.layout.run_dir,
            tool_return_chars=env.config["agent"]["tool_return_chars"],
        )

        async def _accept(s, fences):
            # The entity and init-knowledge checks read the submission as it
            # stands: who takes part, and which stable values and dependencies
            # the document establishes before formal modelling.
            problems = []
            if not (fences.get("quotes") or "").strip():
                problems.append(
                    "the reply carrying the submit call has no ```quotes block. "
                    "Write the supporting quotes as a ```quotes fenced block in "
                    "the reply text, then call submit in that same reply.")
            sink = check_sink(env.emitter(self.name))
            problems += must_failures(
                await run_checks(ENTITY_CHECK_NAMES, s, on=sink))
            problems += must_failures(
                await run_checks(IK_CHECK_NAMES, s, on=sink))
            return problems

        result = await run_agent(
            env.llm(),
            # The corpus is block 0 of prompt.system; it pays through the
            # provider cache across rounds within this session.
            system=prompt.system,
            user=user,
            tools=list(prompt.tools),
            ctx=ctx,
            submit=submit,
            accept=_accept,
            budget=env.budget(),
            writer=writer,
            resume_from=resume,
            effort=self.effort,
            emitter=env.emitter(self.name),
        )
        if result.status != "ok":
            raise NodeError(f"{self.name}: {result.status}: {result.failure}")

        out = env.layout.node_dir(self.name)
        # The file is_done gates on is written last. Each write is atomic on
        # its own but the pair is not, and a kill in between would leave the
        # gate satisfied with quotes.md missing, so a re-entry would skip the
        # node rather than finish it.
        write_text(out / "quotes.md", result.fences["quotes"] + "\n")
        write_json(out / "principals.json", dict(result.submission))
