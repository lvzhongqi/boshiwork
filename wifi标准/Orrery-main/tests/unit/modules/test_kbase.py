"""Vocabulary shapes and the primitive library: the Vocabulary constructor
rejects malformed declarations loudly, the registry-built vocabularies carry
the expected invariants, and the primitive library validates on load."""

import pytest

from orrery.modules.kbase.assumptions.catalog import Vocabulary
from orrery.modules.kbase.primitives import catalog as prim
from orrery.modules.kbase.properties.catalog import (
    PropertyVocabulary, check_requires_refs,
)


def _entry(axis="a", subtype="s", **over):
    e = {"obj": "value", "axis": axis, "subtype": subtype,
         "instance_key": None,
         "structural": False, "stronger_than": (), "params": {},
         "description": "a state", "is_stub": False}
    e.update(over)
    return e


# ── Vocabulary: the rejection paths ─────────────────────────────────────────

def test_vocabulary_rejects_duplicate():
    with pytest.raises(ValueError, match="duplicate"):
        Vocabulary([_entry(), _entry()])


def test_vocabulary_rejects_dangling_edge():
    # A typo'd sibling name drops the edge from the closure with no error.
    with pytest.raises(ValueError, match="unknown subtype"):
        Vocabulary([_entry(subtype="strong", stronger_than=("weeak",)),
                    _entry(subtype="weak")])


def test_vocabulary_rejects_cycle():
    with pytest.raises(ValueError, match="cycle"):
        Vocabulary([_entry(subtype="x", stronger_than=("y",)),
                    _entry(subtype="y", stronger_than=("x",))])


def test_vocabulary_rejects_two_weakest():
    with pytest.raises(ValueError, match="exactly one weakest"):
        Vocabulary([_entry(subtype="x"), _entry(subtype="y")])


def test_vocabulary_rejects_wrong_declaration_order():
    # Declaration order is the expansion order, so weakest-first keeps one set
    # of claims producing the same scenario sequence every run.
    with pytest.raises(ValueError, match="weakest"):
        Vocabulary([_entry(subtype="strong", stronger_than=("weak",)),
                    _entry(subtype="weak")])


def test_vocabulary_rejects_undeclared_structural_and_bad_kind():
    with pytest.raises(ValueError, match="structural"):
        Vocabulary([_entry(structural=None)])
    with pytest.raises(ValueError, match="valid kind"):
        Vocabulary([_entry(params={"holder": {"kind": "person"}})])


def test_value_role_kind_is_gone_and_open_kinds_pass():
    """The class of value an assumption is about lives in the axis, never in a
    target param, so value_role is not a valid kind. Entity and value names are
    open names only the model text can confirm, so they pass the domain check."""
    with pytest.raises(ValueError, match="valid kind"):
        Vocabulary([_entry(params={"role": {"kind": "value_role"}})])
    v = Vocabulary([_entry(params={"of": {"kind": "value_name"}})])
    assert v.domain_error("a", "s", {"of": "whatever"}) is None
    assert v.domain_error("a", "s", None) is None       # a targetless assumption


def test_vocabulary_closure_and_compare():
    v = Vocabulary([_entry(subtype="w"),
                    _entry(subtype="m", stronger_than=("w",)),
                    _entry(subtype="s", stronger_than=("m",))])
    assert v.stronger_than("a", "s") == {"m", "w"}   # transitive, from direct edges
    assert v.compare("a", "s", "w") == 1
    assert v.compare("a", "w", "m") == -1
    assert v.dimension_values("a") == ["w", "m", "s"]


# ── instance_key: what "one answer per object" is keyed on ──────────────────

def test_instance_key_must_name_the_subtypes_own_params():
    """A key naming a field the subtype does not declare reads every target as
    naming no instance, so the uniqueness rule would key on nothing."""
    with pytest.raises(ValueError, match="instance_key names 'of'"):
        Vocabulary([_entry(instance_key="of",
                           params={"holder": {"kind": "entity"}})])


def test_instance_key_is_an_axis_level_property():
    """instance_key belongs to the axis, so two subtypes of one axis keying on
    different objects is refused at declaration time."""
    with pytest.raises(ValueError, match="instance_key is an axis-level"):
        Vocabulary([_entry(subtype="w", instance_key=None),
                    _entry(subtype="s", stronger_than=("w",),
                           instance_key="of",
                           params={"of": {"kind": "value_name"}})])


def test_instance_of_reads_the_object_never_the_whole_target():
    """A single field normalises to a one-tuple, a composite key to the tuple
    of its fields in declared order, and qualifier fields are ignored, so
    {holder: A, of: K} and {holder: S, of: K} name one object."""
    v = Vocabulary([_entry(instance_key="of",
                           params={"of": {"kind": "value_name"},
                                   "holder": {"kind": "entity"}})])
    assert v.instance_key("a") == ("of",)
    assert v.instance_of("a", {"holder": "A", "of": "K"}) == ("K",)
    assert v.instance_of("a", {"holder": "S", "of": "K"}) == ("K",)
    assert v.instance_of("a", {"holder": "A"}) is None      # names no instance

    pair = Vocabulary([_entry(instance_key=("from", "to"),
                              params={"from": {"kind": "entity"},
                                      "to": {"kind": "entity"}})])
    assert pair.instance_key("a") == ("from", "to")
    assert pair.instance_of("a", {"from": "B", "to": "A"}) == ("B", "A")
    # the direction is the object: the reverse seat is a different one
    assert pair.instance_of("a", {"from": "A", "to": "B"}) == ("A", "B")

    glob = Vocabulary([_entry(instance_key=None)])
    assert glob.instance_key("a") is None
    assert glob.instance_of("a", {"of": "K"}) is None       # a global axis


# ── the registry-built values carry the real vocabulary ─────────────────────

def test_realizer_vocab_invariants():
    from orrery.nodes.apply.realizers import REALIZERS, VOCAB
    # Five axes, each one object class crossed with one question; world
    # assumptions (roles, population, sessions) have their own vocabulary.
    assert VOCAB.axes() == ["data", "key_reuse", "channel", "admission",
                            "primitive"]
    assert VOCAB.obj_of("data") == "value"
    assert VOCAB.obj_of("key_reuse") == "secret_value"
    assert VOCAB.obj_of("channel") == "channel"
    assert VOCAB.obj_of("admission") == "identity_scope"
    assert VOCAB.obj_of("primitive") == "crypto_object"
    # data and key_reuse share an object and differ in the question:
    # possession of the value versus use of it as an oracle. Both can hold on
    # the same `of`, so they are two axes.
    assert VOCAB.instance_key("data") == VOCAB.instance_key("key_reuse") == ("of",)
    # one answer per identity recognition scope; consumers determine direction
    assert VOCAB.instance_key("admission") == ("scope",)
    assert VOCAB.instance_key("channel") == ("link",)
    assert VOCAB.instance_key("primitive") == ("family",)
    # structural = reshapes the main-process form; a plain leak does not
    assert VOCAB.is_structural("admission", "open")
    assert VOCAB.is_structural("data", "leaked_after_session")
    assert not VOCAB.is_structural("data", "disclosed")
    # the data ladder: none tops every granting rung, the premise tops none
    assert VOCAB.stronger_than("data", "none") == {
        "chosen", "disclosed", "leaked_after_session",
        "leaked_in_other_instances", "leaked_after_correct_session"}
    assert "none" in VOCAB.stronger_than("data", "assumed_secure")
    # every granting data rung names its value: `of` is required
    for sub in ("chosen", "disclosed", "leaked_after_session",
                "leaked_in_other_instances", "leaked_after_correct_session"):
        assert "of" in VOCAB.required_params("data", sub), sub
    assert "of" in VOCAB.required_params("key_reuse", "observed")
    # No stub left: every declared coordinate has a realizer behind it, so a
    # corpus may cite any of them.
    assert {(a, s) for a in VOCAB.axes() for s in VOCAB.dimension_values(a)
            if VOCAB.is_stub(a, s)} == set()
    # Only these two coordinates carry multiple writings; the choice among
    # them is made mechanically from value lifetime.
    forms = {k: sorted(c.writings) for k, c in REALIZERS.items() if c.writings}
    assert forms == {
        ("data", "chosen"): ["lifted_parameter", "replaced_new"],
        ("data", "disclosed"): ["branch_leak", "draw_leak"],
    }


def test_every_axis_has_exactly_one_flow_state():
    """An unmentioned axis has to mean one thing, so each axis holds exactly
    one noop subtype. This pins the map the resolver defaults through."""
    from orrery.nodes.apply.realizers import FLOW_STATE, VOCAB
    assert FLOW_STATE == {"data": "none", "key_reuse": "separated",
                          "channel": "public", "admission": "closed",
                          "primitive": "ideal"}
    assert set(FLOW_STATE) == set(VOCAB.axes())


def test_property_vocab_shapes():
    from orrery.nodes.inject.injectors import PROP_VOCAB
    assert "Secrecy" in PROP_VOCAB.types()
    assert PROP_VOCAB.subtypes_of("Secrecy")
    assert PROP_VOCAB.parties_shape("Secrecy") == "holders"
    # forward_secrecy is pinned to the granting data rungs: its premise is
    # that the long-term secret reaches the attacker at all.
    req = PROP_VOCAB.requires_assumption("Secrecy", "forward_secrecy")
    assert req["axis"] == "data"
    assert set(req["subtypes"]) == {"disclosed", "leaked_after_session",
                                    "leaked_after_correct_session"}
    # guessing resistance presupposes a small candidate space, which is the
    # primitive axis's broken rung rather than a data leak.
    weak = PROP_VOCAB.requires_assumption(
        "Secrecy", "weak_secret_guessing_resistance")
    assert weak["axis"] == "primitive"
    assert set(weak["subtypes"]) == {"broken"}


def test_property_vocab_rejections():
    def pentry(**over):
        e = {"gtype": "T", "subtype": "s", "parties": "holders",
             "realization": "correspondence", "description": "d",
             "requires_assumption": None, "is_stub": False}
        e.update(over)
        return e

    with pytest.raises(ValueError, match="parties"):
        PropertyVocabulary([pentry(parties="nobody")])
    with pytest.raises(ValueError, match="two different"):
        PropertyVocabulary([pentry(), pentry(subtype="t", parties="free")])
    with pytest.raises(ValueError, match="missing why"):
        PropertyVocabulary([pentry(requires_assumption={
            "axis": "ltk_reveal", "subtypes": ["lkr_from_start"]})])


def test_requires_refs_cross_check():
    from orrery.nodes.apply.realizers import VOCAB
    bad = PropertyVocabulary([{
        "gtype": "T", "subtype": "s", "parties": "holders",
        "realization": "correspondence", "description": "d",
        "requires_assumption": {"axis": "ltk_reveale",
                                "subtypes": ["lkr_from_start"], "why": "w"},
        "is_stub": False}])
    with pytest.raises(ValueError, match="unknown axis"):
        check_requires_refs(bad, VOCAB)


# ── primitives: the data-file library ───────────────────────────────────────

def test_primitives_render_layer_matches_v7():
    # spk sits beside pk: signature keys carry their own pair of types, so a
    # signing key used to decrypt fails the typecheck.
    render = [p.name for p in prim.iter_render_primitives()]
    assert render == ["aenc", "pk", "spk", "senc", "hash", "aeadEncrypt", "sign"]


def test_primitives_alias_normalization_and_decls():
    dh = prim.lookup_primitive("X25519")
    assert dh is not None and dh.name == "exp"
    assert any("equation" in d for d in dh.all_decls())     # commutativity
    assert prim.lookup_primitive("HMAC").name == "prf"
    assert prim.lookup_primitive("no_such_primitive") is None


def test_primitives_requires_and_globals():
    hkdf = prim.lookup_primitive("hkdf")
    assert "exp" in hkdf.requires            # reuses the G / exponent decls
    assert {"g", "aenc", "pk", "HKDF"} <= prim.library_global_names()


def test_abstract_nike_keeps_protocol_objects_typed_and_terminating():
    nike = prim.lookup_primitive("nike")
    assert nike is not None and nike.name == "nike_apply"
    assert {"nsk", "npk", "ntoken", "nshared"} <= set(nike.types)
    declarations = "\n".join(nike.all_decls())
    assert "nike_token(nsk, npk): ntoken" in declarations
    assert "nike_blinded_A(nsk, nsk, npk): nshared" in declarations
    assert "nike_blinded_B(nsk, ntoken): nshared" in declarations
    assert "set ignoreTypes = false." in nike.idiom


def test_primitives_idiom_only_on_lookup_layer():
    for p in prim.all_primitives():
        if p.delivery == prim.LOOKUP:
            assert p.idiom, f"{p.name} is a lookup-layer primitive but has no idiom"


def test_the_live_vocabulary_carries_no_world_concept():
    """World assumptions live in their own section of assumptions.json with
    their own vocabulary, so the object-level vocabulary carries no is_world
    and shares no axis name with it."""
    from orrery.nodes.world.builders import WORLD_VOCAB
    from orrery.nodes.apply.realizers import VOCAB
    assert not hasattr(VOCAB, "is_world")
    assert not set(WORLD_VOCAB.axes()) & set(VOCAB.axes())
