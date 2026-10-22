"""Attack graphs as scripts: the lanes, the steps, what is left out and why,
and how the goal closes the story."""

from orrery.modules.attacks.graph import read
from orrery.modules.attacks.script import ATTACKER, build
from tests.fixtures import ATTACK_GRAPHS


def _kinds(script):
    return [(s.kind, s.src, s.dst) for s in script.steps]


def test_lowe_against_secrecy_reads_as_the_textbook_attack():
    s = build(read(ATTACK_GRAPHS / "nspk_secrecy.dot"))
    A, B, S = "P0_12_0", "P0_11_0", "P0_10_0"
    assert [ln.id for ln in s.lanes] == [A, B, S]
    assert s.lanes[0].bindings == ["intended_peer_A: host = I", "A: host = A"]
    assert _kinds(s) == [
        ("send", A, ATTACKER), ("inject", ATTACKER, A), ("send", A, ATTACKER),
        ("forge", ATTACKER, B), ("send", B, ATTACKER), ("forge", ATTACKER, S),
        ("relay", S, B), ("relay", B, A), ("send", A, ATTACKER),
        ("forge", ATTACKER, B)]
    rewrap = s.steps[3]
    assert rewrap.value == "aenc((I_A,A),pk(SKB))"
    assert rewrap.computed == ["I_A"]
    assert "~M_1 = private_key_I" in rewrap.reads
    assert s.steps[9].computed == ["I_B"]
    # the certificate the attacker hands A was public from the start
    # read by the name the model's initial process bound it to
    assert s.steps[1].reads == ["~M = server_binding_I"]
    assert ("server_binding_I", "sign((public_key_I,I),SKas)") in [
        (d.name, d.body) for d in s.setup]
    assert "sign((pk(private_key_I),I),SKas)" in s.initial
    # the goal: the probe is part of it, and so is what the attacker computed
    assert s.outcome.kind == "knowledge"
    assert s.outcome.probe == "wenc_nonce(witness_secrecy_i_a_I_A_B,I_A)"
    assert s.outcome.probe_lane == B      # the goal watches B's copy of A's nonce
    assert s.outcome.computed == ["I_A", "witness_secrecy_i_a_I_A_B"]
    whys = {(o.get("lane"), o["why"]) for o in s.omitted}
    assert ("P0_13_0", "session took no part") in whys
    assert (B, "read by nothing after the attack") in whys


def test_rows_travel_on_their_sessions_next_step():
    s = build(read(ATTACK_GRAPHS / "nspk_auth.dot"))
    third = s.steps[2]                      # A sends ~M_14
    assert [(n.point, n.word) for n in third.notes] == [(47, "if"), (49, "event")]
    assert third.notes[1].text == "begin_auth_b_a_i_a(A,I,I_A)"
    # A's honest-peer check fails after its last send: it belongs to the goal
    assert any(n.text == "(I = B): else branch taken" for n in s.outcome.notes)


def test_an_agreement_goal_names_the_event_it_should_have_matched():
    s = build(read(ATTACK_GRAPHS / "nspk_auth.dot"))
    o = s.outcome
    assert (o.kind, o.lane, o.text) == ("event", "P0_11_0",
                                        "end_auth_b_a_i_a(A,B,I_A)")
    # B ends a session with A; A began one with I: the second argument differs
    assert o.counterparts == [{"event": "begin_auth_b_a_i_a(A,I,I_A)",
                               "point": 49, "differ": [1]}]


def test_a_disclosed_key_shows_in_what_the_attacker_reads():
    s = build(read(ATTACK_GRAPHS / "iso_leaked_key.dot"))
    assert [ln.role for ln in s.lanes] == ["processA"]
    assert "K_AP" in s.initial
    last = s.steps[-1]
    assert last.kind == "forge" and "~M_3 = K_AP" in last.reads
    # names the attacker made up keep their suffixes: they are different values
    assert s.steps[0].value == "(a_1,a)"
    assert last.value == "(a_5,senc((R_A,a_4,I_B,a_3),K_AP),a_2)"
    # A accepts a key the attacker chose, and no trusted party ever began
    assert s.outcome.text == "end_alice_injective_agreement_with_trusted_party(R_A,a_4)"
    assert s.outcome.counterparts == []


def test_the_script_is_plain_json():
    import json
    data = build(read(ATTACK_GRAPHS / "nspk_auth.dot")).to_json()
    assert json.loads(json.dumps(data)) == data


def test_an_offline_guess_is_the_messages_collected_then_the_test():
    """A weak secret: B only answers a correct h(pw, n), and its answer
    senc(s, pw) lets the attacker check a guess of pw offline. A never
    receives, yet what it sent is what the attacker forwards, so it takes
    part; B's last output is read by the test alone and is still a step."""
    s = build(read(ATTACK_GRAPHS / "weak_offline_guess.dot"))
    A, B = "P0_1_0", "P0_0_0"
    assert [ln.id for ln in s.lanes] == [A, B]
    assert _kinds(s) == [("send", A, ATTACKER), ("forge", ATTACKER, B),
                         ("send", B, ATTACKER)]
    assert s.steps[2].value == "senc(s,pw)"
    assert not s.omitted
    o = s.outcome
    assert (o.kind, o.text, o.probe) == ("guess", "pw", "")
    assert o.guess == {"test": "fail", "name": "@weaksecretcst",
                       "left": "sdec(~M_2,@weaksecretcst)", "right": "",
                       "known": ["~M_2 = senc(s,pw)"]}


def test_a_leaked_verifier_is_guessed_against_with_no_step():
    """The verifier J(pi) was handed out before any session ran: the attacker
    compares it with J of its guess and needs no message at all."""
    s = build(read(ATTACK_GRAPHS / "weak_leaked_verifier.dot"))
    assert (s.lanes, s.steps, s.initial) == ([], [], ["J(pi)"])
    assert s.outcome.kind == "guess" and s.outcome.text == "pi"
    assert s.outcome.guess == {"test": "equal", "name": "@weaksecretcst",
                               "left": "~M", "right": "J(@weaksecretcst)",
                               "known": ["~M = J(pi)"]}


def test_a_nested_tuple_output_binds_each_part():
    from orrery.modules.attacks.graph import Message
    from orrery.modules.attacks.script import _output_slots
    msg = Message(time=1, path="P0_1", direction="out",
                  recipe="((~M,~M_1),~M_2)", value="((A,pk(B)),n)")
    assert _output_slots(msg) == [("~M", "A"), ("~M_1", "pk(B)"), ("~M_2", "n")]


def test_a_process_that_splits_as_it_begins_is_placed_by_its_branches():
    """Neuman-Stubblebine's B begins and splits at once: its own node sits on
    no row of the attacker clock, and its branches' rows place it."""
    s = build(read(ATTACK_GRAPHS / "split_after_begin.dot"))
    assert len(s.steps) == 3 and s.outcome.kind == "event"


def test_an_abbreviated_message_is_spelled_out():
    """ProVerif labels a long output with its slots alone and lists what they
    hold in an Abbreviations table; the step carries the values."""
    s = build(read(ATTACK_GRAPHS / "abbreviated_messages.dot"))
    second = s.steps[1]
    assert second.kind == "send"
    assert second.value == ("(attacker_peer,SK_attacker_peer,pk(SK_attacker_peer),"
                            "sign((pk(SK_attacker_peer),attacker_peer),SKas))")
    assert not any("~M" in st.value for st in s.steps)


def test_an_output_a_data_constructor_wraps_binds_each_part():
    from orrery.modules.attacks.graph import Message
    from orrery.modules.attacks.script import _output_slots
    msg = Message(time=1, path="P0_1", direction="out",
                  recipe="sn(~M,~M_1)", value="sn(mcc,mnc)")
    assert _output_slots(msg) == [("~M", "mcc"), ("~M_1", "mnc")]


def test_a_private_hand_over_is_a_step_between_two_sessions():
    """5G-AKA's SEAF asks the AUSF over the backhaul: a step from one session
    to the other, both kept, the attacker on neither end."""
    s = build(read(ATTACK_GRAPHS / "private_channel.dot"))
    private = [st for st in s.steps if st.kind == "private"]
    assert private and ATTACKER not in (private[0].src, private[0].dst)
    assert {private[0].src, private[0].dst} <= {ln.id for ln in s.lanes}
    assert [st.n for st in s.steps] == list(range(1, len(s.steps) + 1))


def test_long_or_reused_terms_go_by_a_name_defined_where_they_are_made():
    """Lowe's attack in the textbook's shape: A's first message is sent and
    then opened by the attacker, so it is msg3, defined on A's lifeline; B's
    reply is passed to A unchanged under one name; what the initial process
    bound keeps the model's own name; a short term used once is written out.
    Expanding the names gives ProVerif's term back."""
    s = build(read(ATTACK_GRAPHS / "nspk_auth.dot"))
    A = "P0_12_0"
    third, forged, relayed = s.steps[2], s.steps[3], s.steps[7]
    assert third.label == "msg3"
    assert [(d.lane, d.name, d.body) for d in third.defs] == [
        (A, "msg3", "aenc((I_A,A),public_key_I)")]
    assert third.defs[0].value == third.value
    # the attacker's own work is boxed on its lifeline: what it opened, then
    # the message it put together
    assert forged.label == "msg4" and "~M_14 = msg3" in forged.reads
    assert [(d.lane, d.kind, d.name, d.body) for d in forged.defs] == [
        (ATTACKER, "derive", "I_A", "adec(msg3,private_key_I).1"),
        (ATTACKER, "name", "msg4", "aenc((I_A,A),PKB)")]
    assert relayed.kind == "relay" and relayed.label == "msg8"
    assert {d.name for d in s.setup} >= {"PKA", "PKB", "server_binding_A"}


def test_a_value_the_attacker_made_takes_its_receivers_name_primed():
    """5G-AKA: the attacker builds its own SUCI; the network bound it as
    SUCI_recv, so it reads SUCI′ — another SUCI than the UE's."""
    s = build(read(ATTACK_GRAPHS / "private_channel.dot"))
    forged = next(st for st in s.steps if st.kind == "forge")
    names = {d.name: d for d in forged.defs}
    assert "SUCI′" in names and names["SUCI′"].lane == ATTACKER
    assert any(d.name == "SUCI" for st in s.steps for d in st.defs)


def test_a_secret_says_whose_value_was_lost_and_what_it_was():
    """Denning-Sacco with A's server key leaked: the attacker makes up a, a_1,
    a_2 and sends A a server message of its own, so the Kab A ends up holding
    is the attacker's a. The witness names the target and the holder; the
    probe carries the value."""
    from orrery.modules.attacks.graph import read as read_dot
    s = build(read_dot(ATTACK_GRAPHS / "ds_leaked_key.dot"), goal="secrecy_kab")
    forged = s.steps[1]
    assert [(d.kind, d.name) for d in forged.defs] == [
        ("new", "a, a_2, a_1"), ("name", "msg2")]
    assert forged.defs[1].body == "senc((B,a,a_2,a_1),Ksa)"
    assert s.outcome.secret == {"name": "Kab", "holder": "A", "value": "a"}
    assert s.outcome.probe_lane == s.lanes[0].id
