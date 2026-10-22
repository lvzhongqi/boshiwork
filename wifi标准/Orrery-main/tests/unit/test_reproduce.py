"""Unit tests for ``experiments.reproduce``: folding scores, ground-truth
resolution, and the LIB scan that decides which units the paper reports."""

from types import SimpleNamespace

import pytest

from experiments import reproduce


def _score(**overrides):
    values = {
        "agg_state": "scored",
        "props_total": 2,
        "props_match": 2,
        "cases_match": 3,
        "princ_state": "scored",
        "princ_total": 1,
        "princ_match": 1,
        "flow_state": "scored",
        "syn": True,
        "reach": True,
        "answered": 4,
        "cells_matched": 3,
        "n_timeout": 0,
        "sessions": 1,
        "repairs": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fold_uses_corpus_denominators_and_means_repeats():
    unit = SimpleNamespace(n_props=2, n_princ_items=1)
    result = reproduce.fold(
        [_score(), _score(props_match=1, cases_match=2, syn=False, repairs=0)],
        "mean",
        unit,
    )

    assert result["props_match"] == 1.5
    assert result["cases_match"] == 2.5
    assert result["princ_total"] == 1
    assert result["syn"] == 1
    assert result["reach"] == 2
    assert result["gate_runs"] == 2
    assert result["rep_rounds"] == 1


def test_oneshot_ground_truth_rejects_conflicting_subprotocol():
    with pytest.raises(ValueError, match="conflicts"):
        reproduce._oneshot_ground_truth({
            "protocol_dir": "/corpus/proto/subprotocols/a",
            "subprotocol": "b",
        })


def test_scan_lib_keeps_paper_scope_metadata_when_documents_are_withheld(tmp_path):
    unit = tmp_path / "academic" / "NSPK"
    (unit / "claims").mkdir(parents=True)
    (unit / "results").mkdir()
    (unit / "flow").mkdir()
    (unit / "claims" / "properties.json").write_text(
        '{"properties": [{"id": "p"}]}', encoding="utf-8")
    (unit / "claims" / "claims.json").write_text(
        '{"scenarios": [{"id": "s"}], "claims": [{"scenarios": ["s"]}]}',
        encoding="utf-8")
    (unit / "claims" / "assumptions.json").write_text(
        '{"world": [], "fixed": [], "variable": []}', encoding="utf-8")
    (unit / "results" / "results.json").write_text(
        '{"results": [{"verdict": "true"}]}', encoding="utf-8")
    (unit / "flow" / "principals.json").write_text(
        '{"values": []}', encoding="utf-8")

    units, families, doc_only, unmapped, excluded = reproduce.scan_lib(tmp_path)

    assert [item.rel for item in units] == ["academic/NSPK"]
    assert len(families["academic/NSPK"]) == 1
    assert doc_only == sorted(reproduce.PAPER_DOCUMENT_ONLY)
    assert unmapped == []
    assert excluded == []
