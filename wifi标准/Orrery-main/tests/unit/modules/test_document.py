"""Smoke test of the document capability: build a document set and exercise all
five façades. The fixture protocol (one document, empty reference annotation)
and a tmp_path bundle (main plus refs, sub-protocols, reference annotations)
cover the two extremes."""

import asyncio
from pathlib import Path

import pytest

from orrery.modules.document import DocumentLoaderService, ProtocolSource
from orrery.modules.document.corpus import (
    flow_text, inline_analysis_corpus, inline_corpus,
    inline_principals_corpus,
)
from orrery.modules.document.references import section_references
from orrery.modules.document.search import grep
from orrery.modules.document.sections import read_section, toc
from tests.fixtures import TOY_PROTOCOL


def _load(root: Path, **kw):
    src = ProtocolSource.from_directory(root, **kw)
    return asyncio.run(DocumentLoaderService().load(src))


def test_fixture_toc_read_grep():
    ds = _load(TOY_PROTOCOL)
    t = toc(ds)
    assert t and "1" in t.split()[0]
    first_no = ds.get_sections()[0].number
    assert read_section(ds, first_no).text
    # "key" is in the fixture; the old assertion held for any hits at all,
    # precedence having turned it into `... or hits`, and never noticed that
    # the word it grepped for is not in the document
    hits = grep(ds, "key")
    assert hits.startswith("[§")
    assert "no matches" in grep(ds, "nonce")
    with pytest.raises(RuntimeError, match="not found"):
        read_section(ds, "999.999")


def test_markdown_annex_sections_are_addressable(tmp_path):
    (tmp_path / "source" / "main").mkdir(parents=True)
    (tmp_path / "source" / "main" / "spec.md").write_text(
        "# Example specification\n\n"
        "## 1 Main procedure\n\nbody\n\n"
        "## Annex A (informative): State handling\n\nannex intro\n\n"
        "## A.1 State representation\n\nstate body\n\n"
        "### A.1.1 Freshness relation\n\nfreshness body\n\n"
        "## Annex C: Optional profile\n\nprofile intro\n\n"
        "## C.1 Profile state\n\nprofile state body\n"
    )

    ds = _load(tmp_path)
    contents = toc(ds)
    assert "A  Annex A (informative): State handling" in contents
    assert "A.1  State representation" in contents
    assert "A.1.1  Freshness relation" in contents
    assert "C  Annex C: Optional profile" in contents
    assert read_section(ds, "A.1.1").text.endswith("freshness body")
    assert read_section(ds, "C.1").text.endswith("profile state body")


def test_empty_annotation_is_resolved_no_refs():
    ds = _load(TOY_PROTOCOL)
    first_no = ds.get_sections()[0].number
    refs = section_references(ds, first_no)
    # The fixture ships references: {} — parsed and empty, which is not the
    # same answer as unresolved.
    assert refs.resolved is True and refs.references == []


_REF_DOC = (
    "# 1 Key Derivation\n\nthe function this protocol borrows\n\n"
    "# 2 Encoding\n\nthe wire format it borrows\n"
)
_REF_SCOPE = (
    "schema_version: 4\n"
    "references:\n"
    '  "2":\n'
    "    references:\n"
    "      - target_doc: kdf\n"
    '        target_section: "1"\n'
    "        ref_kind: section\n"
    "        mode: append\n"
    '        inline_hint: "the key derivation the flow depends on"\n'
)


def _bundle_with_refs(tmp_path):
    """A main document plus a reference document, with a non-empty reference
    annotation and a sub-protocol split."""
    _sub_bundle(tmp_path, _SUB_SCOPE)
    (tmp_path / "source" / "refs").mkdir(parents=True)
    (tmp_path / "source" / "refs" / "kdf.md").write_text(_REF_DOC)
    (tmp_path / "annotations" / "references.yaml").write_text(_REF_SCOPE)
    return tmp_path


def test_docset_with_refs_and_subprotocols(tmp_path):
    ds = _load(_bundle_with_refs(tmp_path), target_name="a")
    assert len(ds.doc_ids()) > 1                       # main and refs both came in
    assert ds.get_subprotocols()                       # the sub-protocol split applied
    # The reference annotation is non-empty: some section has an outgoing ref.
    annotated = [
        s.number for s in ds.main().sections.walk()
        if s.level > 0 and section_references(ds, s.number).references
    ]
    assert annotated, "the reference annotation should hit at least one section"
    # A reference document reads by section through read_section's doc_id branch.
    ref_doc = next(d for d in ds.doc_ids() if d != ds.main_doc_id)
    ref_secs = [s for s in ds.get(ref_doc).sections.walk() if s.level > 0]
    assert ref_secs, "the reference document should have parsed into sections"
    assert read_section(ds, ref_secs[0].number, doc_id=ref_doc).text

    # Every accessible document contributes a contents map to the prompt; the
    # reference bodies stay out-of-line.
    corpus = inline_corpus(ds, max_chars=1)
    assert "[contents — reference document kdf]" in corpus
    assert "1  Key Derivation" in corpus
    assert "2  Encoding" in corpus
    assert "the function this protocol borrows" not in corpus


def test_flow_reference_block_is_opt_in_and_scoped(tmp_path):
    root = _bundle_with_refs(tmp_path)
    (root / "annotations" / "tags.yaml").write_text(
        "schema_version: 4\n"
        "tags:\n"
        '  "2":\n'
        "    tags: [flow]\n"
    )
    ds = _load(root, target_name="a")

    common = inline_corpus(ds, max_chars=10_000)
    flow = inline_corpus(ds, max_chars=10_000, get_flow=True)

    assert "[resolved flow reference sections]" not in common
    assert "the function this protocol borrows" not in common
    assert "[resolved flow reference sections]" in flow
    assert "the function this protocol borrows" in flow
    assert "secret-token-B" not in flow


def test_analysis_corpus_keeps_small_documents_byte_identical(tmp_path):
    root = _bundle_with_refs(tmp_path)
    ds = _load(root, target_name="a")
    assert inline_analysis_corpus(ds, 100_000) == inline_corpus(ds, 100_000)


def test_large_principals_corpus_includes_entities_and_flow(tmp_path):
    (tmp_path / "source" / "main").mkdir(parents=True)
    (tmp_path / "source" / "main" / "spec.md").write_text(
        "# 1 Roles\n\nENTITY_BODY_TOKEN\n\n"
        "# 2 Exchange\n\nFLOW_BODY_TOKEN\n\n"
        "# 3 Security\n\nSECURITY_BODY_TOKEN\n\n"
        "# 4 Mixed role and exchange\n\nMIXED_BODY_TOKEN\n"
    )
    (tmp_path / "annotations").mkdir()
    (tmp_path / "annotations" / "tags.yaml").write_text(
        "schema_version: 4\n"
        "tags:\n"
        "  '1':\n    tags: [entities]\n"
        "  '2':\n    tags: [flow]\n"
        "  '3':\n    tags: [security]\n"
        "  '4':\n    tags: [entities, flow]\n"
    )
    text = inline_principals_corpus(_load(tmp_path), max_chars=1)
    assert "entity/flow sections only (1, 2, 4)" in text
    assert "ENTITY_BODY_TOKEN" in text
    assert "FLOW_BODY_TOKEN" in text
    assert "MIXED_BODY_TOKEN" in text
    assert "SECURITY_BODY_TOKEN" not in text
    assert text.count("MIXED_BODY_TOKEN") == 1


def test_large_analysis_corpus_includes_mixed_flow_analysis_tags(tmp_path):
    (tmp_path / "source" / "main").mkdir(parents=True)
    (tmp_path / "source" / "main" / "spec.md").write_text(
        "# 1 Mechanics\n\nFLOW_BODY_TOKEN\n\n"
        "# 2 Assumptions\n\nASSUMPTION_BODY_TOKEN\n\n"
        "# 3 Security Goals\n\nSECURITY_BODY_TOKEN\n\n"
        "# 4 Mixed mechanics and goal\n\nMIXED_FLOW_TOKEN\n"
    )
    (tmp_path / "annotations").mkdir()
    (tmp_path / "annotations" / "tags.yaml").write_text(
        "schema_version: 4\n"
        "tags:\n"
        "  '1':\n    tags: [flow]\n"
        "  '2':\n    tags: [assumption]\n"
        "  '3':\n    tags: [security]\n"
        "  '4':\n    tags: [flow, security]\n"
    )
    text = inline_analysis_corpus(_load(tmp_path), max_chars=1)
    assert "assumption/security sections only (2, 3, 4)" in text
    assert "mixed-tag sections included" in text
    assert "ASSUMPTION_BODY_TOKEN" in text
    assert "SECURITY_BODY_TOKEN" in text
    assert "FLOW_BODY_TOKEN" not in text
    assert "MIXED_FLOW_TOKEN" in text
    assert text.count("MIXED_FLOW_TOKEN") == 1


def test_large_analysis_corpus_requires_analysis_tags(tmp_path):
    (tmp_path / "source" / "main").mkdir(parents=True)
    (tmp_path / "source" / "main" / "spec.md").write_text(
        "# 1 Mechanics\n\nFLOW_BODY_TOKEN\n"
    )
    with pytest.raises(RuntimeError, match="no sections tagged assumption or security"):
        inline_analysis_corpus(_load(tmp_path), max_chars=1)


_SUB_DOC = (
    "# 1 Shared Intro\n\ncommon ground\n\n"
    "# 2 Flow A\n\nalpha-flow secret-token-A\n\n"
    "## 2.1 Msg A1\n\nalpha msg\n\n"
    "# 3 Flow B\n\nbeta-flow secret-token-B\n\n"
    "## 3.1 Msg B1\n\nbeta msg\n"
)
_SUB_SCOPE = (
    "schema_version: 4\n"
    "subprotocols:\n"
    '  "2":\n    sub: [a]\n'
    '  "3":\n    sub: [b]\n'
)


def _sub_bundle(tmp_path, scope_yaml, subs=("a", "b")):
    (tmp_path / "source" / "main").mkdir(parents=True)
    (tmp_path / "source" / "main" / "toy.md").write_text(_SUB_DOC)
    (tmp_path / "annotations").mkdir()
    (tmp_path / "annotations" / "subprotocols.yaml").write_text(scope_yaml)
    for s in subs:
        (tmp_path / "subprotocols" / s).mkdir(parents=True)
    return tmp_path


def test_sub_pruning_scopes_all_views(tmp_path):
    ds = _load(_sub_bundle(tmp_path, _SUB_SCOPE), target_name="a")
    t = toc(ds)
    # Contents: scope note first, own and shared sections present, other
    # sub-protocols' titles physically absent.
    assert "sub-protocol" in t and "Flow A" in t and "Shared Intro" in t
    assert "Flow B" not in t and "Msg B1" not in t
    # Text: own and shared sections read; another sub-protocol's section raises
    # its own error rather than "does not exist".
    assert read_section(ds, "2.1").text
    assert read_section(ds, "1").text
    with pytest.raises(RuntimeError, match="sub-protocol"):
        read_section(ds, "3")
    with pytest.raises(RuntimeError, match="sub-protocol"):
        read_section(ds, "3.1")            # cutting follows the whole subtree
    with pytest.raises(RuntimeError, match="not found"):
        read_section(ds, "99")
    # Search: another sub-protocol's text cannot be hit at all.
    assert "no matches" in grep(ds, "secret-token-B")
    assert "secret-token-A" in grep(ds, "secret-token-A")


def test_a_single_subprotocol_directory_is_the_default(tmp_path):
    ds = _load(_sub_bundle(tmp_path, _SUB_SCOPE, subs=("a",)))
    assert ds.active_sub == "a"
    assert "Flow A" in toc(ds)
    assert "Flow B" not in toc(ds)


def test_sub_pruning_guard_undeclared_target(tmp_path):
    # An ownership map that declares nothing for the target sub-protocol fails
    # loudly, which is the guard against a multi-sub bundle with no map at all.
    root = _sub_bundle(tmp_path, _SUB_SCOPE, subs=("a", "b", "c"))
    with pytest.raises(RuntimeError, match="declares no section"):
        _load(root, target_name="c")


def test_sub_pruning_reentry_is_error(tmp_path):
    # A descendant re-entering scope means the ownership map is wrong; that is
    # an explicit error rather than a ghost section left behind.
    scope = _SUB_SCOPE + '  "3.1":\n    sub: [a]\n'
    root = _sub_bundle(tmp_path, scope)
    with pytest.raises(RuntimeError, match="contradicts itself"):
        _load(root, target_name="a")


def test_dependency_section_owned_by_both_subprotocols_is_readable(tmp_path):
    """A differential variant reuses another variant's section by assigning the
    subtree to both sub-protocols. The section then shows up in the scoped tree
    and read_section follows the self-reference, while unrelated siblings stay
    isolated."""
    scope = (
        "schema_version: 4\n"
        "subprotocols:\n"
        '  "2":\n    sub: [a, derived]\n'
        '  "3":\n    sub: [b]\n'
    )
    root = _sub_bundle(tmp_path, scope, subs=("a", "b", "derived"))
    (root / "annotations" / "references.yaml").write_text(
        "schema_version: 4\nreferences:\n"
        '  "1":\n    references:\n'
        "      - target_doc: self\n"
        '        target_section: "2"\n'
        "        ref_kind: self_section\n"
        "        mode: append\n"
    )

    ds = _load(root, target_name="derived")
    assert "alpha-flow" in read_section(ds, "2").text
    assert "alpha msg" in read_section(ds, "2.1").text
    with pytest.raises(RuntimeError, match="sub-protocol"):
        read_section(ds, "3")


def test_one_sub_cannot_see_another(tmp_path):
    ds = _load(_sub_bundle(tmp_path, _SUB_SCOPE), target_name="b")
    nums = {s.number for s in ds.get_sections()}
    assert {"1", "3", "3.1"} <= nums          # own flow plus the shared section
    assert not any(n == "2" or n.startswith("2.") for n in nums)
    with pytest.raises(RuntimeError, match="a"):
        read_section(ds, "2.1")               # the error names the owning sub
    assert "[scope]" in toc(ds)


def test_a_shared_section_may_point_at_every_variant(tmp_path):
    """A shared section naming every variant is the ordinary shape of a
    multi-method document, so whichever method a run models, some pointer leads
    out of its scope. The out-of-scope pointer is skipped rather than followed
    or raised on: another method's text is a different protocol, not background
    this run is missing."""
    root = _sub_bundle(tmp_path, _SUB_SCOPE)
    (root / "annotations" / "references.yaml").write_text(
        "schema_version: 4\nreferences:\n"
        '  "1":\n    references:\n'
        "      - target_doc: self\n        target_section: \"2\"\n"
        "        ref_kind: self_section\n        mode: append\n"
        "      - target_doc: self\n        target_section: \"3\"\n"
        "        ref_kind: self_section\n        mode: append\n")
    for sub, mine, theirs in (("a", "secret-token-A", "secret-token-B"),
                              ("b", "secret-token-B", "secret-token-A")):
        text = inline_corpus(_load(root, target_name=sub),
                             max_chars=10_000, get_flow=True)
        assert mine in text, sub
        assert theirs not in text, sub


def test_unannotated_docset_reports_unresolved(tmp_path):
    # No annotations at all: resolved=False says unresolved, which is a
    # different answer from an annotation carrying no references.
    (tmp_path / "source" / "main").mkdir(parents=True)
    (tmp_path / "source" / "main" / "toy.md").write_text(
        "# 1 Intro\n\nhello\n\n# 2 Flow\n\nworld\n"
    )
    ds = _load(tmp_path)
    refs = section_references(ds, ds.get_sections()[0].number)
    assert refs.resolved is False and refs.references == []


def test_flow_text_selects_the_tagged_sections():
    # The independent review reads the document's own flow sections, so a model
    # is reconciled against the document, not against an artifact from it.
    ds = _load(TOY_PROTOCOL)
    text, source = flow_text(ds)
    assert source == "flow_sections"
    assert "Protocol Description" in text          # §4, tagged flow
    assert "Assumptions" not in text               # §5, not tagged


def test_flow_text_falls_back_to_the_whole_document_and_says_so(tmp_path):
    # With no flow tag anywhere the review falls back to the whole document,
    # which is weaker, so the caller is told which material it got.
    (tmp_path / "source" / "main").mkdir(parents=True)
    (tmp_path / "source" / "main" / "P.md").write_text(
        "# 1 Intro\nbody one\n\n# 2 Steps\nA -> B: m\n", encoding="utf-8")
    ds = _load(tmp_path)
    text, source = flow_text(ds)
    assert source == "whole_document"
    assert "body one" in text and "A -> B: m" in text
