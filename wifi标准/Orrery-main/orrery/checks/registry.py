"""Check registry: registration, plus running the checks a node declares.

Checks come in three classes (must / warn / read-through by the model). The
first two are deterministic functions in the per-node files under rules/; the
third is run by the reviewer and never enters this table.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class CheckResult:
    name: str
    level: Literal["must", "warn"]
    passed: bool
    findings: list[str] = field(default_factory=list)
    #: What happened, when passing does not mean nothing did — goals_typecheck
    #: judges only the syntax outcome, so a solver timeout there passes. Not a
    #: finding: there is nothing in it for the model to repair.
    note: str = ""


# A check takes the artifact — extra material comes in via a closure or partial.
CheckFn = Callable[[object], CheckResult]

_REGISTRY: dict[str, tuple[str, CheckFn]] = {}


def register(name: str, level: Literal["must", "warn"], fn: CheckFn) -> None:
    if name in _REGISTRY:
        raise RuntimeError(f"check {name!r} registered twice")
    _REGISTRY[name] = (level, fn)


async def run_checks(names: list[str], payload: object,
                     *, on: Callable[..., None] | None = None
                     ) -> list[CheckResult]:
    """Run the list a node declares and return one result per name, in order.

    An unregistered name raises, and so does a result whose name or level does
    not match what was mounted. A check may be sync or async, since some run a
    ProVerif subprocess. ``on(name, state, seconds, findings, note)`` reports
    each one, an awaitable check as "running" first.
    """
    import inspect
    import time

    out = []
    for n in names:
        if n not in _REGISTRY:
            raise RuntimeError(f"check {n!r} is not registered; registered: {sorted(_REGISTRY)}")
        level, fn = _REGISTRY[n]
        began = time.monotonic()
        r = fn(payload)
        if inspect.isawaitable(r):
            if on is not None:
                on(n, "running", None, [], "")
            r = await r
        if r.name != n or r.level != level:
            raise RuntimeError(f"check {n!r} returned a mismatched identity: {r}")
        if on is not None:
            on(n, "passed" if r.passed else "failed",
               time.monotonic() - began, list(r.findings), r.note)
        out.append(r)
    return out


def must_failures(results: list[CheckResult]) -> list[str]:
    """The findings of the must-level checks that did not pass, for the accept
    callback. warn-level results are recorded but never block."""
    out = []
    for r in results:
        if r.level == "must" and not r.passed:
            out.extend(r.findings or [f"{r.name} did not pass"])
    return out
