"""Pipeline-domain events: node boundaries, progress, terminal states,
interrupts. Emitted from pipeline/runner and from the nodes themselves."""

from __future__ import annotations

from dataclasses import dataclass, field

from orrery.services.events.types import Event


@dataclass
class RunStarted(Event):
    from_node: str | None = None    # re-entry point; None = a fresh run


@dataclass
class NodeStarted(Event):
    #: The directory this execution writes to, run-relative. A step's directory
    #: is not a function of its name (a run that goes back writes a second one),
    #: so a reader folding the ledger has to be told which attempt this is.
    dir: str = ""


@dataclass
class NodeProgress(Event):
    text: str = ""                  # wording fixed in the node's code, carrying real detail


@dataclass
class NodeFinished(Event):
    # ok | check_failed | failed | skipped. check_failed = the node ran and a
    # comparison disagreed; failed = the node could not finish at all.
    status: str = "ok"
    artifacts: list[str] = field(default_factory=list)   # this node's artifacts (relative paths)


@dataclass
class NodeScored(Event):
    """One step's product, scored against the corpus. Emitted right after the
    step finishes, when the run was given a ground truth and the product was
    not simply handed to the step.

    Numbers only, plus principals' alpha-renaming pairs so a reader can audit
    what was compared. Nothing consumes the score: it is not in RunEnv, no
    repair round sees it, and it gates nothing.
    """
    slug: str = ""                  # which product: principals, flow, claims …
    num: int = 0
    den: int = 0
    extra: int = 0                  # entries produced beyond what the corpus declares
    alignment_status: str = ""      # "ok" only on scores that ran an aligner
    alignment: list[dict] = field(default_factory=list)  # [{candidate, gold}]


@dataclass
class AwaitingApproval(Event):
    pass                            # manual stop point: the node name is in the envelope, the host resumes


@dataclass
class ScenarioStarted(Event):       # the scenario itself is an envelope field
    # The scenario's complete assumption assignment, one row per dimension:
    # {id, axis, subtype, target, from} with from ∈ fixed | condition | default.
    # On the event so a reader can name the combination without opening an
    # artifact.
    assignment: list = field(default_factory=list)


@dataclass
class ScenarioFinished(Event):
    status: str = "ok"              # ok | failed
    verdicts: dict = field(default_factory=dict)   # {goal_id: verdict} summary


@dataclass
class SolveFinished(Event):
    """One cell's ProVerif call, the moment it answers: the cell and its
    outcome, so a person can watch the slowest part of a run go by. The attack
    trace behind a false verdict is on disk in the goal's own retry output,
    ``03_proverif_precise_<goal>.txt`` or ``02_proverif_trace_<goal>.txt``: the
    shared first pass, ``01_proverif.txt``, runs without trace reconstruction.

    The envelope's unit is the inject family that produced the model; ``cell``
    names the one cell inside it.
    """

    cell: str = ""                  # the goal subtype this cell verified
    kind: str = "ok"                # ok | syntax_error | solver_limit | timeout
    seconds: float = 0.0            # every ProVerif call this cell made
    verdicts: dict = field(default_factory=dict)   # {goal_id: true|false|unknown}
    retried: bool = False           # cannot_be_proved bought a preciseActions retry


@dataclass
class Aggregated(Event):
    """The run's answers, as the aggregate step worked them out.

    The conjunction rule (any false makes it false, else any unknown makes it
    unknown) lives in that step alone; the result is on the ledger so a reader
    takes it rather than recomputing it from the per-scenario verdicts.
    """

    results: list = field(default_factory=list)   # [{id, verdict, description?}]


@dataclass
class CrossChecked(Event):
    """cross_check's cell-by-cell comparison against ground truth, putting the
    expected verdict next to the one this run produced. Emitted before the
    mismatch failure is raised, so a failed run still carries it."""
    cells: list = field(default_factory=list)
    # [{id, scenario: [{id, subtype}], ours, expected, match}] — the scenario
    # key is the complete assignment, the same encoding cases_results uses.
    results: list = field(default_factory=list)
    # [{id, ours, expected, match}] — the same comparison one level up, at the
    # aggregated answer, so a reader never re-derives it from the cells.


@dataclass
class Invalidated(Event):
    targets: list[str] = field(default_factory=list)  # superseded relative paths (sealed in place)


@dataclass
class Interrupted(Event):
    scope: str = "run"


@dataclass
class RunFinished(Event):
    pass


@dataclass
class RunFailed(Event):
    reason: str = ""
    # Why the run stopped: "check" = a node's check did not pass (the run has an
    # answer, just not the expected one), "crash" = a node could not finish.
    kind: str = "crash"
    #: Where it happened, as the step's identity path
    #: (``scenarios/baseline/inject/Secrecy``) — the same address a fix or a
    #: re-entry is aimed by. Empty on the run's serial spine, where the node name
    #: in the envelope says it all, and when concurrent siblings failed in
    #: different places, where the reason names them all.
    where: str = ""
