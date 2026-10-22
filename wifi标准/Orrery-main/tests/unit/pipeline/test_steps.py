"""steps.resolve's canonical identity path, the address the console retries by.

The page sends back whichever row was clicked, directory numbers and all
(scenarios/00_baseline/inject/01_Secrecy), and stripping the numbers is the
resolver's job. RunEnv.plan only ever compares against identity
(scenarios/baseline/inject/Secrecy), so the round trip is the contract here: a
path that merely looks right re-runs the wrong thing, or nothing.
"""

from pathlib import Path

import pytest

from orrery.nodes.base import RunEnv
from orrery.pipeline import steps
from orrery.pipeline.table import build_table
from orrery.services.store.atomic import write_text
from orrery.services.store.layout import RunLayout

CHAIN = ("load_document", "tag_sections", "extract_principals", "extract_flow",
         "claims", "build_world", "build_root", "scenarios")


def _run(tmp_path):
    """Builds a run directory in the order a real run fills it. A step whose
    newest execution predates work under an earlier step reads as stale, so
    filling build_root in after opening the scenario stage hides the stage."""
    lay = RunLayout(tmp_path / "wr", "NSPK", "r1")
    lay.run_dir.mkdir(parents=True)
    for name in CHAIN[:-1]:
        lay.open_node(name)
    root = lay.node_dir("build_root")
    write_text(lay.open_apply_point(root, "fixed_A") / "applied.pv", "process 0")
    lay.open_node("scenarios")
    home = lay.open_scenario("baseline")
    write_text(lay.open_apply_point(home, "leaked") / "applied.pv", "process 0")
    lay.open_inject_family("baseline", "Secrecy")
    lay.open_scenario("lowe")
    return lay


def _plan(aim: str, step: str) -> str:
    """What the engine would do with `step` when the re-entry aims at `aim`.
    The unit is pinned at "exists and already answered", the only case where
    the aim alone decides between open, carry and skip."""
    env = RunEnv(protocol_dir=".", layout=None, config={})
    env.aim = aim
    return env.plan(step, Path("/somewhere"), True)


@pytest.mark.parametrize("typed,ident", [
    ("scenarios", "scenarios"),
    ("08_scenarios", "scenarios"),
    ("scenarios/baseline", "scenarios/baseline"),
    ("scenarios/00_baseline", "scenarios/baseline"),
    ("08_scenarios/00_baseline/apply/01_leaked",
     "scenarios/baseline/apply/leaked"),
    ("scenarios/baseline/inject/00_Secrecy",
     "scenarios/baseline/inject/Secrecy"),
    ("build_root/apply/01_fixed_A", "build_root/apply/fixed_A"),
])
def test_a_typed_address_comes_back_canonical(tmp_path, typed, ident):
    lay = _run(tmp_path)
    assert steps.resolve(lay, build_table(), typed).path == ident


def test_the_path_is_an_aim_the_engine_acts_on(tmp_path):
    """The round trip, and the reason the field exists: a directory path
    resolves and reads plausibly yet matches nothing, so plan would skip the
    very step the person asked for."""
    lay = _run(tmp_path)
    ref = steps.resolve(lay, build_table(),
                        "08_scenarios/00_baseline/inject/00_Secrecy")
    assert _plan(ref.path, "scenarios/baseline/inject/Secrecy") == "open"
    # and it is aimed, not broadcast: the sibling family and the other scenario
    # keep what they have
    assert _plan(ref.path, "scenarios/baseline/inject/Authentication") == "skip"
    assert _plan(ref.path, "scenarios/lowe/apply/leaked") == "skip"
    # the levels above carry on in the directories they are in, which is what
    # makes a deep aim cheap
    assert _plan(ref.path, "scenarios") == "carry"
    assert _plan(ref.path, "scenarios/baseline") == "carry"
    # the directory path is not interchangeable with the identity path
    assert _plan(ref.rel, "scenarios/baseline/inject/Secrecy") == "skip"


def test_a_node_is_the_shortest_form_of_the_same_address(tmp_path):
    """A node name is the same address space at its shortest. The console's
    node-level retry is this one, and it redoes everything under the node."""
    lay = _run(tmp_path)
    ref = steps.resolve(lay, build_table(), "scenarios")
    assert ref.path == "scenarios" and ref.kind == "node"
    assert _plan(ref.path, "scenarios/baseline/inject/Secrecy") == "open"
    assert _plan(ref.path, "scenarios/lowe/apply/leaked") == "open"
