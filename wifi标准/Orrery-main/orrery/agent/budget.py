"""The count budget for one agent task.

``None`` means no ceiling on that count. A node loop runs unattended and must
end by construction; the expert answers a person who can stop it, so it leaves
the counts unset. There is no token or wall-clock budget either way.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopBudget:
    # Ordinary model calls; repair rounds draw on the same ceiling. When the
    # last ordinary call ends in framework feedback, runner may make one
    # terminal-only finalization call so the model can answer it.
    max_rounds: int | None = 12
    max_tool_calls: int | None = 40
    max_repairs: int = 6             # repair rounds after a failed check

    def __post_init__(self) -> None:
        given = [v for v in (self.max_rounds, self.max_tool_calls,
                             self.max_repairs) if v is not None]
        if min(given) < 1:
            raise ValueError(f"every budget that is set must be >= 1: {self}")
