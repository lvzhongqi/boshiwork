"""Terms as a trace prints them: enough structure to tell what an attacker
assembled from what it computed, and nothing model-specific."""

import pytest

from orrery.modules.attacks.terms import (
    TermError, computed, display, names, parse, slots, split_top,
)


def test_a_rewrap_is_one_computation_and_the_rest_is_assembly():
    # Lowe's attack on NSPK, step 4: the attacker decrypts A's message with its
    # own key and re-encrypts the content for B.
    recipe = parse("aenc((1-proj-2-tuple(adec(~M_14,~M_1)),~M_9),~M_3)")
    value = parse("aenc((I_A_3,A_3),pk(SKB_2))")
    assert [(str(r), str(v)) for r, v in computed(recipe, value)] == [
        ("1-proj-2-tuple(adec(~M_14,~M_1))", "I_A_3")]
    assert slots(recipe) == ["~M_14", "~M_1", "~M_9", "~M_3"]


def test_slots_and_made_up_names_are_not_computations():
    assert computed(parse("~M_3"), parse("pk(SKB_2)")) == []
    assert computed(parse("(a,~M_9)"), parse("(a,A_3)")) == []
    assert names(parse("(a_1,senc((~M_4,a_2),~M_3))")) == {"a_1", "a_2"}


def test_printing_round_trips_and_grouping_is_not_a_tuple():
    for text in ("f()", "(x,y)", "aenc((I_A_3,A_3),pk(SKB_2))", "~M"):
        assert str(parse(text)) == text
    assert str(parse("(x)")) == "x"
    assert str(parse(" wdec_nonce( ~M_20 ,\n x ) ")) == "wdec_nonce(~M_20,x)"


@pytest.mark.parametrize("bad", ["", "f(", "(a,b", "a)", "f(a;b)"])
def test_a_term_it_cannot_read_is_an_error(bad):
    with pytest.raises(TermError):
        parse(bad)


def test_display_drops_instance_suffixes_but_keeps_what_it_must():
    assert display("aenc((I_A_3,A_3),pk(SKB_2))") == "aenc((I_A,A),pk(SKB))"
    # slots and projections are not names
    assert display("1-proj-2-tuple(adec(~M_14,~M_1))") == \
        "1-proj-2-tuple(adec(~M_14,~M_1))"
    assert display("witness_secrecy_i_a_I_A_B") == "witness_secrecy_i_a_I_A_B"
    # names the attacker made up differ only by their suffix
    assert display("(a_1,a,K_AP_3)", frozenset({"a_1", "a"})) == "(a_1,a,K_AP)"


def test_split_top_ignores_brackets():
    assert split_top("(~M_10,~M_11)= (A_3,I_1)") == ("(~M_10,~M_11)", "(A_3,I_1)")
    assert split_top("f(x=y)") is None
