"""Slim the sanitised run tree into the reviewers' repository copy.

    python3 release/usenix/open_to_thin.py

Third of three steps: step 1 picks the runs, step 2 sanitises them, this one
drops what a 60 MB repository cannot hold. No options — what it reads, what it
writes and which protocols keep playback material are the constants below.

The protocols in ``PLAYABLE`` keep everything a playback reads; every other run
keeps only ``PAPER_DATA_NAMES`` and a ledger filtered to the events that
recompute the paper's tables. Redaction is step 2's alone. Nothing is gzipped,
because the console cannot open a compressed ``events.jsonl``.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Imported for ``unit_of`` alone: which corpus unit a run was scored against.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import latest_3_to_remove_sensitive_open as remove_sensitive        # noqa: E402

#: The repository this script publishes out of, resolved from ``__file__``: the
#: two trees below are its top-level entries, and read relatively they would
#: follow the caller's working directory instead.
ROOT = Path(__file__).resolve().parents[2]

#: The one tree this reads and the one it writes, both fixed: there is exactly
#: one artefact, built one way, and rebuilding it takes no arguments.
SOURCE = ROOT / "a_experiments_open/experiments"
SLIM = ROOT / "runs"

#: The protocols whose most successful main-batch run keeps everything a
#: playback reads; every other run keeps only what the paper's tables need.
#: Seven of them, chosen for spread across families: three academic (NSPK and
#: two repairs of its freshness flaw), one RFC sub-protocol, three ISO
#: mechanisms. The tuple order is the order the names are printed in.
#:
#: The ISO entries are restricted units — step 2 blanked their prompts and
#: prose values, so they play back their shape (principals, flow, scenarios,
#: ProVerif evidence, verdicts) with ``[withheld: third-party specification
#: text]`` where the document text stood.
PLAYABLE = (
    "NSPK",
    "Denning-Sacco",
    "Neuman-Stubblebine",
    "IKEv2-signature",
    "ISO-9798-2-mechanism-2",
    "ISO-9798-2-mechanism-2-no-identifier",
    "ISO-11770-3-key-agreement-mechanism-1",
)

#: What a protocol directory holds that is not a run.
SKIP_DIRS = {"_ground_truth", "_deleted_runs", "_batch_archives", "__pycache__"}

#: A run name ends in an increasing number (NSPK22).
RUN_SUFFIX = re.compile(r"(\d+)$")

# ── Slimming ─────────────────────────────────────────────────────────────────

#: Each cell's verdict evidence. The console's evidence pane links straight to
#: it (main.js::openEvidence), so it is the one piece of solver output that may
#: not be dropped.
EVIDENCE_TXT = "01_proverif.txt"


def slim_drop(rel: Path, keep_prompts: bool = False) -> str | None:
    """Whether the slim tree drops this file; the reason if it does.

    The reason is printed in the summary, so each one has to say why the file
    is not needed. The test looks only at the path inside the run, never at
    size.
    """
    name = rel.name
    if name == "run.log":
        return ("a log mirror of the ledger; the same events are in "
                "events.jsonl, which is what a playback reads")
    if name == "work.md":
        return "a rendering of the ledger, carrying nothing the ledger does not"
    if name.endswith("prompt.md") and keep_prompts:
        # Decided here rather than left to fall through: a prompt lives at
        # ``<session>/rounds/00_prompt.md``, so the per-round rule below would
        # otherwise take it back out again.
        return None
    if name.endswith("prompt.md"):
        # A run nobody plays back has no trail for its prompts to belong to.
        # A playable run keeps them: the console links to them from
        # prompt_filed.
        return ("the prompt itself, for a run that is not played back; the "
                "templates every stage renders are in the node code in this "
                "repository")
    if name.endswith(".txt") and name != EVIDENCE_TXT:
        return (f"intermediate solver output (typecheck, per-round proverif, "
                f"vacuity, per-query traces); each cell's verdict evidence is "
                f"{EVIDENCE_TXT}, which is kept")
    if "rounds" in rel.parts:
        return ("per-round intermediate artefacts; each step's final artefact "
                "is kept")
    return None


#: How much of one solver output to keep before truncating. The distribution
#: has a long tail — a median of 12 KB against a 12 MB maximum — so this cap
#: passes the vast majority through untouched and cuts the pathological few.
#: The cut is stated at the end of the file rather than made silently.
TXT_CAP = 16 * 1024


def cap_solver_output(body: str, rel: Path) -> str:
    """Truncate an over-long solver output, and say that it was truncated.

    Only ``.txt`` is touched: a ``.pv`` is a model and a ``.json`` an artefact,
    and truncating either damages it.
    """
    if not rel.name.endswith(".txt") or len(body) <= TXT_CAP:
        return body
    return (body[:TXT_CAP]
            + f"\n\n… truncated here: the original is {len(body)} characters, "
              f"the first {TXT_CAP} are kept. The complete output is in the "
              f"full artefact.\n")


#: The events a ledger keeps when its run is not playable. The first six are
#: every type ``tools/sync_data.py`` opens. The last three are read by nothing
#: and cost 0.1 MB across the batch; a ledger that cannot say how its own
#: run ended is not worth keeping.
PAPER_LEDGER_EVENTS = frozenset({
    "run_started", "node_finished", "scenario_started", "scenario_finished",
    "session_usage", "solve_finished",
    "run_finished", "run_failed", "interrupted",
})


def trim_ledger(text: str, where: Path) -> str:
    """A non-playable run's ledger, cut to the events something reads.

    The ledger is 98% of the artefact's ``events.jsonl`` bytes and 0% of what
    is played back; filtering takes the tree from 34.1 MB to 14.9. A trimmed
    ledger is no longer the run's record, so questions like why a check failed
    have to be asked of the full tree published beside this one.

    Gaps in ``seq`` are safe, which is what makes the filter possible: every
    reader either filters by type (the paper's script) or treats ``seq`` as an
    idempotent resume point (the console's fold, ``applyEvent``).
    """
    kept = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue                    # a torn tail; every reader drops it
        if row.get("t") in PAPER_LEDGER_EVENTS:
            kept.append(line)
    return "".join(l + "\n" for l in kept)


#: The fields of a reply a playback reads: ``thinking`` and ``content`` are the
#: texts the console rebuilds token fragments from, ``tool_calls`` is what the
#: command-line playback hands back for a round, ``usage`` is the figure on
#: screen. ``thinking_blocks`` is absent — provider resume signatures a playback
#: never uses, and two thirds of every assistant line.
REPLY_FIELDS = ("content", "thinking", "tool_calls", "usage", "reason")


def compact_reply(entry: dict) -> dict:
    """One reply, cut down to the fields a playback reads.

    Every ``tool_calls`` entry carries both ``arguments`` (the raw JSON string)
    and ``arguments_json`` (the same thing parsed); the string is what the model
    actually sent, so it is what survives.
    """
    out = {"t": entry["t"]}
    for k in REPLY_FIELDS:
        v = entry.get(k)
        if k == "tool_calls" and v:
            v = [{kk: vv for kk, vv in c.items() if kk != "arguments_json"}
                 for c in v]
        if v:
            out[k] = v
    return out


def trim_transcript(text: str, where: Path) -> str:
    """The slim tree's transcript: ``meta`` and the replies, replies compacted.

    ``system`` / ``user`` / ``tool_result`` are the questions and a playback
    takes only the answers; the surviving reply fields are ``REPLY_FIELDS``.
    The result is a fifth of the size and can no longer be restored into a
    resumable session by ``TranscriptReader.messages()``.

    A damaged last line is dropped under kill semantics (the same rule as
    ``read_jsonl_tolerant``); a damaged middle line means the file was edited
    externally and raises SystemExit.
    """
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break
            raise SystemExit(
                f"{where}:{i + 1}: not valid JSON on a middle line; this file "
                f"was edited externally")
        t = entry.get("t")
        if t == "meta":
            out.append(line)
        elif t in ("assistant", "rejected"):
            out.append(json.dumps(compact_reply(entry), ensure_ascii=False))
    return "".join(l + "\n" for l in out)


# ── Paper data and playback material ───────────────────────────────────────────

#: The files the paper's tables are built from, which every run keeps: what
#: ``tools/sync_data.py`` opens, plus the two the console's run list needs and
#: each run's own config.yaml.
#:
#: principals.json, properties.json and claims.json are not here: the ones the
#: paper's script reads live in the corpus, while the same names inside a run
#: are that run's own extraction, which is playback material.
PAPER_DATA_NAMES = frozenset({
    # What tools/sync_data.py opens inside a run. Checked against the script:
    # it never mentions stages.jsonl or cases_results.json, and all three of
    # its `results.json` reads are corpus paths, not run paths.
    "run.json", "events.jsonl", "repair.json",
    "cross_check.json",         # the main batch's
    "crosscheck.json",          # the one-shot baseline's

    # The console's run list rather than sync_data's: `_summarize` resolves the
    # aggregate step through the stage index and reads its results.json, which
    # is where the Verdicts and Acc columns come from.
    "stages.jsonl", "results.json",

    # Neither consumer opens it. With no batch-level config.yaml it is the
    # only record of what a run was configured to do, and the only place the
    # artefact and the paper can be checked against each other: this batch
    # ran at a 300 s ProVerif budget and 120 tool calls, neither the released
    # default. It costs 0.7 MB across the 454 runs that recorded one.
    "config.yaml",
})

#: The one file under ``eval/`` either consumer reads. The rest of that
#: directory is the detail ``summary.json`` summarises: the console's eval
#: panel reads the summary alone, and the paper's script never looks below
#: ``eval/summary.json``.
EVAL_SUMMARY = "summary.json"


def is_paper_data(rel: Path) -> bool:
    """Whether either consumer reads this file.

    A run outside ``PLAYABLE`` keeps exactly this and nothing more. The set is
    the measured one: every other ``.json`` under ``eval/`` and
    ``cases_results.json`` are 4.4 MB that nothing in the artefact opens.
    """
    return rel.name in PAPER_DATA_NAMES or (
        rel.parent.name == "eval" and rel.name == EVAL_SUMMARY)


#: The batch playback material comes from. Only the main batch runs the
#: whole pipeline: a claims run stops at ``extract_claims``, and a one-shot
#: baseline run has no ledger, which is the very thing a playback plays.
PLAYBACK_BATCH = "main"

#: How run.json's status ranks: finished and checked, finished but not checked,
#: everything else.
_STATUS_RANK = {"ok": 2, "check_failed": 1}


def run_quality(run_dir: Path) -> tuple:
    """How successful this run was; larger is better.

    The measure is the console's own (``services/store/runs.py::_summarize``):
    run.json's status first, then the accuracy the cross-check reported, so
    "most successful" means the same here and in the run list. The cross-check
    is the last ``*cross_check*/`` directory, the rule ``sync_data`` uses,
    because a run that went back has more than one.
    """
    try:
        meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    rank = _STATUS_RANK.get(str(meta.get("status", "")), 0)
    acc = -1.0
    hits = sorted(run_dir.glob("*cross_check*/cross_check.json"))
    if hits:
        try:
            got = json.loads(hits[-1].read_text(encoding="utf-8")).get("acc")
            if isinstance(got, (int, float)):
                acc = float(got)
        except (OSError, ValueError):
            pass
    m = RUN_SUFFIX.search(run_dir.name)
    return (rank, acc, int(m.group(1)) if m else 0)


def best_run(runs: list[Path]) -> Path:
    """Which run carries the playback material: the most successful one.

    The paper's figures still draw on every run in the input, so this choice
    changes what is seen, never what is counted.
    """
    return max(runs, key=run_quality)


# ── The outputs ──────────────────────────────────────────────────────────────

@dataclass
class Output:
    """One output tree, and the tally it accumulates along the way."""

    root: Path
    slim: bool
    files: int = 0
    bytes: int = 0
    dropped: Counter = field(default_factory=Counter)
    dropped_bytes: Counter = field(default_factory=Counter)
    binary: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return "slim" if self.slim else "full"


def emit(outputs: list[Output], rel: Path, src: Path, *,
         in_run: Path | None = None, paper_only: bool = False) -> None:
    """One source file, written into the output if it survives the rules.

    ``in_run`` is the file's path inside the run directory, which only files
    inside a run have; it is the precondition the drop rules read, and files
    from outside a run pass ``None``.

    The text goes through unchanged apart from the trims below: it arrived
    sanitised from step 2, and redaction stays there in one copy.
    """
    raw = src.read_bytes()
    try:
        text: str | None = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None                             # binary, copied verbatim

    for out in outputs:
        reason = (slim_drop(in_run, keep_prompts=not paper_only)
                  if (out.slim and in_run is not None) else None)
        if reason is None and out.slim and paper_only and in_run is not None \
                and not is_paper_data(in_run):
            reason = ("this protocol is not in PLAYABLE, so only the files "
                      "the paper's tables need are kept")
        if reason:
            out.dropped[reason] += 1
            out.dropped_bytes[reason] += len(raw)
            continue
        dst = out.root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            out.binary.append(str(rel))
            dst.write_bytes(raw)
            out.files += 1
            out.bytes += len(raw)
            continue
        body = text
        if out.slim and in_run is not None:
            if in_run.name == "transcript.jsonl":
                body = trim_transcript(body, src)
            elif paper_only and in_run.name == "events.jsonl":
                body = trim_ledger(body, src)
            else:
                body = cap_solver_output(body, in_run)
        data = body.encode("utf-8")
        dst.write_bytes(data)
        out.files += 1
        out.bytes += len(data)


# ── Walking the input ────────────────────────────────────────────────────────

def find_runs(root: Path) -> dict[tuple[str, str], list[Path]]:
    """Every run in the input, grouped by (batch, protocol directory name).

    Found by searching for ``run.json`` rather than by reading the batch state,
    which names protocol directories one level under a batch while baseline
    runs sit at two depths (``baseline/<protocol>/`` and
    ``baseline/runs/<protocol>/``).

    The key is what ``PLAYABLE`` matches and what ``best_run`` chooses within,
    so a protocol at both depths is two groups, each keeping its own best run.
    Raises SystemExit if a run sits directly under the input root.
    """
    groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for meta in sorted(root.rglob("run.json")):
        run_dir = meta.parent
        rel = run_dir.relative_to(root)
        if any(part in SKIP_DIRS or part == "_history" for part in rel.parts):
            continue
        # A symlink would reach a run that is already listed and pack a
        # protocol twice. Steps 1 and 2 deliver none, so this rarely fires.
        cur = root
        if any((cur := cur / part).is_symlink() for part in rel.parts):
            continue
        if len(rel.parts) < 2:
            raise SystemExit(
                f"a run directly under the input root has no batch or "
                f"protocol: {rel}")
        groups[(rel.parts[0], run_dir.parent.name)].append(run_dir)
    return groups


def pack_run(run_dir: Path, rel_base: Path, outputs: list[Output],
             paper_only: bool = False) -> None:
    """One run, into every output, then the stage index brought into line."""
    for src in sorted(run_dir.rglob("*")):
        rel = src.relative_to(run_dir)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if not src.is_file():
            continue
        emit(outputs, rel_base / rel, src, in_run=rel,
             paper_only=paper_only)
    for out in outputs:
        # Charged back because this rewrites a file emit already counted;
        # uncharged, the tally read 7% over the tree on disk.
        out.bytes -= trim_stage_index(out.root / rel_base)


def trim_stage_index(run_out: Path) -> int:
    """Rewrite this run's ``stages.jsonl`` to the steps that survived.

    The index describes the tree rather than binding it, and the console checks
    the two against each other (``run_tree``'s ``problems``): a step recorded
    here whose directory was slimmed away shows up as "recorded in
    stages.jsonl, not on disk", a run declaring itself broken over the packing.

    An entry is dropped only when its directory is gone, ``run.json``'s
    ``nodes`` still records every step the run executed, and the aggregate step
    survives, so the run list's Verdicts and Acc columns are unaffected.

    Returns the bytes removed, which the caller charges back against a file
    ``emit`` has already counted.
    """
    index = run_out / "stages.jsonl"
    if not index.is_file():
        return 0
    was = index.stat().st_size
    kept = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue                    # a torn tail; the engine drops it too
        if (run_out / row.get("dir", "")).is_dir():
            kept.append(line)
    index.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    return was - index.stat().st_size


# ── Whether the output can still be played back ─────────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    lines = path.read_text("utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break               # the half line a kill leaves behind
            raise SystemExit(f"{path}:{i + 1}: not valid JSON on a middle line")
    return rows


def _session_key(row: dict) -> tuple:
    return row.get("node"), row.get("scenario"), row.get("unit")


def playback_problems(run_out: Path, label: str) -> list[str]:
    """Check the packed run against its own ledger: can it still be played back?

    The ledger says a session ran N rounds, so that session's transcript has to
    hold N replies; one short and the playback breaks at that round. A session
    is two levels up from ``prompt_filed``'s run-relative ``path``, the engine's
    own layout (``services/transcript/prompt.py``).

    Attribution follows the stream rather than a table keyed on (node, scenario,
    unit): extract_flow's main session and the review sub-session after it agree
    on all three, so each ``round_started`` lands on whichever session the last
    ``prompt_filed`` made current. Sessions sharing a key run one after another.

    A run with no ledger is not a problem: the one-shot baseline has none.
    """
    ledger = run_out / "events.jsonl"
    if not ledger.is_file():
        return []

    problems: list[str] = []
    current: dict[tuple, Path] = {}     # key -> the session being written now
    rounds: dict[Path, int] = {}        # session -> highest round the ledger has
    for row in _read_jsonl(ledger):
        key = _session_key(row)
        if row.get("t") == "prompt_filed":
            path = (row.get("data") or {}).get("path") or ""
            if path:
                current[key] = Path(path).parent.parent
        elif row.get("t") == "round_started":
            session = current.get(key)
            if session is None:
                problems.append(
                    f"{label}: round_started {key} with no prompt_filed before "
                    f"it, so its session cannot be located")
                continue
            no = int((row.get("data") or {}).get("round_no") or 1)
            rounds[session] = max(rounds.get(session, 0), no)

    for session, need in sorted(rounds.items()):
        transcript = run_out / session / "transcript.jsonl"
        if not transcript.is_file():
            problems.append(
                f"{label}: {session}/transcript.jsonl is missing, so the "
                f"{need} round(s) the ledger recorded have no replies to play")
            continue
        got = sum(1 for e in _read_jsonl(transcript)
                  if e.get("t") in ("assistant", "rejected"))
        if got < need:
            problems.append(
                f"{label}: {session}/transcript.jsonl holds {got} replies, "
                f"but the ledger recorded {need} rounds")
    return problems


# ── The audit ────────────────────────────────────────────────────────────────

def main() -> None:
    root = SOURCE.resolve()
    if not root.is_dir():
        raise SystemExit(
            f"no such input tree: {root}\n"
            f"  It is step 2's output. Run the three steps in order; "
            f"release/usenix/README.md has them.")


    # One output. A byte-exact companion cannot be written here: these runs
    # carry ISO/IEC, 3GPP and FIDO specification text that may not be
    # redistributed. Step 2 prepares the full tree, having removed that text.
    outputs = [Output(root=SLIM.resolve(), slim=True)]
    for out in outputs:
        if out.root.exists():
            raise SystemExit(f"output directory exists; refusing to overwrite: "
                             f"{out.root}")


    groups = find_runs(root)
    if not groups:
        raise SystemExit(f"no run.json anywhere under {root}")

    # Checked before anything is packed: a mistyped name is one protocol fewer
    # that can be played back, on an output that looks entirely normal.
    playable_protocols = {proto for batch, proto in groups
                            if batch == PLAYBACK_BATCH}
    unknown = [p for p in PLAYABLE if p not in playable_protocols]
    if unknown:
        raise SystemExit(
            f"PLAYABLE names protocols with no {PLAYBACK_BATCH} runs in "
            f"{root}: {', '.join(unknown)}\n"
            f"  A protocol name is a run's parent directory under "
            f"{PLAYBACK_BATCH}/, e.g. NSPK or IKEv2-signature")

    problems: list[str] = []
    chosen: list[str] = []
    #: corpus unit -> the playable run scored against it. Nothing of the corpus
    #: is packed; the console re-anchors recorded ground-truth paths on whatever
    #: corpus sits beside the runs (api/playback.py::reference_root). This only
    #: prints which units a reader needs for the comparison pane to fill.
    playback_units: dict[str, Path] = {}

    for (batch, proto), runs in sorted(groups.items()):
        # Playback material goes only to the protocols named, and only to their
        # most successful run.
        recorded_run = (best_run(runs)
                      if (batch == PLAYBACK_BATCH
                          and (not PLAYABLE or proto in PLAYABLE))
                      else None)
        if recorded_run is not None:
            if PLAYABLE:
                chosen.append(f"{recorded_run.relative_to(root)}")
            if (unit := remove_sensitive.unit_of(recorded_run)):
                playback_units[unit] = recorded_run
        for run_dir in sorted(runs):
            rel = run_dir.relative_to(root)
            pack_run(run_dir, rel, outputs,
                     paper_only=run_dir != recorded_run)
            # Only what carries playback material is checked: a paper-data run
            # has no transcripts by design, so the question does not apply.
            for out in outputs:
                if out.slim and run_dir != recorded_run:
                    continue
                problems += playback_problems(out.root / rel,
                                            f"{out.label}/{rel}")

    # Nothing of the batch's own scaffolding comes across. A batch-level
    # config.yaml is the console's working copy rather than what the batch
    # ran under, and each run's own is in PAPER_DATA_NAMES instead. The batch
    # state (``_batch/``) is 10 MB describing the last attempt at each protocol
    # while the tree holds the runs the paper folds — different selections: for
    # the claims batch not one of the 104 state files names a run that is
    # here.

    if PLAYABLE:
        print(f"{len(PLAYABLE)} playable protocol(s); the run each one "
              f"keeps full material for:")
        for line in chosen[:12]:
            print(f"    {line}")
        if len(chosen) > 12:
            print(f"    …and {len(chosen) - 12} more")

    if playback_units:
        print(f"the {len(playback_units)} playable run(s) were scored against "
              f"these corpus units; the comparison pane fills when a corpus "
              f"holding them sits beside this tree:")
        for unit in sorted(playback_units):
            print(f"    {unit}")

    for out in outputs:
        print(f"[{out.label}] {out.files} files, {out.bytes / 2**20:.2f} MB "
              f"-> {out.root}")
        for reason, n in out.dropped.most_common():
            print(f"    dropped {n:6d} / "
                  f"{out.dropped_bytes[reason] / 2**20:6.0f} MB  {reason}")
        if out.binary:
            print(f"    ! {len(out.binary)} binary file(s) copied verbatim; "
                  f"redaction cannot see inside them: "
                  f"{', '.join(out.binary[:3])}"
                  + ("…" if len(out.binary) > 3 else ""))

    if problems:
        head = f"{len(problems)} packed run(s) cannot be played back:"
        body = "\n  ".join(problems[:10])
        tail = f"\n  …and {len(problems) - 10} more" if len(problems) > 10 else ""
        raise SystemExit(f"{head}\n  {body}{tail}")


if __name__ == "__main__":
    main()
