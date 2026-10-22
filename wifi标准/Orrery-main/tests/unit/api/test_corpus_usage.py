"""Tests for scan_usage, which measures what each corpus assumptions.json
declares. The contract is a faithful reading: every section counted, every
target found, nothing silently dropped.
"""

import json

from orrery.api.corpus_usage import scan_usage


def _write(root, rel, doc):
    home = root / rel / "claims"
    home.mkdir(parents=True)
    home.joinpath("assumptions.json").write_text(
        json.dumps({"vocab_version": "2.2.0", **doc}), encoding="utf-8")


def test_a_plain_protocol_is_one_leaf(tmp_path):
    _write(tmp_path, "academic/NSPK", {
        "world": [], "fixed": [],
        "variable": [{"id": "v", "axis": "data", "target": {"of": "K"},
                      "subtypes": ["none", "disclosed"]}]})
    u = scan_usage([tmp_path])
    assert len(u.leaves) == 1
    leaf = u.leaves[0]
    assert (leaf.protocol, leaf.mechanism) == ("academic/NSPK", None)
    assert leaf.coords == ("data.disclosed", "data.none")


def test_mechanisms_are_leaves_under_one_protocol_directory(tmp_path):
    """``subprotocols/<name>`` is what a run analyses, so it is what gets
    counted; the directory above it is what the panel lists."""
    for sub, of in (("mech-1", "K1"), ("mech-2", "K2")):
        _write(tmp_path, f"ISO/9798-2/subprotocols/{sub}", {
            "world": [], "fixed": [
                {"id": "f", "axis": "data", "target": {"of": of},
                 "subtype": "disclosed"}],
            "variable": []})
    u = scan_usage([tmp_path])
    assert len(u.leaves) == 2
    assert set(u.by_protocol()) == {"ISO/9798-2"}
    assert [x.mechanism for x in u.leaves] == ["mech-1", "mech-2"]
    assert u.coords_of("ISO/9798-2") == ["data.disclosed"]
    assert u.count_of("data.disclosed") == 2


def test_all_three_sections_count(tmp_path):
    """A world entry is as much "what this was modelled with" as an
    assumption, and a variable dimension exercises every rung it offers."""
    _write(tmp_path, "rfc/X", {
        "world": [{"id": "w", "axis": "population", "subtype": "unbounded"}],
        "fixed": [{"id": "f", "axis": "primitive", "target": {"family": "dh"},
                   "subtype": "broken"}],
        "variable": [{"id": "v", "axis": "data", "target": {"of": "K"},
                      "subtypes": ["none", "disclosed", "leaked_after_session"]}]})
    u = scan_usage([tmp_path])
    assert u.leaves[0].coords == (
        "data.disclosed", "data.leaked_after_session", "data.none",
        "population.unbounded", "primitive.broken")


def test_an_unused_rung_reads_zero(tmp_path):
    """Zero separates a rung nothing uses from one nobody wrote down."""
    _write(tmp_path, "academic/NSPK", {"world": [], "fixed": [], "variable": []})
    u = scan_usage([tmp_path])
    assert u.count_of("data.disclosed") == 0
    assert u.leaves[0].coords == ()


def test_a_stowed_copy_is_not_a_second_protocol(tmp_path):
    """A leading underscore marks a directory outside the tree's own subject:
    a work root offered as a corpus keeps a copy of the answers under every
    run it has done."""
    _write(tmp_path, "academic/NSPK", {"world": [], "fixed": [], "variable": []})
    _write(tmp_path, "_history/academic/NSPK", {
        "world": [], "fixed": [], "variable": []})
    u = scan_usage([tmp_path])
    assert [x.protocol for x in u.leaves] == ["academic/NSPK"]


def test_an_unreadable_file_is_collected_not_skipped(tmp_path):
    """A corpus half of which failed to parse must not read as one that
    declares little: the panel says how many it could not read."""
    _write(tmp_path, "academic/NSPK", {"world": [], "fixed": [], "variable": []})
    bad = tmp_path / "academic/Broken/claims"
    bad.mkdir(parents=True)
    bad.joinpath("assumptions.json").write_text("{not json", encoding="utf-8")
    u = scan_usage([tmp_path])
    assert len(u.leaves) == 1
    assert len(u.unreadable) == 1
    assert "academic/Broken" in u.unreadable[0][0]


def test_a_copy_of_a_protocol_is_not_a_second_protocol(tmp_path):
    """Two roots may hold a copy of one protocol at the same relative path.
    Counted twice they inflate every count they touch, and a single-file
    protocol with two copies looks like a directory of two sub-protocols.
    First root wins.
    """
    lib, second = tmp_path / "lib", tmp_path / "second"
    _write(lib, "academic/Denning-Sacco", {
        "world": [], "fixed": [], "variable": [
            {"id": "v", "axis": "data", "target": {"of": "K"},
             "subtypes": ["none", "disclosed"]}]})
    _write(second, "academic/Denning-Sacco", {
        "world": [], "fixed": [], "variable": [
            {"id": "v", "axis": "channel", "target": {"link": ["A", "B"]},
             "subtypes": ["public", "secure"]}]})
    u = scan_usage([lib, second])
    assert len(u.leaves) == 1
    assert u.count_of("data.disclosed") == 1        # the library's copy
    assert u.count_of("channel.secure") == 0        # not the second root's
    assert len(u.by_protocol()["academic/Denning-Sacco"]) == 1


def test_a_missing_root_is_passed_over(tmp_path):
    """The corpus is an optional dependency: a configured root that is simply
    not there is the ordinary state of a checkout without one."""
    u = scan_usage([tmp_path / "nope", None])
    assert u.leaves == [] and u.roots == ()
