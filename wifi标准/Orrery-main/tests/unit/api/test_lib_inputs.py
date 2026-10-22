"""Tests for corpus_inputs: which artifacts a run is handed from the corpus,
and where the run stops."""
import json

import pytest

from orrery.api.corpus_inputs import (
    check_inputs, resolve_lib_inputs, run_protocol_async, supplied_of, to_node_for,
)


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "claims").mkdir()
    (tmp_path / "flow").mkdir()
    for name in ("assumptions", "properties", "claims"):
        (tmp_path / "claims" / f"{name}.json").write_text("{}")
    (tmp_path / "flow" / "flow.pv").write_text("(* *)")
    (tmp_path / "flow" / "principals.json").write_text(json.dumps({}))
    return tmp_path


def _given(r):
    return {k for k, v in r.items() if v is not None and k != "ground_truth"}


def _resolve(corpus, **kw):
    """Every switch off unless the case turns it on."""
    off = {"lib_principals": False, "lib_flow": False, "lib_claims": False}
    return _given(resolve_lib_inputs(corpus, **{**off, **kw}))


def test_nothing_switched_on_is_the_full_pipeline(corpus):
    assert _resolve(corpus) == set()


def test_principals_alone_is_what_measures_the_flow_extraction(corpus):
    """The model is written on the corpus's semantic principals and values;
    nothing else about it is given."""
    assert _resolve(corpus, lib_principals=True) == {"principals"}


def test_the_three_claim_files_are_one_switch(corpus):
    """There is no supplying one of them: claims.json references entries of the
    other two."""
    assert _resolve(corpus, lib_claims=True) == {"assumptions", "properties",
                                                 "claims"}


def test_the_question_is_not_coupled_to_the_model(corpus):
    """The question and the model are separate switches. The default pairs the
    corpus's question with an extracted flow model, so the verdict score
    measures the flow extraction with the question held fixed."""
    assert _resolve(corpus, lib_claims=True) == {"assumptions", "properties",
                                                 "claims"}
    assert _resolve(corpus, lib_principals=True, lib_flow=True) == {
        "principals", "flow"}


def test_an_explicit_path_wins_over_a_switch(corpus, tmp_path):
    mine = tmp_path / "mine.json"
    r = resolve_lib_inputs(corpus, claims=mine, lib_claims=True)
    assert r["claims"] == mine


def test_the_only_subprotocol_is_the_default(corpus):
    sub = corpus / "subprotocols" / "AKA"
    sub.mkdir(parents=True)
    (corpus / "claims").rename(sub / "claims")
    (corpus / "flow").rename(sub / "flow")
    assert _resolve(corpus, lib_claims=True) == {
        "assumptions", "properties", "claims"}


def test_a_switch_whose_file_the_corpus_lacks_is_an_error(corpus):
    """It raises rather than falling back to extraction: the fallback runs a
    different pipeline than the reader asked for, and the measurement then
    means something else."""
    (corpus / "flow" / "flow.pv").unlink()
    with pytest.raises(FileNotFoundError, match="flow.pv"):
        resolve_lib_inputs(corpus, lib_principals=True, lib_flow=True)


# ── what the choices may not be ─────────────────────────────────────────────
def test_a_mother_model_needs_its_principals():
    """The semantic value/dependency contract must accompany its mother model."""
    with pytest.raises(ValueError, match="lib_flow needs inputs.lib_principals"):
        check_inputs("scenarios", lib_flow=True, lib_principals=False)


def test_a_run_with_nothing_to_do_is_refused():
    """Stopping after an artifact that was handed in walks the table writing
    back the files it was given and reports success — which looks like a
    result."""
    with pytest.raises(ValueError, match="nothing to do"):
        check_inputs("principals", lib_principals=True)
    with pytest.raises(ValueError, match="nothing to do"):
        check_inputs("claims", lib_principals=True, lib_flow=True,
                     lib_claims=True)
    # scenarios always leaves build_world onward to do.
    check_inputs("scenarios", lib_principals=True, lib_flow=True,
                 lib_claims=True)


def test_where_a_run_ends():
    assert to_node_for("principals") == "extract_principals"
    assert to_node_for("claims") == "extract_claims"
    assert to_node_for("scenarios") is None


def test_what_a_finished_run_was_handed_is_read_off_its_record():
    """The page draws this; the mapping stays here so there is one copy."""
    assert supplied_of({}) == {"lib": [], "end": "scenarios"}
    assert supplied_of({"principals": "p", "assumptions": "a",
                        "properties": "r", "claims": "c"}) == {
        "lib": ["lib_principals", "lib_claims"], "end": "scenarios"}
    assert supplied_of({"to_node": "extract_flow"})["end"] == "flow"


def test_an_incomplete_claims_trio_is_not_the_claims_switch():
    assert supplied_of({"assumptions": "a", "properties": "r"})["lib"] == []


@pytest.mark.parametrize("old", ["start_point", "lib_model", "lib_question"])
def test_the_chain_shape_is_refused(old):
    from orrery.pipeline.config import MissingConfigError, load_config
    with pytest.raises(MissingConfigError, match="lib_principals"):
        load_config({"inputs": {old: "document"}}, require=False)


def test_async_batch_adapter_uses_current_input_bands(monkeypatch, tmp_path):
    """The external adapter reads the current inputs.lib_* switches and
    end_point, and translates end_point into to_node."""
    seen = {}

    class Result:
        status = "ok"
        metrics = {}

    async def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return Result()

    monkeypatch.setattr("orrery.api.corpus_inputs.run", fake_run)
    cfg = {"inputs": {
        "lib_principals": False,
        "lib_flow": False,
        "lib_claims": False,
        "end_point": "principals",
    }}
    result = __import__("asyncio").run(run_protocol_async(
        "NSPK", tmp_path, config=cfg))
    assert result["status"] == "ok"
    assert seen["to_node"] == "extract_principals"
