"""The injector family: one class per goal subtype, structurally symmetric with
realizers/base, with the calling logic in nodes/inject/node.py.

One call covers one batch and a batch produces exactly one ``.pv``. What may
share that file is decided by ``perturbs_model`` rather than by subtype, and two
different goal types are never batched together — their rules contaminate each
other in ways no current check catches.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from orrery.agent.compose import localized, render_file


class Injector:
    """The injector for one goal subtype. The class fields are its vocabulary
    entry: ``parties`` (the shape libschema validates instance files against)
    and ``realization`` (the strategy key the engine dispatches on) come from
    the type's base class, the rest from the leaf.
    """

    gtype: str = ""
    subtype: str = ""
    parties: str = ""
    realization: str = ""
    description: str = ""
    # The assumption this subtype must be paired with, as {axis, subtypes, why},
    # or None. The claims gate rejects a claim whose world lacks it, and user 2's
    # traversal pins that axis.
    requires_assumption: dict | None = None
    # Declared vocabulary with no injection layer behind it. Using it is an
    # explicit error, never a silent skip.
    unimplemented: bool = False
    # Injecting this subtype changes the model itself, not just the queries and
    # the names they need, so it gets a batch — and a .pv — to itself: its
    # perturbation would answer its neighbours' questions for them.
    perturbs_model: bool = False
    # Stronger still: not even a second goal of the same subtype can share the
    # model, because an equivalence game yields one unnamed solver verdict for
    # the whole biprocess.
    one_goal_per_file: bool = False

    @property
    def id(self) -> str:
        return f"{self.gtype}.{self.subtype}"

    @classmethod
    def _dir(cls) -> Path:
        """The leaf's own directory — the coordinate the registry reads the
        type and subtype off."""
        return Path(inspect.getfile(cls)).parent

    @classmethod
    def rules_dir(cls) -> Path:
        """Where this injector's ``rules.sys.md`` lives — the leaf, unless a
        type overrides this to share one file across its subtypes."""
        return cls._dir()

    def sys_prompt(self, lang: str = "en") -> str:
        """Render this injector's rules block. ``lang="zh"`` reads the ``_zh``
        counterpart instead; a missing file raises ``FileNotFoundError``."""
        return render_file(self.rules_dir() / localized("rules.sys.md", lang))
