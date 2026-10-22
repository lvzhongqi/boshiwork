"""Tests for the stage index, which makes a re-entered run readable instead of
rewritten: it says which directory holds a step's current artifact and which
directories are behind it.
"""

import json

import pytest

from orrery.services.store import stages
from orrery.services.store.stages import Stage

CHAIN = ["load_document", "extract_principals", "extract_flow", "claims",
         "scenarios"]


def _run(tmp_path):
    (tmp_path / "run").mkdir()
    return tmp_path / "run"


def _alloc(run, st, ident, **kw):
    kw.setdefault("parent", "")
    kw.setdefault("kind", "seq")
    kw.setdefault("cause", "initial")
    s = stages.allocate(run, st, ident=ident, **kw)
    st.append(s)
    return s


def test_seq_numbers_are_execution_order_and_never_repeat(tmp_path):
    run, st = _run(tmp_path), []
    for ident in CHAIN:
        _alloc(run, st, ident)
    assert [s.dir for s in st] == [
        "01_load_document", "02_extract_principals", "03_extract_flow",
        "04_claims", "05_scenarios"]
    # going back does not reuse a number: the second principals is the sixth
    # thing this run did, and its directory name says so
    again = _alloc(run, st, "extract_principals", cause="gap", by="extract_flow")
    assert again.dir == "06_extract_principals"
    assert again.supersedes == "02_extract_principals"


def test_gen_numbers_are_per_identity_and_reproducible(tmp_path):
    """Parallel siblings share a generation whatever order they finish in, so
    a fan-out's directory names are the same on a second run of the same
    protocol."""
    run, st = _run(tmp_path), []
    _alloc(run, st, "08_scenarios", kind="seq")
    for label in ("lowe", "baseline"):          # deliberately not declared order
        _alloc(run, st, label, parent="01_08_scenarios", kind="gen")
    assert {s.name for s in st[1:]} == {"00_lowe", "00_baseline"}
    redo = _alloc(run, st, "baseline", parent="01_08_scenarios", kind="gen",
                  cause="fix", by="user")
    assert redo.name == "01_baseline"


def test_a_stale_input_cascades_down_the_chain(tmp_path):
    """Staleness is derived, never marked. principals is re-worked and flow
    follows it; every step after flow ran before the re-work, so none of them
    is current.
    """
    run, st = _run(tmp_path), []
    for ident in CHAIN:
        _alloc(run, st, ident)
    _alloc(run, st, "extract_principals", cause="gap", by="extract_flow")
    _alloc(run, st, "extract_flow", cause="gap", by="extract_flow")

    got = stages.live(st, "")
    assert got["load_document"].n == 1                  # untouched, still current
    assert got["extract_principals"].dir == "06_extract_principals"
    assert got["extract_flow"].dir == "07_extract_flow"
    assert "claims" not in got and "scenarios" not in got


def test_parallel_siblings_do_not_invalidate_one_another(tmp_path):
    run, st = _run(tmp_path), []
    _alloc(run, st, "scenarios")
    for label in ("baseline", "lowe"):
        _alloc(run, st, label, parent="01_scenarios", kind="gen")
    _alloc(run, st, "baseline", parent="01_scenarios", kind="gen", cause="fix",
           by="user")
    got = stages.live(st, "01_scenarios")
    assert got["baseline"].name == "01_baseline"
    assert got["lowe"].name == "00_lowe"        # a redone sibling costs it nothing


def test_live_dir_resolves_and_answers_none_for_stale(tmp_path):
    run, st = _run(tmp_path), []
    for ident in CHAIN:
        _alloc(run, st, ident)
    _alloc(run, st, "extract_principals", cause="gap", by="extract_flow")
    assert stages.live_dir(run, st, "", "extract_principals") \
        == run / "06_extract_principals"
    assert stages.live_dir(run, st, "", "claims") is None


def test_facts_carry_forward_to_the_next_attempt(tmp_path):
    """A fact is a message about the step's work, not about one attempt at it,
    so the next attempt reads it too."""
    run, st = _run(tmp_path), []
    first = _alloc(run, st, "extract_principals")
    (run / first.dir / "facts.jsonl").write_text('{"text": "add the nonce"}\n')
    second = _alloc(run, st, "extract_principals", cause="gap", by="extract_flow")
    assert (run / second.dir / "facts.jsonl").read_text() == '{"text": "add the nonce"}\n'


def test_an_unrecorded_directory_is_refused_not_absorbed(tmp_path):
    run, st = _run(tmp_path), []
    (run / "01_extract_principals").mkdir()
    with pytest.raises(FileExistsError, match="disagree"):
        stages.allocate(run, st, parent="", ident="extract_principals",
                        kind="seq", cause="initial")


def test_a_damaged_line_is_an_error(tmp_path):
    run = _run(tmp_path)
    stages.path(run).write_text('{"dir": "x"}\nnot json\n')
    with pytest.raises(RuntimeError, match="unreadable line in the stage index"):
        stages.load(run)


def test_only_the_half_line_a_kill_leaves_is_forgiven(tmp_path):
    """A kill between write and flush leaves an unterminated last line; that
    one is dropped, the way the next append cuts it. A terminated line that
    does not parse, or a bad middle line, is still an error: this file decides
    which directory is current, so a skipped record changes the answer."""
    run = _run(tmp_path)
    st: list = []
    s = _alloc(run, st, "extract_flow")
    with open(stages.path(run), "a", encoding="utf-8") as f:
        f.write('{"dir": "02_extract_fl')          # no newline: the kill signature
    assert [x.dir for x in stages.load(run)] == [s.dir]
    with open(stages.path(run), "a", encoding="utf-8") as f:
        f.write('\n')                              # now a whole line that is not a record
    with pytest.raises(RuntimeError, match="edited externally"):
        stages.load(run)


def test_recording_a_directory_that_is_not_there_is_refused(tmp_path):
    run = _run(tmp_path)
    with pytest.raises(ValueError, match="written together"):
        stages.record(run, Stage(dir="01_x", ident="x", parent="", kind="seq",
                                 n=1, cause="initial"))


def test_verify_reports_both_directions(tmp_path):
    run, st = _run(tmp_path), []
    _alloc(run, st, "extract_principals")
    (run / "02_extract_flow").mkdir()            # written by nobody
    problems = stages.verify(run, st)
    assert problems == ["02_extract_flow: on disk, not recorded in stages.jsonl"]


def test_round_trips_through_the_file(tmp_path):
    run, st = _run(tmp_path), []
    _alloc(run, st, "extract_principals")
    _alloc(run, st, "extract_flow")
    back = stages.load(run)
    assert [s.dir for s in back] == [s.dir for s in st]
    assert all(s.ts for s in back)
    assert json.loads(stages.path(run).read_text().splitlines()[0])["cause"] == "initial"


def test_the_chain_order_is_derived_from_the_first_pass(tmp_path):
    """Services may not import the node table, so the declared order is read
    back out of the index: the first pass through a chain is its declared
    order."""
    run, st = _run(tmp_path), []
    for ident in CHAIN:
        _alloc(run, st, ident)
    _alloc(run, st, "extract_principals", cause="gap", by="extract_flow")
    assert stages.chain(st, "") == CHAIN


def test_a_parent_holding_both_kinds_is_an_error(tmp_path):
    run, st = _run(tmp_path), []
    _alloc(run, st, "a")
    _alloc(run, st, "b", kind="gen")
    with pytest.raises(RuntimeError, match="cannot be read as both"):
        stages.live(st, "")


def test_a_skipped_step_keeps_its_place(tmp_path):
    """Re-entering below a step does not re-run it, so it records nothing, and
    its earlier execution stays live because nothing upstream moved."""
    run, st = _run(tmp_path), []
    for ident in CHAIN:
        _alloc(run, st, ident)
    _alloc(run, st, "claims", cause="rerun", by="user")     # re-entered at claims
    _alloc(run, st, "scenarios", cause="rerun", by="user")
    got = stages.live(st, "")
    assert got["extract_principals"].dir == "02_extract_principals"   # untouched
    assert got["claims"].dir == "06_claims"
    assert got["scenarios"].dir == "07_scenarios"


def test_a_re_work_deep_in_a_tree_ages_the_steps_after_it(tmp_path):
    """The cascade reaches through nesting levels rather than stopping at each
    one. A fix aimed at one apply point appends deep in the tree and leaves the
    enclosing step's own number alone, but that step's verdict has changed, so
    everything computed from it is stale.
    """
    run, st = _run(tmp_path), []
    _alloc(run, st, "scenarios")                       # 01_scenarios
    home = _alloc(run, st, "baseline", parent="01_scenarios", kind="gen")
    _alloc(run, st, "ltk_reveal_A", parent=f"{home.dir}/apply")
    _alloc(run, st, "aggregate")                       # 03_aggregate, after it

    assert set(stages.live(st, "")) == {"scenarios", "aggregate"}

    # now re-work that one apply point, and nothing else
    _alloc(run, st, "ltk_reveal_A", parent=f"{home.dir}/apply",
           cause="fix", by="user")
    got = stages.live(st, "")
    assert "scenarios" in got                          # it carried on: still current
    assert "aggregate" not in got                      # …but its input moved under it


def test_a_family_is_stale_once_its_scenario_apply_chain_is_reworked(tmp_path):
    """A goal family names the scenario's apply chain as its input. A point
    re-worked there after the family ran makes the family stale, so the
    scenario stage builds it again on the new model instead of handing back
    the model.pv it built on the old one. A family that names no input (an
    older index) keeps the plain highest-generation rule."""
    run = _run(tmp_path)
    st: list = []
    sc = _alloc(run, st, "baseline", parent="08_scenarios", kind="gen")
    _alloc(run, st, "k1", parent=f"{sc.dir}/apply")
    fam = _alloc(run, st, "Secrecy", parent=f"{sc.dir}/inject", kind="gen",
                 input=f"{sc.dir}/apply")
    plain = _alloc(run, st, "Authentication", parent=f"{sc.dir}/inject", kind="gen")
    assert stages.live(st, f"{sc.dir}/inject") == {"Secrecy": fam,
                                                   "Authentication": plain}
    _alloc(run, st, "k1", parent=f"{sc.dir}/apply", cause="fix")   # re-worked
    assert stages.live(st, f"{sc.dir}/inject") == {"Authentication": plain}
    fam2 = _alloc(run, st, "Secrecy", parent=f"{sc.dir}/inject", kind="gen",
                  input=f"{sc.dir}/apply")
    assert stages.live(st, f"{sc.dir}/inject")["Secrecy"] == fam2
