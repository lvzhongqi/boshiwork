"""The builder family — the world vocabulary's leaves.

A world entry constrains the analysis as a whole: which principals exist, which
seats each may take, how sessions are laid out. build_world applies every world
assumption once, before any object-level point.

A leaf is a directory ``builders/<axis>/<subtype>/``: ``builder.py`` holds the
class, ``__init__.py`` re-exports it, ``rules.sys.md`` (with its ``_zh``
counterpart) is the prompt. The class declaration is the vocabulary entry.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from orrery.agent.compose import localized, render_file


class Builder:
    """The builder for one world subtype."""

    axis: str = ""
    subtype: str = ""
    #: the target field naming the object instance this entry is about, or None
    #: for an axis about the world as a whole. Axis-level: the registry rejects
    #: an axis whose subtypes disagree.
    instance_key: str | tuple[str, ...] | None | type(...) = ...
    #: True for the one subtype per axis that is the flow model's own shape.
    noop: bool = False
    #: position in the total build order; axis-level, checked for agreement.
    build_order: int = 0
    #: True for a subtype that only re-seats or re-counts what the input model
    #: already contains: its edit may change instances, table rows and
    #: replication, never the binder inventory. Build acceptance diffs the
    #: inventory for these builders and rejects a minted or dropped binding.
    preserves_inventory: bool = False
    params: dict[str, dict] = {}
    description: str = ""

    @property
    def id(self) -> str:
        return f"{self.axis}.{self.subtype}"

    @classmethod
    def _dir(cls) -> Path:
        return Path(inspect.getfile(cls)).parent

    def sys_prompt(self, lang: str = "en") -> str:
        """The builder's rules block. A noop subtype has none and raises."""
        if self.noop:
            raise ValueError(
                f"[builder {self.id}] is the flow state; it has no writing and "
                f"produces no build step")
        return render_file(self._dir() / localized("rules.sys.md", lang))


class NoopBuilder(Builder):
    """The flow model's own shape on this axis: nothing to build."""
    noop = True
