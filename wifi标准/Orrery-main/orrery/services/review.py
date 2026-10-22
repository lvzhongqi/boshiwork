"""Whether a person has read a finished run.

A marker, not a state machine: nothing in the pipeline, the expert or the checks
reads it, and no run is blocked or reopened by it. It only lets a list of runs
say which ones somebody has been through, and puts a dated sign-off on the
ledger. Being read happens after the run, possibly weeks later and more than
once, so the console's endpoint is what writes the file.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Where the marker lives, under the run root. The leading underscore keeps it
#: out of the pipeline's and the expert's artifact tools: it is a fact about the
#: run, not one of the artifacts the run produced.
REVIEW_JSON = "_review.json"


def review_state(run_dir) -> dict:
    """This run's review state, ``{state, note}``. A missing or unreadable
    marker reads as open: a run nobody has marked is a run nobody has read."""
    path = Path(run_dir) / REVIEW_JSON
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "open", "note": ""}
