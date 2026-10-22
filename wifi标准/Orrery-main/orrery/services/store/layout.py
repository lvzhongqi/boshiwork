"""Single source of truth for the run directory layout: every path rule is
written once, here.

``open_*`` allocates — it makes a step's next directory and records it in the
index (services/store/stages); every other method resolves against that index.
Directory names are never parsed to decide anything; ``stages.jsonl`` is what
the program believes. Directories are numbered by when they ran, so re-entering
an earlier step appends instead of overwriting. No ground-truth path is offered
here: cross_check gets a scoped handle from the orchestration layer instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from orrery.services.store import stages
from orrery.services.store.atomic import write_text
from orrery.services.store.stages import Stage

# A step's session file and the sub-directory its prompts and repair rounds
# land in. Every session rule keys on these exact names.
TRANSCRIPT = "transcript.jsonl"
ROUNDS = "rounds"
REDACTED = "********"


def _redact_config(value, path: tuple[str, ...] = ()):
    """Return a YAML-safe copy with credentials and relay URLs removed.

    Key matching ignores case and ``_``/``-``, so ``api_key``, ``api-key`` and
    ``apiKey`` cannot diverge into safe and unsafe spellings; the ``apykey``
    misspelling is covered too. Backend relay URLs (``llm.url`` and every
    ``llm.profiles.<backend>.url``) are dropped rather than masked. The input
    is never mutated.
    """
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            name = str(key)
            normalized = name.replace("_", "").replace("-", "").lower()
            is_backend_url = normalized == "url" and (
                path == ("llm",)
                or len(path) == 3 and path[:2] == ("llm", "profiles"))
            if is_backend_url:
                continue
            if normalized == "extraheaders" and isinstance(item, Mapping):
                # A relay header is a credential as often as not
                # (Authorization, a cookie, a tenant token); the names stay,
                # since they say which relay, and every value goes.
                out[key] = {k: REDACTED for k in item}
                continue
            out[key] = (REDACTED if normalized in {"apikey", "apykey"}
                        else _redact_config(item, (*path, name)))
        return out
    if isinstance(value, (list, tuple)):
        return [_redact_config(item, path) for item in value]
    return value


def unit_name(home: Path, session_dir: Path) -> str:
    """A session's directory → the unit name its events carry, relative to
    ``home`` (``apply/03_lkr_from_start``, ``inject/00_Secrecy``).

    ``home`` is the directory that batch of sessions lands under: a scenario's
    for the scenario stage, the step's own for the root model. The name is
    derived from the path, so the ledger address and the place on disk cannot
    drift apart."""
    return str(Path(session_dir).relative_to(home))


class StageMissing(LookupError):
    """Asked for the directory of a step that has no current one.

    Either it never ran, or what it left was computed from something since
    rewritten (stages.live). Raised instead of returning a path that would be
    silently created under a caller that assumed an artifact.
    """


class RunLayout:
    """Every path inside one run directory, resolved through the stage index.

    Holds no state beyond the run's identity and a cached copy of that index.
    """

    def __init__(self, root: Path, protocol: str, run_name: str) -> None:
        self.root = Path(root)
        self.protocol = protocol
        self.run_name = run_name
        self._stages: list[Stage] | None = None

    # ── the index ────────────────────────────────────────────────────────
    @property
    def stages(self) -> list[Stage]:
        """This run's executions, loaded once and cached until something is
        allocated. Every path on the console and in the pipeline resolves
        through it."""
        if self._stages is None:
            self._stages = stages.load(self.run_dir)
        return self._stages

    def reload(self) -> None:
        """Drop the cached index so the next access re-reads it. Needed by a
        reader watching a run another process is executing — the console —
        where the index grows underneath it."""
        self._stages = None

    def adopt(self, s: Stage) -> None:
        """Record a stage whose directory was put in place outside ``_open`` —
        the fork path, which copies another run's upstream work in wholesale.
        The directory exists first; the entry is what makes it findable."""
        self._stages = [*self.stages, stages.record(self.run_dir, s)]

    def rel(self, p: Path) -> str:
        """A path inside this run → its run-relative form, which is how a step
        is addressed outside the filesystem: the index, a fix plan, the facts
        tree."""
        return "" if Path(p) == self.run_dir else str(Path(p).relative_to(self.run_dir))

    _rel = rel

    def stage_name(self, node: str) -> str:
        """The bare name of a node's current directory (``05_extract_flow``),
        for the surfaces that show a reader where something lives. Falls back
        to the node's own name when it has no directory yet."""
        d = self.find_node_dir(node)
        return d.name if d is not None else node

    def _open(self, parent: str, ident: str, kind: str,
              cause: str, by: str, resume: bool = False,
              input: str = "") -> Path:
        """Allocate one execution's directory and record it in the index.

        Called from concurrent tasks — the scenarios of one stage, the goal
        families of one scenario — and safe only because every step is
        synchronous: no await sits between reading the index and appending to
        it, so two tasks on the same loop cannot be handed the same number.
        """
        prev = stages.newest(self.stages, parent, ident)
        s = stages.allocate(self.run_dir, self.stages, parent=parent,
                            ident=ident, kind=kind, cause=cause, by=by,
                            input=input)
        self._stages = [*self.stages, s]
        d = self.run_dir / s.dir
        if resume and prev is not None and prev.dir:
            # An accepted gap asks the step to reconsider one thing, not to
            # start over, so its session travels to the new attempt. Only the
            # transcript does: the rounds stay with the attempt that wrote
            # them, and the new directory's slot band starts at 00.
            src = self.run_dir / prev.dir / TRANSCRIPT
            if src.is_file():
                (d / TRANSCRIPT).write_text(src.read_text(encoding="utf-8"),
                                            encoding="utf-8")
        return d

    def _live(self, parent: str, ident: str) -> Path | None:
        return stages.live_dir(self.run_dir, self.stages, parent, ident)

    def _need(self, parent: str, ident: str, what: str) -> Path:
        d = self._live(parent, ident)
        if d is None:
            raise StageMissing(
                f"{what} has no current directory in {self.run_name}: it "
                f"either never ran, or what it left was computed from "
                f"something that has since been re-worked")
        return d

    # ── run-level files ──────────────────────────────────────────────────
    @property
    def run_dir(self) -> Path:
        return self.root / self.protocol / self.run_name

    @property
    def run_json(self) -> Path:
        return self.run_dir / "run.json"

    @property
    def config_yaml(self) -> Path:
        """The effective configuration used by this run, with secrets removed."""
        return self.run_dir / "config.yaml"

    def write_config(self, config: Mapping) -> None:
        """Atomically record the effective config without persisting API keys."""
        if not isinstance(config, Mapping):
            raise TypeError(
                f"run config must be a mapping, got {type(config).__name__}")
        text = yaml.safe_dump(
            _redact_config(config), allow_unicode=True, sort_keys=False)
        write_text(self.config_yaml, text)

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"

    @property
    def run_log(self) -> Path:
        """This run's log file: every event as a sentence, plus what the
        console filtered out. A projection of events.jsonl for reading, never
        parsed by anything (services/logs.py)."""
        return self.run_dir / "run.log"

    @property
    def gaps_jsonl(self) -> Path:
        """The gap-report audit trail (pipeline/control/gaps writes, the expert
        overview reads)."""
        return self.run_dir / "gaps.jsonl"

    # ── nodes ────────────────────────────────────────────────────────────
    def open_node(self, node: str, *, cause: str = "initial", by: str = "",
                  resume: bool = False) -> Path:
        """Start an execution of ``node`` and return its fresh directory, with
        the previous attempt's facts carried in. The only way a node directory
        comes into being.

        ``resume`` also carries the previous attempt's session across, for the
        one case that is a continuation rather than a fresh start: the target
        of an accepted gap report.
        """
        return self._open("", node, "seq", cause, by, resume)

    def node_dir(self, node: str) -> Path:
        return self._need("", node, f"step {node!r}")

    def has(self, node: str, *parts: str) -> bool:
        """Does this step's current work include that file?

        The question every ``is_done`` asks. A step with no current directory
        answers False, so the ordinary "not run yet" stays an answer instead of
        becoming an error at every caller.
        """
        d = self.find_node_dir(node)
        return d is not None and d.joinpath(*parts).exists()

    def find_node_dir(self, node: str) -> Path | None:
        """A node's current directory, or None — for the surfaces that
        legitimately handle absence: an artifact listing, a console reading a
        run that stopped early."""
        return self._live("", node)

    def node_transcript(self, node: str) -> Path:
        return self.node_dir(node) / TRANSCRIPT

    @property
    def flow_pv(self) -> Path:
        """The flow model, read by claims and by the root step."""
        return self.node_dir("extract_flow") / "flow.pv"

    # ── where an apply chain lives, and what it leaves ───────────────────
    # build_world, build_root and every scenario all run an apply chain, and
    # all three keep one shape: an ``apply/`` band holding one directory per
    # point, with the chain's own result inside the band beside them. A chain
    # with no points still gets the directory, holding only the result.
    def apply_dir(self, home: Path) -> Path:
        return home / "apply"

    # ── the world model (build_world) ──
    # The flow model with the declared world built onto it: the terrain every
    # other assumption's guards refer to.
    @property
    def world_pv(self) -> Path:
        return self.apply_dir(self.node_dir("build_world")) / "world.pv"

    @property
    def world_notes(self) -> Path:
        """The world assignment in words: what was applied, and what the flow
        model already was and so needed nothing."""
        return self.apply_dir(self.node_dir("build_world")) / "notes.md"

    # ── the root model (build_root) ──
    # The flow model with every fixed assumption applied, written once per run
    # and read by every scenario. Its own step, so it can be re-entered and
    # fixed without touching the scenarios.
    @property
    def root_pv(self) -> Path:
        return self.apply_dir(self.node_dir("build_root")) / "root.pv"

    @property
    def root_notes(self) -> Path:
        return self.apply_dir(self.node_dir("build_root")) / "notes.md"

    # ── final answers (aggregate) and the evaluation report (cross_check) ──
    @property
    def results_json(self) -> Path:
        return self.node_dir("aggregate") / "results.json"

    @property
    def cases_results_json(self) -> Path:
        return self.node_dir("aggregate") / "cases_results.json"

    @property
    def cross_check_json(self) -> Path:
        """The evaluation report, an ordinary artifact of the cross_check node
        in its own directory like every other step's. The ground-truth fence
        still holds: this class offers no path to the corpus itself, and
        cross_check gets a scoped handle from the orchestration layer."""
        return self.node_dir("cross_check") / "cross_check.json"

    # ── scenario stage ───────────────────────────────────────────────────
    @property
    def scenarios_root(self) -> Path:
        return self.node_dir("scenarios")

    def open_scenario(self, label: str, *, cause: str = "initial",
                      by: str = "") -> Path:
        """Start an execution of one scenario. ``gen``-numbered: scenarios run
        concurrently with no order among themselves, so the number counts
        generations and every scenario of one pass shares it."""
        return self._open(self._rel(self.scenarios_root), label, "gen", cause, by)

    def scenario_dir(self, label: str) -> Path:
        return self._need(self._rel(self.scenarios_root), label,
                          f"scenario {label!r}")

    def find_scenario_dir(self, label: str) -> Path | None:
        return self._live(self._rel(self.scenarios_root), label)

    def scenario_labels(self) -> list[str]:
        """The scenarios with a current directory, by label."""
        root = self.find_node_dir("scenarios")
        if root is None:
            return []
        return sorted(stages.live(self.stages, self._rel(root)))

    def scenario_pv(self, label: str) -> Path:
        return self.apply_dir(self.scenario_dir(label)) / "scenario.pv"

    def scenario_notes(self, label: str) -> Path:
        return self.apply_dir(self.scenario_dir(label)) / "notes.md"

    def scenario_verdict(self, label: str) -> Path:
        return self.scenario_dir(label) / "verdict.json"

    # ── attack reproductions ─────────────────────────────────────────────
    #: Reproductions a person asked for after the run, beside the run's own
    #: tree rather than in it: evidence produced for a question, not an
    #: artifact the pipeline produced (the expert's deepened traces too).
    MANUAL_ATTACKS = "_attacks"

    def attack_dir(self, label: str, goal: str, *, manual: bool) -> Path:
        """Where one cell's reproduction is written: under the
        ``reproduce_attacks`` step, or under ``_attacks/`` for one asked for
        after the run."""
        if manual:
            return self.run_dir / self.MANUAL_ATTACKS / label / goal
        return self.node_dir("reproduce_attacks") / label / goal

    def attack_dirs(self, label: str, goal: str) -> list[Path]:
        """Every place a reproduction of this cell may already be, the
        pipeline step's first."""
        out = []
        step = self.find_node_dir("reproduce_attacks")
        if step is not None:
            out.append(step / label / goal)
        out.append(self.run_dir / self.MANUAL_ATTACKS / label / goal)
        return out

    # ── apply points (the root model's and every scenario's alike) ────────
    # Keyed by the directory the points land under, not by a scenario label, so
    # one rule serves both writers of an apply/ band: the root step, into its
    # own node directory, and each scenario, into its scenario directory.
    #
    # A point is identified by its rid — the assumption's own id — never by its
    # subtype: a protocol may apply one subtype to two targets (Otway-Rees
    # assumes lkr_from_start of both A and B) and the points would share a
    # name. The number beside it is execution order, not a disambiguator.
    def _apply_parent(self, home: Path) -> str:
        return self._rel(self.apply_dir(home)).lstrip("/")

    def open_apply_point(self, home: Path, rid: str, *, cause: str = "initial",
                         by: str = "") -> Path:
        """Start an execution of one apply point. ``seq``-numbered: the points
        of a chain are a fold, each taking the previous one's output, so the
        number is when it ran and a re-run lands after the points it
        invalidates."""
        return self._open(self._apply_parent(home), rid, "seq", cause, by)

    def apply_point_dir(self, home: Path, rid: str) -> Path:
        return self._need(self._apply_parent(home), rid, f"apply point {rid!r}")

    def find_apply_point_dir(self, home: Path, rid: str) -> Path | None:
        return self._live(self._apply_parent(home), rid)

    def apply_transcript(self, home: Path, rid: str) -> Path:
        return self.apply_point_dir(home, rid) / TRANSCRIPT

    # ── injections ───────────────────────────────────────────────────────
    def _inject_parent(self, label: str) -> str:
        return f"{self._rel(self.scenario_dir(label))}/inject"

    def open_inject_family(self, label: str, family: str, *,
                           cause: str = "initial", by: str = "") -> Path:
        """Start an execution of one goal family. ``gen``-numbered like
        scenarios: the families of a scenario run concurrently and none of them
        is upstream of another. Its input is the scenario's apply chain: a
        point re-worked there after this row makes the family stale, so a fix
        aimed at an apply point reaches the verdict instead of the family
        handing back the model it built on the old chain."""
        return self._open(self._inject_parent(label), family, "gen", cause, by,
                          input=self._apply_parent(self.scenario_dir(label)))

    def inject_family_dir(self, label: str, family: str) -> Path:
        return self._need(self._inject_parent(label), family,
                          f"goal family {family!r} of scenario {label!r}")

    def find_inject_family_dir(self, label: str, family: str) -> Path | None:
        return self._live(self._inject_parent(label), family)

    def inject_family_dirs(self, label: str) -> dict[str, Path]:
        """Every current goal family of one scenario, by family name."""
        return {ident: self.run_dir / s.dir
                for ident, s in stages.live(self.stages,
                                            self._inject_parent(label)).items()
                if s.dir}

    def inject_transcript(self, label: str, family: str) -> Path:
        """The transcript of one inject call. A family with more cells than
        inject_cells_per_call is split across calls, and each chunk is a
        family directory of its own (``Authentication_c2``,
        pipeline/scenarios.family_batches): one session, one model.pv, one set
        of solver logs, the same as any other family."""
        return self.inject_family_dir(label, family) / TRANSCRIPT

    def inject_model(self, label: str, family: str) -> Path:
        """The batch's model — the one file the verdicts were read off.

        It sits at the family level because a batch is one session and one
        ``.pv``. What a batch is: pipeline/scenarios.family_batches — subtypes
        that only add queries share a file, one that changes the model does
        not."""
        return self.inject_family_dir(label, family) / "model.pv"
