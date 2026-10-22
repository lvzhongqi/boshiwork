"""Step topology: a fix targets a step by its directory path, and this module
turns that path into an address the engine can re-enter at.

Four kinds of step are addressable — a node (one table row), a scenario, an
apply point (under a scenario or under build_world/build_root), and an inject
family. Anything deeper, a single cell for instance, resolves to an error
naming the step above it. Nothing here destroys anything: a re-work writes a
new directory and the earlier one stops being current, which
services/store/stages derives from the numbers.

Addresses are identities, not directories. The first segment takes either the
directory name (``04_extract_flow``, what list_artifacts shows) or the node
name (``extract_flow``, what the prompts and the table use), and a scenario or
apply point is named by its label rather than by whichever numbered directory
currently holds it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orrery.pipeline.table import index_of
from orrery.services.store.layout import RunLayout

_NUMBERED = re.compile(r"^\d+_")

_SHAPES = (
    "a node name (extract_flow), a scenario (08_scenarios/<label>), an "
    "apply point (08_scenarios/<label>/apply/<rid>, "
    "06_build_world/apply/<rid>, or "
    "07_build_root/apply/<rid>), or an inject family "
    "(08_scenarios/<label>/inject/<family>)")


@dataclass(frozen=True)
class StepRef:
    """One addressable step: where its current execution lives, which table
    node owns it, and the canonical identity a re-entry is aimed by."""

    rel: str       #: run-relative dir of the current execution, "" if not run
    node: str      #: the owning table node, the engine's re-entry point
    kind: str      #: "node" | "scenario" | "apply_point" | "inject_family"
    #: Identity path: numbers stripped, first segment as the node name.
    #: ``RunEnv.plan`` compares against this identity, never a directory.
    path: str = ""

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.rel.split("/"))

    @property
    def deep(self) -> bool:
        """Is the target below its node? A re-work aimed inside a step's own
        tree continues that step: the node keeps the directory it is working
        in, and the level actually aimed at is the one that appends."""
        return self.kind != "node"


def _ident(segment: str) -> str:
    """A path segment as an identity: the leading number records when the
    directory ran and is not part of the step's name."""
    return _NUMBERED.sub("", segment)


def resolve(layout: RunLayout, table: list, step: str) -> StepRef:
    """Path → StepRef, or a ValueError whose message lists the valid shapes.

    What the plan points at has to exist and still be current: a fix aimed at a
    step already superseded from upstream would file its message against a
    directory nothing reads.
    """
    parts = [p for p in str(step).strip().strip("/").split("/") if p]
    if not parts:
        raise ValueError(f"empty step path; give {_SHAPES}")
    head = _ident(parts[0])
    names = [n.name for n in table]
    if head not in names:
        raise ValueError(
            f"step {step!r} does not start with a pipeline step: {parts[0]!r} "
            f"is none of {names}")
    home = layout.find_node_dir(head)
    if len(parts) == 1:
        # A bare node may legitimately have no directory yet, since a fix can
        # aim at a step the run stopped before reaching. The empty rel says so,
        # and execute gives it a directory.
        return StepRef(rel=layout.rel(home) if home else "", node=head,
                       kind="node", path=head)
    if home is None:
        raise ValueError(
            f"step {step!r} names {head!r}, which has no current work in this "
            f"run: it either never ran, or what it left was computed from "
            f"something that has since been re-worked")

    if head == "scenarios":
        label = _ident(parts[1])
        d = layout.find_scenario_dir(label)
        if d is None:
            known = sorted({s.ident for s in layout.stages
                            if s.parent == layout.rel(home)})
            raise ValueError(
                f"step {step!r} names scenario {label!r}, which this run "
                f"does not have; its scenarios are "
                f"{known or '(the scenario stage has produced none yet)'}")
        if len(parts) == 2:
            return StepRef(rel=layout.rel(d), node=head, kind="scenario",
                           path=f"scenarios/{label}")
        if len(parts) == 4 and parts[2] == "apply":
            p = layout.find_apply_point_dir(d, _ident(parts[3]))
            if p is None:
                raise ValueError(
                    f"step {step!r} names no current apply point; "
                    f"list_artifacts shows what {layout.rel(d)}/apply holds")
            return StepRef(rel=layout.rel(p), node=head, kind="apply_point",
                           path=f"scenarios/{label}/apply/{_ident(parts[3])}")
        if len(parts) == 4 and parts[2] == "inject":
            f = layout.find_inject_family_dir(label, _ident(parts[3]))
            if f is None:
                raise ValueError(
                    f"step {step!r} names no current goal family; "
                    f"list_artifacts shows what {layout.rel(d)}/inject holds")
            return StepRef(rel=layout.rel(f), node=head, kind="inject_family",
                           path=f"scenarios/{label}/inject/{_ident(parts[3])}")

    if head in ("build_world", "build_root") and len(parts) == 3 \
            and parts[1] == "apply":
        p = layout.find_apply_point_dir(home, _ident(parts[2]))
        if p is None:
            raise ValueError(
                f"step {step!r} names no current apply point; list_artifacts "
                f"shows what {layout.rel(home)}/apply holds")
        return StepRef(rel=layout.rel(p), node=head, kind="apply_point",
                       path=f"{head}/apply/{_ident(parts[2])}")

    raise ValueError(
        f"step {step!r} is not a re-workable step; the addressable steps are "
        f"{_SHAPES}. A cell re-works with the step above it")


def superseded_by(layout: RunLayout, table: list, ref: StepRef) -> list[str]:
    """The step directories that stop being current when ``ref`` is re-worked,
    as run-relative paths.

    Read off the node index: every node from the target's own onward has its
    current directory replaced when the re-entry runs. The target's own
    directory is included when the fix is aimed below its node, since there the
    node carries on and the deeper step gets a new directory. Reported only,
    so the price of a fix can be shown before it is paid.
    """
    out = []
    if ref.deep and ref.rel:
        out.append(ref.rel)
    for n in table[index_of(table, ref.node):]:
        d = layout.find_node_dir(n.name)
        if d is not None and layout.rel(d) not in out:
            out.append(layout.rel(d))
    return out
