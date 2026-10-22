"""Every step draws itself with one word, and no two steps draw the same one.

The pipeline strip fits twelve cells across one row, too narrow for the full
node names. The verb is the droppable part: four steps begin extract_ and two
begin build_, so the object is what tells them apart.

The short name is the node's own declaration rather than a console-side table,
and these two tests are what make declaring it mandatory.
"""

from __future__ import annotations

from orrery.pipeline.table import build_table


def test_every_step_declares_a_short_name() -> None:
    """A node added without one draws as an empty cell and nothing else catches
    it: the strip has no name to fall back on, so the gap reads as a rendering
    bug rather than a missing declaration."""
    missing = [n.name for n in build_table() if not n.short]
    assert not missing, (
        "these steps declare no `short` and would draw as blank cells in the "
        f"pipeline strip: {missing}. Add one to the node class — the object "
        "the step acts on, not the verb.")


def test_short_names_tell_the_steps_apart() -> None:
    """Two steps sharing a short name make the strip show the same word twice,
    leaving a reader unable to tell which cell is which step. Naming by verb is
    how that happens: four steps would draw as `extract`."""
    table = build_table()
    seen: dict[str, str] = {}
    clashes = []
    for n in table:
        if n.short in seen:
            clashes.append(f"{seen[n.short]} and {n.name} both draw as {n.short!r}")
        seen[n.short] = n.name
    assert not clashes, "; ".join(clashes)
