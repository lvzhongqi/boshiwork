"""The writing machinery around apply: semantic single-session realizers,
lifetime-selected forms, and the registry's declaration checks. The
declaration checks run at import, so a broken leaf never reaches a run."""

from pathlib import Path

import pytest

from orrery.nodes.apply.realizers import REALIZERS, _decl, realizer_for
from orrery.nodes.apply.realizers.base import Realizer


# _decl reads a leaf's coordinate off its directory, so a stand-in leaf
# declares where it lives rather than being written to disk.

def _leaf(*, at=None, **over):
    body = {"axis": "data", "obj": "value", "subtype": "disclosed",
            "structural": False, "stronger_than": (), "description": "d",
            "params": {"of": {"kind": "value_name"}},
            "instance_key": "of"}
    body.update(over)
    home = Path("/nowhere") / (at or f"{body['axis']}/{body['subtype']}")
    body["_dir"] = classmethod(lambda cls, home=home: home)
    return type("Leaf", (Realizer,), body)


def test_a_leaf_that_does_not_declare_its_instance_key_is_refused():
    """None is a real answer (a global axis), so the undeclared state is the
    ``...`` sentinel. The registry refuses a leaf left at it, rather than
    keying "one answer per object" on nothing."""
    with pytest.raises(RuntimeError, match="instance_key is not declared"):
        _decl(_leaf(instance_key=...))


def test_a_leaf_that_does_not_declare_structural_is_refused():
    with pytest.raises(RuntimeError, match="structural is not declared"):
        _decl(_leaf(structural=None))


def test_a_leaf_filed_under_the_wrong_directory_is_refused():
    with pytest.raises(RuntimeError, match="lives at"):
        _decl(_leaf(at="channel/public"))


def test_an_instance_key_field_must_be_one_of_the_leafs_own_params():
    """_decl carries the declaration through; Vocabulary catches a key naming
    a field the leaf never declares. A miss reads as "this target names no
    instance", and the uniqueness rule then passes everything."""
    from orrery.modules.kbase.assumptions.catalog import Vocabulary

    with pytest.raises(ValueError, match="instance_key names 'link'"):
        Vocabulary([_decl(_leaf(instance_key="link"))])


def test_a_composite_instance_key_declares_every_coordinate():
    """Axes whose objects genuinely have two coordinates retain tuple keys."""
    from orrery.modules.kbase.assumptions.catalog import Vocabulary

    both = {"from": {"kind": "entity"}, "to": {"kind": "entity"}}
    v = Vocabulary([_decl(_leaf(axis="pair_axis", obj="pair_object",
                                subtype="open", instance_key=("from", "to"),
                                params=both))])
    assert v.instance_key("pair_axis") == ("from", "to")
    with pytest.raises(ValueError, match="instance_key names 'to'"):
        Vocabulary([_decl(_leaf(axis="pair_axis", obj="pair_object",
                                subtype="open", instance_key=("from", "to"),
                                params={"from": {"kind": "entity"}}))])


def test_apply_submission_has_no_model_side_give_up():
    """The model always attempts the semantic encoding; acceptance and its
    repair loop own concrete syntax and model-checking failures."""
    from types import SimpleNamespace

    from orrery.nodes.apply.node import (
        build_batch_encode_prompt, build_encode_prompt,
    )

    realizer = realizer_for("data", "assumed_secure")
    prompt = build_encode_prompt(
        "free K: key [private].\nprocess 0\n",
        realizer, {"of": "K"})
    assert prompt.submit.give_up is None
    batch = build_batch_encode_prompt(
        "free K: key [private].\nprocess 0\n", realizer,
        [SimpleNamespace(ref_id="secure_k", target={"of": "K"})])
    assert batch.submit.give_up is None


def test_sys_prompt_form_contract():
    admission = realizer_for("admission", "open")
    assert admission.writings == ()
    assert "whole model" in admission.sys_prompt()
    with pytest.raises(ValueError, match="single-writing"):
        admission.sys_prompt("unused_form")
    # Lifetime-selected subtypes retain the multi-writing contract.
    lifetime = realizer_for("data", "disclosed")
    with pytest.raises(KeyError, match="needs a writing form"):
        lifetime.sys_prompt()
    for single in (realizer_for("key_reuse", "observed"),
                   realizer_for("data", "assumed_secure")):
        with pytest.raises(ValueError, match="single-writing"):
            single.sys_prompt("unused_form")
        assert single.sys_prompt()               # its own rules.sys.md renders


def test_admission_is_one_global_semantic_session():
    """Admission is one capability. The sighted model decides whether it
    needs registry, certificate, consumer-gate, or combined edits."""
    r = realizer_for("admission", "open")
    en = r.sys_prompt()
    zh = r.sys_prompt(lang="zh")
    assert r.writings == ()
    assert all(x in en for x in ("producers", "credentials", "consumers"))
    assert all(x in zh for x in ("生产者", "凭据", "消费者"))
    assert "whole model" in en and "完整模型" in zh


def test_the_lifetime_decides_the_disclosed_writing():
    """data.disclosed has one meaning and two lifetime-dependent encodings.
    The three restricted leak states are separate subtypes, not writings."""
    d = realizer_for("data", "disclosed")
    assert d.form_from_lifetime("long_lived") == "branch_leak"
    assert d.form_from_lifetime("per_session") == "draw_leak"
    with pytest.raises(NotImplementedError, match="does not select"):
        realizer_for("key_reuse", "observed").form_from_lifetime("long_lived")


def test_every_multi_writing_subtype_is_lifetime_selected():
    """Only value lifetime selects a writing. Global semantic judgement stays
    in one sighted realizer prompt."""
    for key, cls in sorted(REALIZERS.items()):
        if not cls.writings:
            assert not cls.writings_by_lifetime, key
            continue
        assert cls.form_from_lifetime is Realizer.form_from_lifetime, key
        mapping = cls.writings_by_lifetime
        assert set(mapping) <= {"long_lived", "per_session"}, key
        assert set(mapping.values()) == set(cls.writings), key


def test_a_mapping_gap_reads_as_backend_coverage_not_semantics():
    """The base selectors' error names the gap as ProVerif-backend coverage:
    the combination is semantically well-defined, no writing realises it
    yet."""
    with pytest.raises(KeyError, match="coverage gap"):
        realizer_for("data", "disclosed").form_from_lifetime("forever")


def test_check_writing_coverage_runs_before_any_session():
    """The pre-session sweep resolves only mechanically decidable forms, so
    lifetime coverage holes surface before any model call while semantic
    admission stays one sighted session."""
    from orrery.modules.libschema.model import Point
    from orrery.nodes.apply.realizers import check_writing_coverage

    pv = ("(* @orrery-idiom identity.authenticated_key_binding/v1 scope=peer_auth *)\n"
          "table keys(host, pkey).\n"
          "free KAB: bitstring [private].\n"
          "let roleA(A: host) =\n  new NA: bitstring;\n  0.\n")
    check_writing_coverage(
        [Point(axis="data", subtype="disclosed", target={"of": "KAB"}, ref_id="d1"),
         Point(axis="data", subtype="leaked_in_other_instances",
               target={"of": "NA"}, ref_id="w1"),
         Point(axis="admission", subtype="open",
               target={"scope": "peer_auth"}, ref_id="adm"),
         Point(axis="data", subtype="assumed_secure", target={"of": "KAB"},
               ref_id="ax")],
        pv)                                                    # no raise
    # Admission has no syntax precondition: its session reads the whole model.
    check_writing_coverage(
        [Point(axis="admission", subtype="open",
               target={"scope": "peer_auth"}, ref_id="adm")],
        "process 0")
    with pytest.raises(KeyError, match="unknown point"):
        check_writing_coverage(
            [Point(axis="ltk_reveal", subtype="lkr_from_start", target=None)],
            pv)
    with pytest.raises(ValueError, match="names no 'of'"):
        check_writing_coverage(
            [Point(axis="data", subtype="disclosed", target=None)], pv)
    with pytest.raises(ValueError, match="does not occur"):
        check_writing_coverage(
            [Point(axis="data", subtype="disclosed", target={"of": "GHOST"})],
            pv)
    # Lifetime only selects syntax for multi-writing realizers such as
    # disclosed/chosen; it is not a semantic admission check.
    check_writing_coverage(
        [Point(axis="data", subtype="leaked_after_session",
               target={"of": "NA"})], pv)
    check_writing_coverage(
        [Point(axis="data", subtype="leaked_in_other_instances",
               target={"of": "KAB"})], pv)


def test_no_writing_prompt_names_a_form():
    """The encoding round holds one writing, and the form name is project
    jargon a general model reads nothing out of. Every writing's rules and
    every scope finding say "this writing"."""
    for key, cls in sorted(REALIZERS.items()):
        r = cls()
        if not r.writings:
            continue
        for form in sorted(r.writings):
            text = r.sys_prompt(form)
            for name in sorted(r.writings):
                assert name not in text, f"{key}:{form} names the form {name!r}"


def test_disclosed_verify_applied_pins_the_leak_to_the_target():
    """The added public out must carry exactly a declared target term. Leaking
    a value the target derives from (the exponent behind a public key) is a
    stronger world and comes back as a repair problem."""
    d = realizer_for("data", "disclosed")
    base = "process\n  ( !roleA(skA) | out(c, G_I) )\n"
    ok_pv = base.replace("out(c, G_I) )", "out(c, G_I) | out(c, G_R) )")
    assert d.verify_applied(base, ok_pv, [{"of": "G_R"}]) == []
    bad_pv = base.replace("out(c, G_I) )", "out(c, G_I) | out(c, I) )")
    problems = d.verify_applied(base, bad_pv, [{"of": "G_I"}])
    assert problems and "out(c, I)" in problems[0]
    # a compound target term is matched whole, and pre-existing outs never count
    ok2 = base.replace("out(c, G_I) )", "out(c, G_I) | out(c, J(pi)) )")
    assert d.verify_applied(base, ok2, [{"of": "J(pi)"}]) == []
