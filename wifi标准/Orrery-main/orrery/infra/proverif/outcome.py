"""The five-way classification of a ProVerif run, shared by the ``run_proverif``
tool and the solve node: OK, SYNTAX_ERROR, SOLVER_LIMIT, TIMEOUT, RESOURCE_LIMIT.
Only SYNTAX_ERROR triggers a repair round; the other three mean the solver could
not decide. ``cannot_be_proved`` is a query-level verdict inside an OK outcome,
not a run-level kind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from orrery.infra.proverif.runner import RawRun


class OutcomeKind(str, Enum):
    OK = "ok"
    SYNTAX_ERROR = "syntax_error"
    SOLVER_LIMIT = "solver_limit"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"


@dataclass(frozen=True)
class QueryVerdict:
    query: str
    verdict: str  # true / false / cannot_be_proved


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    verdicts: list[QueryVerdict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: RawRun | None = None


# The verdict line comes two ways: ``RESULT <q> is true|false.`` and
# ``RESULT <q> cannot be proved.`` (no "is"). Lines starting ``RESULT (`` are
# the ``RESULT (but ...)`` follow-ups of an injective query, and are excluded.
_RESULT_RE = re.compile(
    r"^RESULT\s+(?!\()(.*?)\s+(?:is\s+(true|false)|(cannot be proved))\b",
    re.MULTILINE,
)


def parse_verdicts(stdout: str) -> list[QueryVerdict]:
    """Take each query's verdict from stdout in order of appearance, normalised
    to ``true`` / ``false`` / ``cannot_be_proved``."""
    out: list[QueryVerdict] = []
    for m in _RESULT_RE.finditer(stdout):
        verdict = m.group(2) if m.group(2) else "cannot_be_proved"
        out.append(QueryVerdict(query=m.group(1).strip(), verdict=verdict))
    return out


#: ProVerif's location line, split into the file it names and the rest.
_LOCATION = re.compile(r'^File "[^"]*", (line \d+.*)$')
#: A quoted path inside a message, reduced to its last component.
_QUOTED_PATH = re.compile(r'"[^"]*[\\/]([^\\/"]+)"')


def parse_diagnostics(stdout: str, stderr: str) -> tuple[list[str], list[str]]:
    """Pull error and warning lines out of stdout and stderr, in that order.

    ProVerif has no regular error prefix, and it puts the location on its own
    preceding line (``File "model.pv", line 41, character 69:``). The line and
    character part is prepended to the message it belongs to, since a bare
    "Syntax error." leaves a repair round guessing at which line to fix.

    The file name is dropped, and a path quoted inside a message is cut to its
    last component. ProVerif names the file by the path it was handed, which
    is a run directory or a temp directory on the host: the model never saw
    the file under that name, the tokens buy nothing, and the transcript would
    carry the machine's layout. The full output stays in the raw run and in
    the ``.txt`` log beside every solve.
    """
    errors: list[str] = []
    warnings: list[str] = []
    location: str | None = None
    for line in ((stderr or "") + "\n" + (stdout or "")).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (m := _LOCATION.match(stripped)):
            location = m.group(1)
            continue
        message = _QUOTED_PATH.sub(r'"\1"', stripped)
        if re.match(r"^error\b", stripped, re.IGNORECASE):
            errors.append(f"{location} {message}" if location else message)
        elif re.match(r"^warning\b", stripped, re.IGNORECASE):
            warnings.append(f"{location} {message}" if location else message)
        elif "syntax error" in stripped.lower():
            errors.append(f"{location} {message}" if location else message)
        location = None
    return errors, warnings


def classify(raw: RawRun) -> Outcome:
    """Turn the raw subprocess facts into one of the five kinds.

    Decided in order: timeout, memory limit, syntax/type error, abnormal exit,
    otherwise OK. An OK outcome with no verdicts is legal — that is what a
    typecheck with no queries looks like — so a caller that did issue queries
    decides for itself whether empty verdicts are an error.
    """
    if raw.timed_out:
        return Outcome(kind=OutcomeKind.TIMEOUT, raw=raw)
    if raw.memory_limited:
        return Outcome(kind=OutcomeKind.RESOURCE_LIMIT, raw=raw)

    errors, warnings = parse_diagnostics(raw.stdout, raw.stderr)
    verdicts = parse_verdicts(raw.stdout)
    if errors and not verdicts:
        # Error lines count as a syntax or type error only when no verdict came
        # out: a run that finished can still print lines beginning "Error..."
        # inside attack traces and query names.
        return Outcome(
            kind=OutcomeKind.SYNTAX_ERROR, errors=errors, warnings=warnings, raw=raw
        )

    combined = (raw.stdout + "\n" + raw.stderr).lower()
    if not verdicts and (raw.returncode != 0 or "internal error" in combined):
        # No verdict, plus an abnormal exit code or an internal error the solver
        # reported itself — which it can do while still exiting 0.
        return Outcome(kind=OutcomeKind.SOLVER_LIMIT,
                       errors=errors, warnings=warnings, raw=raw)

    return Outcome(
        kind=OutcomeKind.OK, verdicts=verdicts, errors=errors,
        warnings=warnings, raw=raw
    )
