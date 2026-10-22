"""Scenario checks after apply: a ProVerif typecheck of the model as written.

Applying an assumption may touch the whole model, so there is no fixed shape to
compare against, and reachability may legitimately fail after attacker_supplied.
payload: {"pv", "runner", "pv_log" (call it with a purpose to get a log stem)}.
"""

from __future__ import annotations

import re

from orrery.checks.registry import CheckResult, register
from orrery.infra.proverif.outcome import OutcomeKind, classify


async def _typecheck(payload) -> CheckResult:
    # Checked verbatim: goals are injected downstream, so the text that
    # typechecks is the text on disk.
    raw = await payload["runner"].run(
        payload["pv"], log_to=payload["pv_log"]("typecheck"))
    out = classify(raw)
    # Only the syntax outcome is judged, the way goals_typecheck judges it: a
    # timeout or a resource limit is the solve behind the typecheck being cut
    # off, not a rejected file, and telling the model to "check every
    # declaration" over one would send it rewriting a model that was fine.
    ok = out.kind is not OutcomeKind.SYNTAX_ERROR
    errs = [] if ok else (out.errors or [
        f"ProVerif rejected the file and reported no line-level error "
        f"(outcome: {out.kind.value}); the failure is structural rather than "
        f"local -- check that every declaration the bodies use is present and "
        f"that the file ends with a complete main process"])
    note = "" if out.kind is OutcomeKind.OK else (
        f"typechecked; the solve behind it ended in {out.kind.value}, which "
        f"is not a failure to typecheck")
    return CheckResult("scenario_typecheck", "must", ok, errs, note)


register("scenario_typecheck", "must", _typecheck)

SCENARIO_CHECK_NAMES = ["scenario_typecheck"]
