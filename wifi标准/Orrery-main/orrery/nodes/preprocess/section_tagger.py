"""Node 2, tag_sections: give every section its type tags.

Three paths: the corpus ships its own ``annotations/`` and nothing is written;
this run already wrote ``tags.json``, which is re-applied without a model call;
or neither, and the document is read and tagged. The overlay lives in memory on
``env.doc_set``, rebuilt by ``load_document`` on every pass, so a re-entry has
to put the tags back — hence ``always_run``. ``inline_corpus`` picks the flow
sections out by these tags, so an untagged large document reaches extract_flow
as a table of contents.

A document reader on ``READER_TOOLS``; on a document too large to inline whole
its corpus block falls back to flow sections this node has not tagged yet, so
there it differs from the other readers'. A model-written overlay marks its
annotations ``source="llm"``, which keeps the reference façade answering
unresolved rather than "this section cites nothing".
"""

from __future__ import annotations

import json

from orrery.agent.compose import localized, render_prompt, render_system, resume_user
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.agent.tools import READER_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.infra.llm.client import Effort
from orrery.modules.document.corpus import inline_corpus
from orrery.modules.document.model.overlay import Annotation, AnnotationOverlay
from orrery.modules.document.model.types import SectionType
from orrery.nodes.base import Node, NodeError, RunEnv
from orrery.services.events import NodeProgress
from orrery.services.store.atomic import write_json
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

_TAGS = [t.value for t in SectionType]

_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "description": "one entry per section that carries at least one tag; sections with no tag are simply left out",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "string", "description": "the section number exactly as the contents list spells it, e.g. '3.2' or 'A.1'"},
                    "tags": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "string", "enum": _TAGS},
                        "description": "every type this section carries",
                    },
                },
                "required": ["number", "tags"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tags"],
    "additionalProperties": False,
}


def build_prompt(*, corpus: str, protocol: str, step_messages: str = "",
                 lang: str = "en") -> Prompt:
    """Build this node's one request. No I/O and no LLM, so the prompt preview
    calls it to render exactly the bytes a run sends."""
    return Prompt(
        system=render_system(__file__, localized("tag_sections.sys.md", lang),
                             cut_after=["document"], document=corpus),
        user=render_prompt(__file__, localized("tag_sections.user.md", lang),
                           protocol=protocol, step_messages=step_messages),
        tools=tuple(READER_TOOLS),
        submit=SubmitSpec(kind="tool", schema=_SCHEMA),
        label="tag_sections",
    )


def _section_numbers(doc_set) -> set[str]:
    return {s.number for s in doc_set.main().sections.walk() if s.level > 0}


def _tagged_overlay(entries: list[dict]) -> AnnotationOverlay:
    """A fresh overlay carrying these tags and no references.

    Fresh rather than mutated in place: DocumentSet memoises the resolved
    sub-protocol map against ``id(overlay)``. ``source="llm"`` tells the
    reference façade that nobody annotated the references here, so an
    unanswered reference stays unresolved instead of becoming "none".
    """
    return AnnotationOverlay(sections={
        e["number"]: Annotation(
            tags=[SectionType.from_str(t) for t in dict.fromkeys(e["tags"])],
            source="llm")
        for e in entries if e.get("tags")
    })


class SectionTaggerNode(Node):
    name = "tag_sections"
    short = "tag"
    task = (
        "Tag the document sections (locate the flow, assumption and security "
        "passages)")
    model_driven = True
    # The overlay lives in memory and load_document rebuilds the document set
    # on every pass, so even a finished tagging has to be put back.
    always_run = True
    depends_on = ("load_document",)
    # Recall over a table of contents, not construction; a missed flow section
    # is invisible downstream, because extract_flow never sees the text.
    effort = Effort.MEDIUM

    def is_done(self, env: RunEnv) -> bool:
        # Never asked by the runner: an always_run node is neither skipped on
        # re-entry nor re-used, it is called through run(), where the "nothing
        # to do" cases live. Answered anyway, since Node declares it.
        return env.doc_set is not None and (not env.doc_set.overlay.is_empty()
                                            or self.name in env.pinned())

    async def run(self, env: RunEnv) -> None:
        if env.doc_set is None:
            raise NodeError(f"{self.name} failed: no document set upstream")
        # Pinned means nobody downstream will read the corpus: every step that
        # would have picked sections out with these tags was handed its artifact
        # instead. ``pinned_nodes`` states the condition, which is stricter than
        # "the mother model arrived" — with only that supplied,
        # extract_assumptions and extract_properties still read the document.
        if self.name in env.pinned():
            return
        if not env.doc_set.overlay.is_empty():
            return                      # the corpus ships its own annotations

        # pipeline's `_prepare` allocates a stage only for nodes that are not
        # always_run, so when the tagging actually has to happen no directory
        # exists yet and one is opened here.
        out = env.layout.find_node_dir(self.name) or env.layout.open_node(self.name)
        done = out / "tags.json"
        if done.exists():
            env.doc_set.overlay = _tagged_overlay(
                json.loads(done.read_text(encoding="utf-8"))["tags"])
            return

        prompt = build_prompt(
            corpus=inline_corpus(env.doc_set,
                                 env.config["document"]["inline_max_chars"]),
            protocol=env.protocol_id, step_messages=env.facts(self.name),
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
        known = _section_numbers(env.doc_set)

        async def _accept(s, _fences):
            # A number outside the tree tags nothing, silently; the loader
            # refuses such an entry when reading a corpus's tags.yaml, and the
            # model gets the same rule.
            problems = []
            unknown = sorted({e["number"] for e in s["tags"]} - known)
            if unknown:
                problems.append(
                    f"these are not section numbers in this document: {unknown}. "
                    f"Use the numbers exactly as the contents list spells them.")
            if not any(SectionType.FLOW.value in e["tags"] for e in s["tags"]):
                problems.append(
                    "no section is tagged 'flow'. Every protocol document "
                    "describes its message exchange somewhere; without that tag "
                    "a large document reaches the modelling step as a table of "
                    "contents. Find it and tag it.")
            return problems

        result = await run_agent(
            env.llm(), system=prompt.system, user=user,
            tools=list(prompt.tools), ctx=ctx, submit=submit, accept=_accept,
            budget=env.budget(), writer=writer, resume_from=resume,
            effort=self.effort, emitter=env.emitter(self.name),
        )
        if result.status != "ok":
            raise NodeError(f"{self.name}: {result.status}: {result.failure}")

        entries = result.submission["tags"]
        write_json(done, result.submission)
        env.doc_set.overlay = _tagged_overlay(entries)
        if env.bus is not None:
            env.bus.emit(NodeProgress(
                run=env.layout.run_name, node=self.name,
                text=f"tagged {len(entries)} sections from the document "
                     f"(no annotations/ directory shipped with this corpus)"))
