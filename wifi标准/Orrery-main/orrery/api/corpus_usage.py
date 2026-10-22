"""Measures which subtypes the corpus declares, by scanning its assumptions.json.

A leaf is one analysable target — a protocol directory or one of its
``subprotocols/<mechanism>`` — and is the unit counted, grouped by protocol
directory for display. Absent roots are skipped and unparsable files land in
``unreadable``, so a half-broken corpus does not read as a sparse one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Leaf:
    """One analysable target and the vocabulary coordinates it declares."""

    protocol: str                      # corpus-relative protocol directory
    mechanism: str | None              # subprotocols/<name>, when there is one
    coords: tuple[str, ...]            # "axis.subtype", sorted

    @property
    def label(self) -> str:
        return self.mechanism or self.protocol.rsplit("/", 1)[-1]


@dataclass
class CorpusUsage:
    """The scan's result: the leaves found, the files that could not be read,
    and the roots actually walked."""

    leaves: list[Leaf] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    roots: tuple[str, ...] = ()

    def by_protocol(self) -> dict[str, list[Leaf]]:
        out: dict[str, list[Leaf]] = {}
        for leaf in self.leaves:
            out.setdefault(leaf.protocol, []).append(leaf)
        for group in out.values():
            group.sort(key=lambda x: x.label)
        return out

    def coords_of(self, protocol: str) -> list[str]:
        """The union of the coordinates every leaf under this protocol
        directory declares, which is what a folded row stands for."""
        seen: set[str] = set()
        for leaf in self.leaves:
            if leaf.protocol == protocol:
                seen.update(leaf.coords)
        return sorted(seen)

    def count_of(self, coord: str) -> int:
        """How many leaves declare this coordinate. Zero means no protocol in
        the corpus sits on that rung."""
        return sum(1 for leaf in self.leaves if coord in leaf.coords)


def _coords_of_file(data: dict) -> list[str]:
    """The (axis, subtype) coordinates one assumptions.json declares.

    All three sections count, and a variable dimension contributes every
    subtype it offers, since the run can sit at any of them.
    """
    out: set[str] = set()
    for section in ("world", "fixed", "variable"):
        for entry in data.get(section, []) or []:
            axis = entry.get("axis")
            if not axis:
                continue
            subs = entry.get("subtypes") or (
                [entry["subtype"]] if entry.get("subtype") else [])
            for sub in subs:
                out.add(f"{axis}.{sub}")
    return sorted(out)


def scan_usage(roots) -> CorpusUsage:
    """Walk the given corpus roots and measure what they declare.

    Roots that are not directories are skipped. One protocol per
    corpus-relative path, first root wins, so the same protocol copied under a
    second root is counted once.
    """
    usage = CorpusUsage()
    seen: set[tuple[str, str | None]] = set()
    kept: list[str] = []
    for root in roots:
        if root is None:
            continue
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        kept.append(str(root))
        for path in sorted(root.rglob("claims/assumptions.json")):
            rel_parts = path.relative_to(root).parts
            # A leading underscore marks a path outside the tree's own
            # subject, such as the stowed answers a work directory keeps.
            if any(seg.startswith("_") for seg in rel_parts):
                continue
            home, mechanism = path.parent.parent, None
            if home.parent.name == "subprotocols":
                home, mechanism = home.parent.parent, home.name
            protocol = str(home.relative_to(root))
            if (protocol, mechanism) in seen:
                continue
            seen.add((protocol, mechanism))
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                usage.unreadable.append((str(path), f"{type(exc).__name__}: {exc}"))
                continue
            if not isinstance(data, dict):
                usage.unreadable.append(
                    (str(path), "the file is not a JSON object"))
                continue
            usage.leaves.append(Leaf(
                protocol=protocol,
                mechanism=mechanism,
                coords=tuple(_coords_of_file(data))))
    usage.roots = tuple(kept)
    usage.leaves.sort(key=lambda x: (x.protocol, x.label))
    return usage
