"""Node protocol: a node declares and assembles, while execution lives in
agent/runner and orchestration in pipeline.

Every node says what it is called (name), how a re-entry decides it is already
finished (is_done, by looking for the artifact on disk), what one run does
(run), and whether it must re-run every time (always_run, for pure-code nodes
whose output only lives in memory).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from orrery.agent.budget import LoopBudget
from orrery.agent.compose import step_messages
from orrery.infra.llm.client import ChatClient
from orrery.infra.llm.factory import build_chat_client
from orrery.modules.document.model.document_set import DocumentSet
from orrery.services.facts import collect
from orrery.services.store.layout import RunLayout
from orrery.services.transcript.prompt import is_session_file


class NodeError(RuntimeError):
    """Explicit node failure: repair rounds exhausted, or the artifact could not
    be written. The node did not get its job done; the runner records it and
    ends the run."""


class CheckFailed(NodeError):
    """The node did its job and the answer is "no": a comparison disagreed, a
    check did not pass. The artifact is written and the verdict stands.

    A run ends on either one, but a failed check is a result and a failed node
    is a breakage, and every surface that shows them tells them apart."""


class GapRaised(Exception):
    """Upstream-gap signal: the agent called report_gap and the node hands it up
    unchanged, since accepting or rejecting it belongs to pipeline/gaps. Carries
    the pairing info needed to resume the tool call."""

    def __init__(self, gap, transcript_path, tool_call_id):
        super().__init__(f"gap: {gap.reporter} -> {gap.target} is missing {gap.missing!r}")
        self.gap = gap
        self.transcript_path = transcript_path
        self.tool_call_id = tool_call_id


#: Which supplied input pins which node, keyed by run.json's own field name,
#: which is also run()'s parameter name. Four layers read this one table: the
#: node that stands aside, the console that greys the step out, the gap tool
#: that may not offer it as a fallback, and the re-entry that refuses it.
#:
#: Pinned means re-running cannot change anything: the node writes the file it
#: was handed, so a second pass writes the same bytes.
PINNED_BY = {
    "principals": "extract_principals",
    "flow": "extract_flow",
    "assumptions": "extract_assumptions",
    "properties": "extract_properties",
    "claims": "extract_claims",
}

#: The steps that read the document itself. Once every one of them has been
#: handed its artifact, nothing downstream asks for the corpus again (see
#: pinned_nodes).
_DOCUMENT_READERS = frozenset(PINNED_BY.values())


def pinned_nodes(supplied) -> frozenset[str]:
    """The nodes this run cannot usefully re-enter, given what it was handed.

    Two bands: the steps whose artifact was supplied, and — only when all five
    were — ``load_document`` and ``tag_sections``, whose tags let
    ``inline_corpus`` pick sections out of an oversized document and have no
    other readers. Under a partial supply the pair stays live, because
    extract_assumptions and extract_properties still read the corpus and
    untagged they see a table of contents instead of the flow.
    """
    have = {k for k, v in (supplied or {}).items() if v}
    pinned = {node for key, node in PINNED_BY.items() if key in have}
    if _DOCUMENT_READERS <= pinned:
        pinned |= {"load_document", "tag_sections"}
    return frozenset(pinned)


@dataclass
class RunEnv:
    """Shared environment for one run. Nodes take services from here instead of
    assembling paths or reading config files themselves."""

    protocol_dir: Path
    layout: RunLayout
    config: dict
    # The protocol's identity, <name>[-<version>][-<subprotocol>]. Artifacts and
    # events name the protocol with this; the directory name is a path, not an
    # identity.
    protocol_id: str = ""
    subprotocol: str | None = None          # subprotocol name; None = single protocol
    doc_set: DocumentSet | None = None      # filled by load_document, read later
    # Which documents to read, when the caller names them:
    # {"main": path, "refs": [path, ...]}. None means load_document discovers
    # them by walking the corpus layout under protocol_dir, the case for every
    # corpus entry. Same rule as the inputs below: given, use it; absent, do the
    # work.
    documents_input: object = None
    # Claim inputs, passed straight through from run(): dict | path | None.
    #
    # The two vocabularies are read by their own extraction nodes, not by the
    # claims gate: given, the node writes the supplied file as its artifact and
    # makes no model call; absent, it reads the vocabulary out of the document.
    # Either way the artifact exists, so the gate downstream has one input path.
    # claims_input decides more: with it the run answers a stated question
    # (user 1), without it user 2's traversal is not wired up.
    assumptions_input: object = None
    properties_input: object = None
    claims_input: object = None
    # The mother model and the signature it is written on, passed straight
    # through from run(): a path (or text / dict) or None. Same rule as the two
    # vocabularies — given, the node writes the supplied artifact and makes no
    # model call; absent, it extracts.
    #
    # They travel together. A role's parameter list is its initial knowledge,
    # and flow_fixed_parts checks the supplied model's signatures against the
    # template rendered from principals.json, so a model supplied over some
    # other pass's principals.json fails that check by construction. The
    # pipeline refuses the pairing at its door.
    flow_input: object = None
    principals_input: object = None
    bus: object = None                      # event bus, filled by the runner
    # Ground-truth directory, consumed only by cross_check; layout does not
    # expose this path.
    ground_truth: object = None
    # The node table's names in order, set by the runner. A node reads its own
    # legal report_gap targets off it.
    node_names: tuple[str, ...] = ()
    # The model-driven nodes' names, set by the runner from the table: the steps
    # that run a session and can read a filed message. Gap verification checks
    # its target against this.
    model_driven_names: tuple[str, ...] = ()
    # The nodes that run on every pass regardless (base.Node.always_run), set
    # by the runner from the table. Sending one of them back changes nothing
    # (it re-reads what it already left), so a gap may not name it.
    always_run_names: tuple[str, ...] = ()
    # What this pass was sent back to redo, as a step path: an identity at each
    # level, never a directory — ``extract_flow``,
    # ``scenarios/baseline/apply/ltk_reveal_A``. Set by the runner from the
    # re-entry the run was started with, and by the gap path when the pipeline
    # sends itself back.
    #
    # An identity because the questions the aim answers are asked before the
    # directory exists: a plain ``--from-node extract_flow`` names a step with
    # no directory to point at yet.
    aim: str | None = None
    _llm: ChatClient | None = field(default=None, repr=False)

    # ── where a unit's work goes ─────────────────────────────────────────
    # One rule, asked at every level of the tree: the node chain, a stage's
    # scenarios, an apply chain's points, a scenario's goal families.

    def redoing(self, step: str) -> bool:
        """Is this unit itself the work being redone — or inside it?"""
        return self.aim is not None and (
            self.aim == step or step.startswith(self.aim + "/"))

    def contains_aim(self, step: str) -> bool:
        """Is the work being redone strictly inside this unit? Then the unit
        carries on rather than starting over: its other branches are still
        good."""
        return self.aim is not None and self.aim.startswith(step + "/")

    def plan(self, step: str, prev: Path | None, finished: bool) -> str:
        """What to do with a unit that may already have work: ``skip`` it,
        ``carry`` on in the directory it has, or ``open`` a new one.

        The order of the tests is the rule: nothing there yet opens; an aim
        inside it carries, keeping the branches that are still good; unfinished
        work carries, so a run killed part-way keeps what it completed; the unit
        itself being redone opens; otherwise nobody asked, so skip.
        """
        if prev is None:
            return "open"
        if self.contains_aim(step):
            return "carry"
        if not finished:
            return "carry"
        if self.redoing(step):
            return "open"
        return "skip"

    def supplied(self) -> dict:
        """What this run was handed, by run.json's own field names — the shape
        ``pinned_nodes`` reads."""
        return {"principals": self.principals_input,
                "flow": self.flow_input,
                "assumptions": self.assumptions_input,
                "properties": self.properties_input,
                "claims": self.claims_input}

    def pinned(self) -> frozenset[str]:
        """The nodes re-running cannot change, because their artifact was
        supplied (see ``pinned_nodes``)."""
        return pinned_nodes(self.supplied())

    def upstream(self, node_name: str) -> tuple[str, ...]:
        """The nodes that ran before ``node_name`` — the legal targets of a gap
        report. Empty when the table was not supplied (pure-mechanism tests).

        Pinned nodes are filtered out here rather than at each caller: a gap
        asks an upstream step to redo its work, and a step holding a file
        somebody handed it has nothing to redo. An always-run node is out for
        the same reason: it runs on every pass anyway and re-uses what it left.
        """
        if node_name not in self.node_names:
            return ()
        out = self.pinned() | set(self.always_run_names)
        return tuple(n for n in self.node_names[:self.node_names.index(node_name)]
                     if n not in out)

    def llm(self) -> ChatClient:
        """Built on demand, so pure-mechanism tests need no model config."""
        if self._llm is None:
            self._llm = build_chat_client(self.config["llm"])
        return self._llm

    def budget(self) -> LoopBudget:
        """The agent loop's round, tool-call and repair caps, from config."""
        a = self.config["agent"]
        return LoopBudget(max_rounds=a["max_rounds"],
                          max_tool_calls=a["max_tool_calls"],
                          max_repairs=a["max_repairs"])

    def facts(self, node: str, scenario: str | None = None) -> str:
        """The messages filed for this step, rendered for a fresh session's
        prompt; empty when there are none. Only a fresh session reads it — a
        resumed one already had the same text handed into its transcript.

        A step's messages live in its own directory (services/facts) and a step
        reads its ancestors' too: one filed for the scenario stage reaches every
        scenario, one filed for a single scenario reaches it alone. Announced on
        the ledger, since it changes a prompt.
        """
        step = self.layout.rel(self.layout.node_dir(node))
        if scenario is not None:
            step = self.layout.rel(self.layout.scenario_dir(scenario))
        return self.facts_at(step, announce_as=(node, scenario))

    def facts_at(self, step_rel: str,
                 announce_as: tuple[str, str | None] | None = None) -> str:
        """``facts`` by run-relative directory path, for callers deeper than a
        node or a scenario (an apply point's session under its own dir)."""
        matched = collect(self.layout.run_dir, step_rel)
        if not matched:
            return ""
        if announce_as is not None:
            em = self.emitter(announce_as[0], announce_as[1])
            if em is not None:
                from orrery.services.events.pipeline import NodeProgress
                em(NodeProgress(run="", node=announce_as[0],
                                text=f"{len(matched)} filed message(s) inlined "
                                     f"into this step's prompt"))
        return step_messages([f.text for f in matched])

    def emitter(self, node: str, scenario: str | None = None,
                unit: str | None = None):
        """Stamping emitter for run_agent: fills the envelope's addressing
        fields before an event reaches the bus. Returns None when there is no
        bus (pure-mechanism tests), and run_agent then emits nothing.

        ``unit`` names one of a scenario's concurrent sessions
        (``layout.unit_of``); binding it here keeps the agent layer from
        learning that units exist. A stage-wide line takes an emitter with no
        unit, which is how a reader tells it from a session's own events."""
        if self.bus is None:
            return None
        bus, run_name = self.bus, self.layout.run_name

        def emit(ev) -> None:
            ev.run = run_name
            ev.node = ev.node or node
            ev.scenario = ev.scenario or scenario
            ev.unit = ev.unit or unit
            bus.emit(ev)

        return emit


class Node(ABC):
    """One pipeline step: its identity and declarations, plus the two methods
    the runner calls (``is_done``, ``run``). The class-level fields below are
    what other layers — console, gap tool, fix path — read about a step."""

    name: ClassVar[str]
    #: This step's job in one sentence, for whoever is reading rather than
    #: running. The same words for every protocol and every run, so it travels
    #: like the assumption and goal vocabularies (a meta endpoint the console
    #: asks for once) instead of being repeated on every run's ledger. Declared
    #: on the node, the one place that cannot fall out of step with itself.
    task: ClassVar[str] = ""
    #: The name as the pipeline strip draws it: one word, the one this step does
    #: not share with any other. Twelve cells across one row leave about nine
    #: rem each, which the full names overflow. The verb is what goes, except
    #: where the verb is the distinguishing word (``load_document``,
    #: ``tag_sections``) and the object goes instead.
    #:
    #: Declared rather than derived: a rule ("drop the first word") would have
    #: to know the exceptions, and a table in the console page would be a second
    #: copy of pipeline/table.py. Checked for presence and uniqueness by
    #: tests/unit/nodes/test_short_names.py.
    short: ClassVar[str] = ""
    always_run: ClassVar[bool] = False
    # Whether this step runs a model session — the precondition for reading a
    # filed message (a user fix, an accepted gap report). A pure-code node's
    # artifact is a function of its inputs, so a message delivered to it reaches
    # nobody; fixes and gap verification both refuse such a target.
    model_driven: ClassVar[bool] = False
    # The nodes this one may aim a report_gap at, and the enum the tool is built
    # with (agent/tools/gap_tools.gap_tool). Empty means the node does not mount
    # the tool at all, the default for most nodes.
    #
    # Declared per node rather than derived: agent/ may not depend on pipeline/,
    # so the set cannot be computed where the tool is built, and "upstream and
    # model-driven" is only the outer bound — what matters is which upstream
    # artifact this node consumes, which may be fewer. tests/contracts holds
    # every declaration inside that bound, so self-targets and downstream
    # targets stay unreachable.
    gap_targets: ClassVar[tuple[str, ...]] = ()
    # Which earlier steps this one actually consumes. Empty means "whatever ran
    # before me", the linear default and right for most of the table.
    #
    # The table is a list while the real shape is a DAG: the two vocabulary
    # readers both take the flow model and neither takes the other, so they run
    # side by side, and extract_claims joins all three back together. The
    # console draws its graph from this. It schedules nothing — execution is
    # still in table order — it says what that order means.
    depends_on: ClassVar[tuple[str, ...]] = ()
    # Whether this node still runs once a check has failed the run. Default no:
    # a step whose product is built on the failed one has nothing to build. A
    # step that explains the run's answers is the exception, since a run whose
    # comparison disagreed is the run a reader most needs explained. It runs
    # the way every step does, and a failure in it fails the run.
    runs_after_check_failure: ClassVar[bool] = False
    # Whether this step runs ProVerif. A run whose table, up to its stop point,
    # holds such a step has its solver checked before anything starts: the
    # solver is first called only after the flow model has been paid for, and
    # a missing one should cost nothing and name the setting at fault.
    needs_solver: ClassVar[bool] = False
    # How much reasoning this step is worth, declared next to the node's name
    # because "how hard is this step" is the node's own knowledge; the model
    # cannot judge it from the prompt alone. None (the pure-code nodes, which
    # make no model call) sends nothing and takes the provider default.
    effort: ClassVar[str | None] = None

    @abstractmethod
    def is_done(self, env: RunEnv) -> bool: ...

    @abstractmethod
    async def run(self, env: RunEnv) -> None: ...

    def artifacts(self, env: RunEnv) -> list[str]:
        """What this node wrote, as the ledger reports it (NodeFinished, then
        work.md's "done — artifacts" line). Default: the files of the node's own
        directory; a node whose products land elsewhere (a scenario tree, the
        run root) overrides this."""
        d = env.layout.find_node_dir(self.name)
        if d is None:
            return []
        return sorted(p.name for p in d.glob("*")
                      if p.is_file() and not is_session_file(p.name))


class RoundLog:
    """Per-round dump for the nodes that repair, written to ``rounds/`` beside
    the session so the step's own products keep plain names.

    Every file leads with a two-digit slot handed out in write order, so a plain
    ``ls`` reads as the history: each round's prompt, its edits, the assembled
    ``.pv``, the ProVerif calls, the findings. The slot leads because a listing
    sorts on leading characters; the round number follows it. Slots are the next
    free one in the directory, since the agent loop writes into the same band.
    """

    def __init__(self, session_dir: Path) -> None:
        from orrery.services.transcript.prompt import ROUNDS
        self.dir = Path(session_dir) / ROUNDS
        self.n = 0
        self._k = 0

    def _name(self, part: str, *, n: int | None = None) -> str:
        """Claim the next slot and build the file name on it.

        The slot is the higher of what is on disk and what this object has
        handed out: the agent loop files prompts into the same band, so a local
        counter alone would collide, and a stem is handed out before its files
        exist, so an on-disk scan alone would repeat itself. ``n`` names a round
        other than the current one."""
        from orrery.services.transcript.prompt import next_slot
        self._k = max(self._k + 1, next_slot(self.dir))
        return f"{self._k:02d}_r{self.n if n is None else n}{part}"

    def submission(self, data) -> None:
        """File the structured answer the model submitted for the round about to
        open, for the steps where the model names edits (anchor, position, text)
        and the framework splices them (nodes/apply, nodes/inject). It takes the
        slot before that round's assembled text.

        Written before the splice and for every submission: one that is
        malformed, out of scope, or anchored to nothing never reaches ``begin``,
        and a request with no ``.pv`` after it is the record of "the model
        asked, nothing was built". It also makes a round's assembled text a pure
        function of its input text and these edits.
        """
        from orrery.services.store.atomic import write_json
        write_json(self.dir / self._name("_edits.json", n=self.n + 1), data)

    def begin(self, pv: str) -> None:
        """Open a round with the text under test. It lands on disk before the
        checks run, so a round interrupted halfway still says what was being
        checked."""
        from orrery.services.store.atomic import write_text as _wt
        self.n += 1
        _wt(self.dir / self._name(".pv"), pv + "\n")

    def stem(self, purpose: str) -> Path:
        """The next log stem of this round, for one ProVerif call. Handed to
        the checks as ``pv_log``; the runner writes ``<stem>.pv`` and
        ``<stem>.txt`` against it."""
        return self.dir / self._name(f"_{purpose}")

    def finish(self, problems: list[str]) -> None:
        """Close the round with its findings, or a line saying all checks
        passed."""
        from orrery.services.store.atomic import write_text as _wt
        body = "all checks passed" if not problems else "\n".join(f"- {x}" for x in problems)
        _wt(self.dir / self._name("_checks.md"), body + "\n")
