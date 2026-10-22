"""Stowing the corpus's expected answers beside the runs checked against them.

For a reader, not for the pipeline: a copy under the protocol directory puts a
run's output and the corpus's answer in one ``ls``. It sits at protocol level,
since nothing inside a run directory may be something that run did not write;
``services/store/runs.py`` lists it in ``RESERVED`` and walks go through
``run_dirs``, so it is never mistaken for a result.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from orrery.services.store.runs import GROUND_TRUTH

#: What is copied over, in the corpus's own layout so the two trees read alike.
#: The corpus is not uniform, so a sub-directory it does not carry is skipped
#: in silence rather than treated as a fault.
STOWED = ("claims", "source", "formal", "results")

ORIGIN = "ORIGIN.txt"

#: The corpus directory name a recorded path is cut at. The segments above it
#: belong to one machine; the tail below it is the protocol's address.
CORPUS_DIR = "VerdictBench"


def corpus_rel(recorded: Path | str) -> str:
    """A recorded ground-truth path, as its place inside the corpus.

    ``run.json`` records an absolute path belonging to the machine that produced
    the run; the portable part is the tail after ``CORPUS_DIR``, which is the
    protocol's address. Empty string when the path does not pass through the
    corpus, the ordinary state for a run given no ground truth.
    """
    parts = Path(recorded).parts
    for i, seg in enumerate(parts):
        if seg == CORPUS_DIR:
            return "/".join(parts[i + 1:])
    return ""


def stow_ground_truth(work_root: Path, protocol_id: str,
                      ground_truth: str | Path | None) -> Path | None:
    """Copy this protocol's expected answers to
    ``<work_root>/<protocol_id>/_ground_truth/``. Returns where they landed, or
    None when the run brought no corpus.

    Idempotent by re-copying: each sub-directory in ``STOWED`` is removed and
    written again, so an edited corpus is reflected rather than merged into.
    Anything else in that directory is left alone. Raises FileNotFoundError
    when ``ground_truth`` is not a directory.
    """
    if ground_truth is None:
        return None
    src = Path(ground_truth)
    if not src.is_dir():
        raise FileNotFoundError(
            f"ground truth {src} is not a directory; nothing to stow beside "
            f"the runs of {protocol_id}")
    home = Path(work_root) / protocol_id / GROUND_TRUTH
    home.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in STOWED:
        if not (src / name).is_dir():
            continue
        dst = home / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src / name, dst)
        copied.append(name)
    # Where it came from, in the directory itself: which corpus revision an
    # experiment was scored against is worth being able to place later.
    (home / ORIGIN).write_text(
        f"copied from: {src}\n"
        f"copied at:   {datetime.now().isoformat(timespec='seconds')}\n"
        f"contents:    {', '.join(copied) if copied else '(nothing found)'}\n"
        f"\n"
        f"A copy, for reading. The pipeline never opens it: the cross_check\n"
        f"node and the read_expected tool go to the corpus above.\n",
        encoding="utf-8")
    return home
