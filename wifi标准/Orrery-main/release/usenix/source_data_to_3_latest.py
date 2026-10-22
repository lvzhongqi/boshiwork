"""Copy out exactly the runs the paper's numbers are computed from.

    python3 release/usenix/source_data_to_3_latest.py \
        a_experiments/experiments a_experiments_3/experiments \
        --verify-against <paper>/tmp/experiments

First of three steps, and it only selects: redaction is step 2's, slimming is
step 3's. The windows transcribe ``tools/sync_data.py`` in the paper
repository — main and baseline keep each unit's most recent ``N_RUNS``
end-to-end runs, claims keeps the newest run per scored setup stage — and
``--verify-against`` compares the result run for run against the paper's own
run cache, which is what ``sync_data.py`` itself reads.

Runs are ordered by ``started``, not by the number in the directory name.
Only ``_history`` is skipped, so a run under ``_deleted_runs/`` still counts,
and ``baseline/`` holds runs at two depths, ``baseline/<protocol>/`` and
``baseline/runs/<protocol>/``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

#: The families the paper reports (``sync_data.py::FAMILIES``); each is a
#: unit-path prefix relative to the corpus.
PAPER_FAMILIES = (
    "academic/NSPK", "academic/NSSK", "academic/Denning-Sacco",
    "academic/Kao-Chow", "academic/Otway-Rees", "academic/Yahalom",
    "academic/wide-mouth-frog", "academic/Neuman-Stubblebine",

    "rfc/EDHOC/draft-08/subprotocols/symmetric",
    "rfc/EDHOC/draft-12/subprotocols/dh",
    "rfc/IKEV2", "rfc/TLS13/draft18", "rfc/TLS13/draft20", "rfc/OAuth-2.0",
    "3gpp/5G-AKA", "informal/FIDO", "informal/Signal",

    "ISO/11770-2-symmetric-techniques", "ISO/11770-3-asymmetric-techniques",
    "ISO/11770-4-weak-secrets", "ISO/11770-7-cross-domain-key-exchange",
    "ISO/9798-2-symmetric-encipherment", "ISO/9798-3-digital-signature",
    "ISO/9798-4-cryptographic-check", "ISO/9798-5-zero-knowledge",
    "ISO/9798-6-manual-data-transfer",
)

#: Units the corpus holds that the paper drops from every table and every
#: ``\lib*`` total (``sync_data.py::EXCLUDED``). Exclusion wins over a family
#: match: EDHOC draft-08's asymmetric method sits under ``rfc/EDHOC``.
PAPER_EXCLUDED = (
    "rfc/EAP-AKA-prime",
    "informal/Bluetooth",
    "3gpp/AKMA",
    "rfc/EDHOC/draft-08/subprotocols/asymmetric",
)

#: ``\nRuns`` in ``data/setup.tex``: how many repeats the batch ran, and the
#: window main and baseline are folded over.
N_RUNS = 3

#: The corpus directory name, the anchor for turning a recorded absolute path
#: back into a unit (``sync_data.py::local_gt``).
CORPUS_NAME = "VerdictBench"

#: The three setup stages the claims batch contributes, as
#: ``RunScore.__init__`` names them.
SETUP_NODES = (("assum", "extract_assumptions"),
               ("props", "extract_properties"),
               ("claims", "extract_claims"))

_VERSIONED = re.compile(r"^(?P<series>.+)-v(?P<number>[1-9]\d*)$")
_LIB = re.compile(r"(?:^|/)%s/(.+)$" % re.escape(CORPUS_NAME))


def _load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _first_start(run_dir: Path) -> dict | None:
    """The ``run_started`` event that opened this run, or None.

    A restarted run has its run.json rewritten in place, so ``from_node`` then
    describes the restart. The event log is append-only, so its first
    ``run_started`` still says what the run set out to do.
    """
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("t") == "run_started":
                    return ev.get("data") or {}
    except OSError:
        return None
    return None


def _oneshot_unit(meta: dict) -> str | None:
    """The unit a one-shot baseline record names, from its protocol
    directory and sub-protocol."""
    got = (meta.get("protocol_dir") or "").rstrip("/")
    if not got:
        return None
    sub = meta.get("subprotocol")
    if not sub or got.endswith(f"/subprotocols/{sub}"):
        return got
    if got.endswith("/subprotocols"):
        return f"{got}/{sub}"
    if "/subprotocols/" in got:
        # The same refusal as reproduce._oneshot_ground_truth: a directory
        # already naming another sub-protocol would otherwise be mapped to a
        # unit that does not exist.
        raise ValueError(f"one-shot protocol_dir {got!r} conflicts with "
                         f"subprotocol {sub!r}")
    return f"{got}/subprotocols/{sub}"


def _through_symlink(root: Path, path: Path) -> bool:
    """Whether reaching ``path`` from ``root`` passes through a symlink. The
    ``latest`` pointer is one, and walking into it reaches a run twice."""
    cur = root
    for part in path.relative_to(root).parts:
        cur = cur / part
        if cur.is_symlink():
            return True
    return False


def _no_symlinks(directory: str, names: list[str]) -> set[str]:
    """``shutil.copytree`` ignore rule: never deliver a symlink.

    A published run directory is read file by file by the two steps after this,
    and a pointer in it is either a duplicate of something already delivered or
    a path that leaves the tree.
    """
    here = Path(directory)
    return {n for n in names if (here / n).is_symlink()}


def _setup_keys(summary: dict) -> set[str]:
    """Which of ``SETUP_NODES`` this run actually scored.

    A stage counts as scored only when its summary block is a mapping, is not
    marked ``supplied`` and carries a denominator: a supplied artefact has
    nothing of ours to score, and a failed scoring pass left no numbers.
    """
    prod = (summary or {}).get("products") or {}
    keys = set()
    for key, node in SETUP_NODES:
        block = prod.get(node)
        if (isinstance(block, dict) and not block.get("supplied")
                and block.get("den") is not None):
            keys.add(key)
    return keys


class Run:
    """One run as the selection rules see it."""

    __slots__ = ("dir", "rel", "unit", "started", "kind", "setup")

    def __init__(self, run_dir: Path, rel: Path, unit: str, meta: dict,
                 summary: dict) -> None:
        self.dir = run_dir
        self.rel = rel
        self.unit = unit
        self.started = meta.get("started", "") or meta.get("finished_at", "")
        if meta.get("experiment") == "oneshot":
            self.kind, self.setup = "e2e", set()
            return
        from_node = meta.get("from_node")
        start = _first_start(run_dir)
        # A restart after a crash keeps the run end to end.
        if from_node and start is not None and not start.get("from_node"):
            from_node = None
        terminal = meta.get("to_node") in (None, "cross_check")
        self.kind = ("e2e" if not from_node and terminal
                     and not meta.get("forked_from") else "stage")
        self.setup = _setup_keys(summary)


def in_paper(unit: str) -> bool:
    """Whether the paper reports this unit. Prefix match, exclusion first."""
    def under(rel: str, pre: str) -> bool:
        return rel == pre or rel.startswith(pre + "/")
    if any(under(unit, e) for e in PAPER_EXCLUDED):
        return False
    return any(under(unit, f) for f in PAPER_FAMILIES)


def scan(batch_root: Path, root: Path) -> dict[str, list[Run]]:
    """Every run under one batch, keyed by unit, oldest first.

    Transcribes ``sync_data.py::scan_runs`` and ``_sort_run_scores``. Only
    ``_history`` is skipped; ``_deleted_runs`` is walked, because the script
    this follows walks it.
    """
    by_unit: dict[str, list[Run]] = defaultdict(list)
    for meta_path in sorted(batch_root.rglob("run.json")):
        if "_history" in meta_path.parts:
            continue
        run_dir = meta_path.parent
        if _through_symlink(batch_root, run_dir):
            continue
        meta = _load(meta_path)
        got = meta.get("ground_truth") or (
            _oneshot_unit(meta) if meta.get("protocol_dir") else None)
        if not got:
            continue
        summary_path = run_dir / "eval" / "summary.json"
        summary = _load(summary_path) if summary_path.is_file() else {}
        if not summary_path.is_file() and not meta.get("experiment"):
            nodes = meta.get("nodes") or {}
            if nodes.get("extract_flow") not in ("ok", "failed"):
                continue
        m = _LIB.search(got)
        unit = m.group(1) if m else got
        by_unit[unit].append(
            Run(run_dir, run_dir.relative_to(root), unit, meta, summary))

    ordered = {}
    for unit, runs in by_unit.items():
        matches = [_VERSIONED.fullmatch(r.dir.name) for r in runs]
        if (matches and all(x is not None for x in matches)
                and len({x.group("series") for x in matches}) == 1):
            runs = sorted(runs, key=lambda r: int(
                _VERSIONED.fullmatch(r.dir.name).group("number")))
        else:
            runs = sorted(runs, key=lambda r: (r.started, r.dir.name))
        ordered[unit] = runs
    return ordered


def select(root: Path, last: int = N_RUNS) -> dict[str, set[Path]]:
    """The runs the paper's numbers depend on, per batch, as paths relative
    to ``root``. See this module's docstring for why the three differ."""
    chosen: dict[str, set[Path]] = {}
    for batch in ("main", "baseline"):
        picked: set[Path] = set()
        for unit, runs in scan(root / batch, root).items():
            if not in_paper(unit):
                continue
            e2e = [r for r in runs if r.kind == "e2e"]
            picked.update(r.rel for r in (e2e[-last:] if last else e2e))
        chosen[batch] = picked

    picked = set()
    for unit, runs in scan(root / "claims", root).items():
        if not in_paper(unit):
            continue
        for key, _ in SETUP_NODES:
            scored = [r for r in runs if key in r.setup]
            if scored:
                picked.add(scored[-1].rel)
    chosen["claims"] = picked
    return chosen


def flatten(rel: Path) -> Path:
    """Where a run goes in the delivered tree: ``<batch>/<protocol>/<run>``.

    Baseline keeps most of its runs a level deeper, under
    ``baseline/runs/<protocol>/<run>``, which the console's two-level listing
    never reaches. Flattening here gives both delivered trees one shape from
    one rule. Nothing inside a run refers to where the run sits, so moving one
    is safe.
    """
    parts = rel.parts
    return Path(parts[0], parts[-2], parts[-1])


def copy_out(root: Path, dest: Path, chosen: dict[str, set[Path]]) -> int:
    """Copy the selected runs whole and unmodified; this step does not edit.

    Three things at batch level stay behind. ``_batch/``, whose state table
    records the batch running out of credit rather than what the runs did,
    and whose logs echo their children's prompts and so the restricted
    specifications. The ``latest`` symlinks, which name nothing in a fixed
    selection. And the batch's own ``config.yaml``, the console's working
    copy, which had drifted from the file the batch was launched under.

    Each run's own ``config.yaml`` travels instead: the configuration that run
    used, credentials already masked. A run that recorded none keeps none.
    """
    copied = 0
    placed: dict[Path, Path] = {}
    for batch, rels in sorted(chosen.items()):
        for rel in sorted(rels):
            out = flatten(rel)
            # Two source paths landing on one delivered path would silently
            # merge two runs into one directory holding half of each.
            if (clash := placed.get(out)) is not None:
                raise SystemExit(
                    f"two runs would be delivered to the same place:\n"
                    f"  {clash}\n  {rel}\n  both -> {out}")
            placed[out] = rel
            # ``ignore=_no_symlinks``, not ``symlinks=False``: the latter
            # follows a link and delivers a second copy of its target under the
            # link's name.
            shutil.copytree(root / rel, dest / out, ignore=_no_symlinks)
            copied += 1
        have = sum(1 for rel in rels
                   if (dest / flatten(rel) / "config.yaml").is_file())
        print(f"  {batch:9s} {have} of {len(rels)} run(s) recorded their "
              f"own configuration")

    return copied


def main() -> None:
    """Command line: select, optionally verify against the paper's cache, copy."""
    ap = argparse.ArgumentParser(
        description="Copy out exactly the runs the paper's numbers use")
    ap.add_argument("source", type=Path,
                    help="the experiment tree to select from (holding main/, "
                         "claims/, baseline/)")
    ap.add_argument("dest", type=Path,
                    help="where to write the selection; must not exist")
    ap.add_argument("--last", type=int, default=N_RUNS, metavar="N",
                    help=f"the main/baseline window, i.e. the paper's \\nRuns "
                         f"(default {N_RUNS})")
    ap.add_argument("--verify-against", type=Path, default=None, metavar="DIR",
                    help="the paper's own run cache (<paper>/tmp/experiments). "
                         "The selection is compared against it run by run and "
                         "a mismatch is fatal")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the selection; write nothing")
    args = ap.parse_args()

    args.source = args.source.resolve()
    if not args.source.is_dir():
        raise SystemExit(f"no such source tree: {args.source}")
    for batch in ("main", "claims", "baseline"):
        if not (args.source / batch).is_dir():
            raise SystemExit(f"{args.source} has no {batch}/ batch")

    chosen = select(args.source, args.last)
    total = sum(len(v) for v in chosen.values())
    for batch in ("main", "claims", "baseline"):
        rule = {"main": f"most recent {args.last} end-to-end runs per unit",
                "baseline": f"most recent {args.last} end-to-end runs per unit",
                "claims": "newest run per scored setup stage"}[batch]
        print(f"  {batch:9s} {len(chosen[batch]):4d} runs   ({rule})")
    print(f"  {'total':9s} {total:4d} runs")

    # The cache is what sync_data.py reads, so a selection matching it run for
    # run is the selection the published numbers came from.
    if args.verify_against:
        cache = args.verify_against.resolve()
        if not cache.is_dir():
            raise SystemExit(f"no such run cache: {cache}")
        theirs = select(cache, args.last)
        bad = []
        for batch in sorted(set(chosen) | set(theirs)):
            mine, ref = chosen.get(batch, set()), theirs.get(batch, set())
            ident = lambda rels: {(r.parts[0], r.parts[-2], r.parts[-1])
                                  for r in rels}
            for rel in sorted(ident(mine) - ident(ref)):
                bad.append(f"{batch}: {'/'.join(rel)} selected here, not in "
                           f"the cache")
            for rel in sorted(ident(ref) - ident(mine)):
                bad.append(f"{batch}: {'/'.join(rel)} in the cache, not "
                           f"selected here")
        if bad:
            raise SystemExit(
                f"the selection does not match the paper's own run cache "
                f"({len(bad)} difference(s)); the tree this ran on is not the "
                f"one the published numbers came from:\n  "
                + "\n  ".join(bad[:20])
                + (f"\n  …and {len(bad) - 20} more" if len(bad) > 20 else ""))
        print(f"  verified against {cache}: identical, run for run")

    if args.dry_run:
        print("dry run: nothing written")
        return
    if args.dest.exists():
        raise SystemExit(f"destination exists; refusing to overwrite: "
                         f"{args.dest}")
    copied = copy_out(args.source, args.dest, chosen)
    print(f"copied {copied} runs -> {args.dest}")

    # A copy is a place a selection can silently change: a missed symlink, a
    # permission error swallowed by copytree. Compared by identity — batch,
    # protocol, run name — not by path, since the copy is flattened.
    again = select(args.dest, args.last)
    ident = lambda rels: {(r.parts[0], r.parts[-2], r.parts[-1]) for r in rels}
    drift = {c: (ident(chosen[c]) ^ ident(again.get(c, set()))) for c in chosen}
    drift = {c: v for c, v in drift.items() if v}
    if drift:
        raise SystemExit(
            f"the copy does not select the same runs as the source: "
            + "; ".join(f"{c}: {len(v)} differ" for c, v in drift.items()))
    print("re-selected from the copy: identical")


if __name__ == "__main__":
    main()
