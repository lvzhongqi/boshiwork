"""Stowing the corpus's answers beside the runs they are compared against."""

import pytest

from orrery.api.truth import ORIGIN, stow_ground_truth


def _corpus(root, **files):
    """Build a corpus directory holding the relative files named."""
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def test_it_copies_the_corpus_layout_under_the_protocol(tmp_path):
    src = _corpus(tmp_path / "corpus" / "NSPK",
                  **{"claims/claims.json": "{}",
                     "source/main/NSPK.md": "# NSPK",
                     "formal/proverif/main.pv": "(* pv *)",
                     "results/results.json": '{"results": []}'})
    work = tmp_path / "wr"

    home = stow_ground_truth(work, "NSPK", src)

    # Beside the runs, not inside one: a run directory holds only what that
    # run wrote.
    assert home == work / "NSPK" / "_ground_truth"
    assert (home / "claims" / "claims.json").read_text() == "{}"
    assert (home / "source" / "main" / "NSPK.md").read_text() == "# NSPK"
    assert (home / "formal" / "proverif" / "main.pv").read_text() == "(* pv *)"
    assert (home / "results" / "results.json").read_text() == '{"results": []}'
    assert str(src) in (home / ORIGIN).read_text()


def test_a_run_with_no_corpus_stows_nothing(tmp_path):
    """Most protocols bring no expected answers; that is the ordinary case."""
    work = tmp_path / "wr"
    assert stow_ground_truth(work, "NSPK", None) is None
    assert not work.exists()


def test_what_the_corpus_does_not_carry_is_skipped(tmp_path):
    src = _corpus(tmp_path / "corpus" / "EDHOC",
                  **{"source/main/edhoc.md": "# EDHOC"})
    home = stow_ground_truth(tmp_path / "wr", "EDHOC-draft-08", src)
    assert (home / "source").is_dir()
    assert not (home / "results").exists()
    assert "source" in (home / ORIGIN).read_text()


def test_stowing_again_reflects_the_corpus_rather_than_merging(tmp_path):
    """Idempotent by re-copying: a file the corpus has since dropped must not
    survive in the copy."""
    src = _corpus(tmp_path / "corpus" / "NSPK",
                  **{"claims/claims.json": "{}",
                     "claims/old.json": "stale"})
    work = tmp_path / "wr"
    stow_ground_truth(work, "NSPK", src)
    (src / "claims" / "old.json").unlink()

    home = stow_ground_truth(work, "NSPK", src)
    assert (home / "claims" / "claims.json").is_file()
    assert not (home / "claims" / "old.json").exists()


def test_a_ground_truth_path_that_is_not_there_is_an_error(tmp_path):
    """A silent skip would be indistinguishable from a protocol that never
    had answers."""
    with pytest.raises(FileNotFoundError, match="is not a directory"):
        stow_ground_truth(tmp_path / "wr", "NSPK", tmp_path / "nope")
