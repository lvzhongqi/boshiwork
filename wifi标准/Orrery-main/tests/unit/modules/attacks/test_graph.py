"""Reading the dot file ``proverif -graph`` draws, from real runs."""

import pytest

from orrery.modules.attacks.graph import GraphError, parse, read
from tests.fixtures import ATTACK_GRAPHS


def test_sessions_rows_and_messages_of_the_lowe_attack():
    g = read(ATTACK_GRAPHS / "nspk_auth.dot")
    starts = {n.path: n.begins for n in g.nodes.values() if n.begins}
    assert starts == {"P0_10_0": "processS", "P0_11_0": "processB",
                      "P0_12_0": "processA", "P0_13_0": "processA"}
    a_start = next(n for n in g.nodes.values() if n.path == "P0_12_0" and n.begins)
    assert [(r.point, r.word, r.text) for r in a_start.rows] == [
        (42, "let", "intended_peer_A_1: host = I_1"),
        (40, "let", "A_2: host = A_3")]
    # a row ProVerif wrapped mid-term reads back whole
    rows = [r for n in g.nodes.values() for r in n.rows]
    assert any(r.text == "(PKA_recv: pkey,A_binding_recv: host) = "
                         "(pk(SKA_3),A_3)" for r in rows)
    assert any(r.text == "(I_1 = B_2): else branch taken" for r in rows)
    times = [m.time for m in g.messages]
    assert times == sorted(times)
    forged = [m for m in g.messages if m.direction == "in"
              and m.recipe.startswith("aenc((1-proj")]
    assert forged and forged[0].path == "P0_11_0"
    assert forged[0].value == "aenc((I_A_3,A_3),pk(SKB_2))"
    assert g.goal_path == "P0_11_0" and not g.goal_text


def test_actions_fall_between_the_messages_around_them():
    g = read(ATTACK_GRAPHS / "nspk_auth.dot")
    # A checks I's certificate, draws I_A and records its begin event after
    # receiving the certificate (clock 39) and before sending ~M_14 (clock 42)
    node = next(n for n in g.nodes.values()
                if any(r.word == "event" and r.text.startswith("begin_auth_b_a_i_a")
                       for r in n.rows))
    assert 39 < node.time < 42


def test_a_knowledge_goal_is_the_red_attacker_node():
    g = read(ATTACK_GRAPHS / "nspk_secrecy.dot")
    assert g.goal_text.startswith("The attacker has the message wdec_nonce(")
    assert g.goal_text.endswith("= witness_secrecy_i_a_I_A_B")
    assert not g.goal_path


_HEAD = 'digraph {\nP0__0 [label = "Honest Process"];\n'


def test_a_labelled_edge_that_is_not_a_message_is_an_error():
    text = _HEAD + 'P__3 -> P0_2__4 [label = <out(d, s)>];\n}'
    with pytest.raises(GraphError, match="not a message"):
        parse(text)


def test_a_graph_without_a_goal_is_an_error():
    text = _HEAD + '{rank = same; P__1 P0_1__1}\nP0_1__1 -> P__1 [label = <~M = s>, arrowhead = normal];\n}'
    with pytest.raises(GraphError, match="no goal"):
        parse(text)


def test_a_hand_over_between_two_processes_is_a_private_message():
    """5G-AKA's SEAF and AUSF talk over the backhaul the attacker cannot see:
    the edge runs process to process, labelled with an abbreviation whose
    value is the message, and it is timed on the two nodes' own row."""
    g = read(ATTACK_GRAPHS / "private_channel.dot")
    first = g.private[0]
    assert (first.src, first.dst) == ("P0_8_0", "P0_7_0")
    assert first.value.startswith("(nausf_authenticate_request_tag,make_SUCI(")
    assert not any("~X" in p.value for p in g.private)
    assert any(m.time < first.time for m in g.messages)
    assert any(m.time > first.time for m in g.messages)


def test_a_private_message_the_abbreviations_do_not_spell_out_is_an_error():
    text = _HEAD + 'P0_1__3 -> P0_2__4 [label = <out(d, s)>];\n}'
    with pytest.raises(GraphError, match="do not spell out"):
        parse(text)
