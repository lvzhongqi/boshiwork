"""The expert long session: one continuous read-only agent session.

Each user message is one run_agent call, with resume_from set to the session
transcript — a direct reuse of the session-resume mechanism. The reply is the
submission (of the text kind). When the model calls propose_fix, the round ends
and the plan is carried out to the host for two-level authorisation, shaped just
like report_gap.

The transcript goes to `_expert/` in the run directory: an underscore domain,
so no agent — the expert included — reads the expert's conversation through
artifact tools. Superseded attempts sit sealed in each step's own directory
(NN_-banded files and NN_transcript.jsonl), so the expert reads history the
same way it reads everything else: as artifacts and transcripts.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from orrery.agent.budget import LoopBudget
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.agent.tools.artifact_tools import ARTIFACT_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.document_tools import DOCUMENT_TOOLS
from orrery.agent.tools.expert_tools import EXPERT_TOOLS, FixPlan
from orrery.agent.tools.review_tools import REVIEW_TOOLS
from orrery.agent.tools.trace_tools import TRACE_TOOLS
from orrery.agent.tools.truth_tools import TRUTH_TOOLS
from orrery.infra.llm.client import ChatClient
from orrery.expert import overview
from orrery.modules.document import DocumentLoaderService, ProtocolSource
from orrery.agent.compose import localized, render_prompt
from orrery.services.transcript.reader import TranscriptReader
from orrery.services.transcript.resume import resume_messages
from orrery.services.store.layout import RunLayout
from orrery.services.transcript.writer import TranscriptWriter

# review_tools rides with the read-only set: filing a reading changes no
# artifact, and asking for a longer counter-example only re-runs a solver
# over a model that is already on disk.
_READONLY_TOOLS = (DOCUMENT_TOOLS + ARTIFACT_TOOLS + TRACE_TOOLS
                   + EXPERT_TOOLS + REVIEW_TOOLS)


def build_prompt(*, state: str = "", user_text: str = "",
                 has_truth: bool = False, lang: str = "en") -> Prompt:
    """One message of the expert session. No I/O and no LLM — the prompt
    preview calls it to render exactly what a run sends.

    The run overview leads the user message rather than sitting in the system
    prompt: a fix rewrites artifacts mid-session, so the newest copy has to be
    the last thing in the conversation to win.

    ``has_truth`` adds read_expected. Adding the tool rather than making it
    answer "nothing here" is what keeps a run with no corpus quiet about the
    whole subject: a model is not told the tool exists, so it neither offers a
    comparison it cannot make nor spends a round finding that out."""
    return Prompt(
        system=[render_prompt(__file__, localized("session.sys.md", lang))],
        user=f"{state}\n\n{user_text}",
        tools=tuple(_READONLY_TOOLS + (TRUTH_TOOLS if has_truth else [])),
        submit=SubmitSpec(kind="text"),
        label="expert",
    )


def executed_notice(from_node: str, superseded: list[str],
                    limit: int = 12) -> str:
    """What the model reads as the result of its own propose_fix call, once the
    fix has run.

    It names the superseded paths rather than saying the run has changed.
    Everything the session read before the fix is still sitting in the
    conversation as concrete text, and a general warning loses to concrete
    text; a list of paths is what makes the next answer read the file again
    instead of quoting a version that no longer exists.
    """
    if not superseded:
        return (f"Plan executed: the pipeline re-ran from {from_node}. Nothing "
                f"downstream had been produced yet, so no artifact was replaced.")
    shown = superseded[:limit]
    rest = len(superseded) - len(shown)
    lines = "\n".join(f"- {p}" for p in shown)
    return (f"Plan executed: the pipeline re-ran from {from_node}. These "
            f"artifacts were rewritten, so whatever you read from them earlier "
            f"in this conversation is out of date — read one again before you "
            f"rely on it:\n{lines}"
            + (f"\n- ... and {rest} more" if rest > 0 else ""))


@dataclass
class ExpertReply:
    kind: str                      # "reply" | "plan" | "failed"
    text: str = ""
    plan: FixPlan | None = None
    # What this message cost, and what the session has cost so far. A session
    # is charged to the user's own key and gets dearer with every turn (each
    # one re-sends the whole conversation), so the host shows both: the second
    # number is the one that tells you when to start a fresh session.
    cost: str = ""

    @property
    def display(self) -> str:
        return f"{self.text}\n\n{self.cost}" if self.cost else self.text


class ExpertSession:
    """Bound to a run, not to a process: a run directory is enough to instantiate
    it, whether that run is in progress, finished or failed."""

    def __init__(self, run_dir: Path, config: dict, llm: ChatClient,
                 bus=None) -> None:
        self.run_dir = Path(run_dir)
        self.config = config
        self.llm = llm
        # Where this session's rounds go. Without one it is silent. The host
        # supplies it, and supplies the *run's* bus when the run is in flight
        # — a second bus on one ledger would hand out `seq` numbers that
        # collide.
        self.bus = bus
        meta = json.loads((self.run_dir / "run.json").read_text(encoding="utf-8"))
        self.protocol = meta["protocol"]
        self.protocol_dir = Path(meta["protocol_dir"])
        # The documents this run was handed, when it was handed any:
        # the same branch load_document takes, read off the same
        # record. A run started on a reader's own file has no corpus
        # layout under protocol_dir, so discovering one there raises
        # and the expert cannot answer a single question about it.
        self.documents = meta.get("documents") or None
        # A run directory is named by the protocol's *identity*
        # (<name>[-<version>][-<subprotocol>]), not by its name — a bundle's
        # sub-protocol and a versioned entry both land elsewhere. Built from the
        # name, every path off this layout pointed at a directory that does not
        # exist, and each reader then failed on its own and quietly: the
        # overview described the run as empty, and a fix superseded nothing and
        # filed the user's instruction where no step reads it.
        self.layout = RunLayout(self.run_dir.parent.parent,
                                meta["protocol_id"], meta["run_name"])
        if self.layout.run_dir.resolve() != self.run_dir.resolve():
            # A copied or renamed run: everything read off run.json would be
            # answered from, and every fix written to, the original.
            raise ValueError(
                f"{self.run_dir} is not the run its run.json describes: that "
                f"record names {self.layout.run_dir}. A copied run cannot be "
                f"attached; attach the original, or start a fresh run")
        # The corpus this run was checked against, if it was. Read from
        # run.json — where the run recorded what it was started with — rather
        # than from layout, which deliberately knows no such path. None means
        # the expert simply never has read_expected.
        gt = meta.get("ground_truth")
        self.ground_truth = Path(gt) if gt else None
        self._transcript = self.run_dir / "_expert" / "transcript.jsonl"
        self._doc_set = None
        self._pending_fix_call: str | None = None
        self._turn = asyncio.Lock()      # one turn at a time; see handle()

    def _transcripts(self) -> dict[str, Path]:
        """Every session of this run the expert may read, keyed by path.

        A recursive walk rather than a scan of the top level: the scenario
        stage keeps one session per assumption applied and per goal family
        injected, nested inside the scenario
        (``08_scenarios/<scenario>/apply/01_<subtype>/``), and those are the
        sessions that wrote scenario.pv and each model.pv — the artifacts a
        user is most likely to question. A top-level scan reached four of a
        measured run's twelve sessions, and not one of the eight it missed.

        Underscore domains stay out: the expert's own conversation is not
        upstream evidence.

        A sealed session (``NN_transcript.jsonl`` — a superseded attempt,
        renamed into its directory's slot band) is readable too, keyed with
        its file name after the step's, so "what did the first attempt do and
        why was the second one right" can be answered from the record.
        """
        out: dict[str, Path] = {}
        for p in sorted(self.run_dir.rglob("*transcript.jsonl")):
            parts = p.parent.relative_to(self.run_dir).parts
            if not parts or any(seg.startswith("_") for seg in parts):
                continue
            # 03_extract_principals → extract_principals, so a step keeps the name
            # the prompts and the fix plans use; deeper segments stay exactly
            # as they appear on disk, so a path from list_artifacts is a key.
            key = "/".join((parts[0].split("_", 1)[-1],) + parts[1:])
            if p.name != "transcript.jsonl":
                key = f"{key}/{p.name}"
            out[key] = p
        return out

    async def _ctx(self) -> ToolContext:
        if self._doc_set is None:
            given = self.documents
            src = (
                ProtocolSource.from_documents(given["main"],
                                              given.get("refs") or ())
                if given is not None else
                ProtocolSource.from_directory(self.protocol_dir)
            )
            self._doc_set = await DocumentLoaderService().load(src)
        transcripts = self._transcripts()
        return ToolContext(
            node="expert", doc_set=self._doc_set,
            artifacts_root=self.run_dir,
            ground_truth=self.ground_truth,
            transcript_paths=transcripts,
            proverif=self._solver(),
            emitter=self._emitter(),
            tool_return_chars=self.config["agent"]["tool_return_chars"],
        )

    def _solver(self):
        """A ProVerif runner for deepen_trace, or None when this session has no
        usable solver. Built per turn and not held: a session outlives many
        turns, and the config it was opened with may have been edited since."""
        cfg = self.config.get("proverif") or {}
        exe = cfg.get("executable")
        if not exe or str(exe) == "???":
            return None
        from orrery.infra.proverif.runner import ProVerifRunner
        return (ProVerifRunner(executable=exe, timeout_s=cfg["timeout_s"]),
                cfg["timeout_s"])

    async def handle(self, user_text: str) -> ExpertReply:
        """One message, one turn. Turns are serialised, and a turn that ended
        in a plan blocks the next one until the host has resolved it.

        Both guards protect the same thing — the transcript is read once at the
        start of a turn and written throughout it, so two turns sharing one
        baseline overwrite each other (measured: one reply lost, the other
        written twice). Queueing rather than refusing, because both messages
        are things the user asked for, and the second turn then sees the
        first's answer, which is what a conversation is. A pending plan is the
        exception: its tool_call is answered by resolve_plan, and a turn
        slipping in between would separate the call from its result, which the
        API rejects on the next resume.
        """
        async with self._turn:
            # Inside the lock, so that a queued turn sees the state the turn
            # ahead of it left rather than the state it started from.
            if self._pending_fix_call is not None:
                return ExpertReply(kind="failed", text=(
                    "a proposed fix is still waiting for your decision; confirm "
                    "or cancel it before sending another message"))
            # The stage index is cached per layout, and a fix executed in an
            # earlier turn (or a run this process finished since) has grown
            # it; read again, or the overview below describes the run as it
            # was before the fix.
            self.layout.reload()
            resume = resume_messages(self._transcript)
            writer = TranscriptWriter(self._transcript)
            if resume is None:
                writer.meta(node="expert", run=self.layout.run_name)
            ctx = await self._ctx()
            # Rebuilt for every message, because a fix rewrites artifacts
            # mid-session: the newest copy is the last thing in the
            # conversation, which is where it has to be to win.
            state = overview.build(self.layout, self.run_dir,
                                   sorted(ctx.transcript_paths),
                                   lang=self.config.get("prompt_lang", "en"))
            prompt = build_prompt(state=state, user_text=user_text,
                                  has_truth=self.ground_truth is not None,
                                  lang=self.config.get("prompt_lang", "en"))
            result = await run_agent(
                self.llm,
                system=prompt.system,
                user=prompt.user,
                tools=list(prompt.tools),
                ctx=ctx,
                submit=SubmitSpec(kind="text"),
                accept=lambda s, f: [],
                budget=LoopBudget(
                    # expert.* rather than agent.*: one message is not one
                    # task. tool_return_chars stays shared — the expert reads
                    # the same files the nodes wrote, so the same cap fits.
                    max_rounds=self.config["expert"]["max_rounds"],
                    max_tool_calls=self.config["expert"]["max_tool_calls"],
                    max_repairs=1),
                writer=writer,
                resume_from=resume,
                emitter=self._emitter(),
            )
            cost = self._cost_line(result)
            if result.status == "fix":
                self._pending_fix_call = result.fix_tool_call_id
                return ExpertReply(kind="plan", plan=result.fix,
                                   text=result.fix.rationale, cost=cost)
            if result.status == "ok":
                return ExpertReply(kind="reply", text=result.submission,
                                   cost=cost)
            return ExpertReply(kind="failed", text=result.failure, cost=cost)

    def _emitter(self):
        """Stamping emitter for this session's rounds, or None when nobody is
        watching. Same shape as RunEnv.emitter — the run name and node are the
        address, and the agent layer never learns whose events these are.

        The expert is not a step of the pipeline, so its events carry
        ``node="expert"``: a reader can tell an answer's rounds from a node's
        by that alone, and the ledger gains an audit trail of what was asked
        and what was changed."""
        if self.bus is None:
            return None
        bus, run_name = self.bus, self.layout.run_name

        def emit(ev) -> None:
            ev.run = run_name
            ev.node = ev.node or "expert"
            bus.emit(ev)

        return emit

    def _cost_line(self, result) -> str:
        """This turn's tokens and the session's running total. The total is read
        back from the transcript rather than kept in memory, so it stays right
        across a re-attach — a session outlives the process it started in."""
        s_in, s_out = TranscriptReader(self._transcript).usage_total()
        n = lambda v: f"{v / 1000:.1f}k" if v >= 1000 else str(v)   # noqa: E731
        return (f"[this message {n(result.usage.input_tokens)} in / "
                f"{n(result.usage.output_tokens)} out · session "
                f"{n(s_in)} in / {n(s_out)} out]")

    def resolve_plan(self, outcome: str) -> None:
        """Fill in the tool_result once the plan has been executed or cancelled.
        Without it, the next message resuming the session would leave a
        tool_use with no result, which the API rejects. The host must call this
        when the confirmation flow ends."""
        if self._pending_fix_call is None:
            return
        TranscriptWriter(self._transcript).tool_result(
            self._pending_fix_call, "propose_fix", outcome)
        self._pending_fix_call = None
