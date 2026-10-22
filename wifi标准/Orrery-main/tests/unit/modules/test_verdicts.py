"""Splitting ProVerif verdicts by naming anchor: the normal split, substring
disambiguation, owner hints from source comments, and the two raising paths
(an unidentifiable owner, and a goal with no verdict)."""

import pytest

from orrery.infra.proverif.outcome import QueryVerdict
from orrery.modules.verdicts.split import combine, split_by_goal


def _qv(q, v):
    return QueryVerdict(query=q, verdict=v)


def test_split_and_combine():
    out = split_by_goal(
        [_qv("not attacker(w_secrecy_i_a[])", "true"),
         _qv("inj-event(end_auth_b_to_a(x)) ==> inj-event(begin_auth_b_to_a(x))",
             "false")],
        ["secrecy_i_a", "auth_b_to_a"], where="t",
    )
    assert out == {"secrecy_i_a": "true", "auth_b_to_a": "false"}


def test_substring_ids_disambiguate_to_longer():
    # auth_b_to_a is a substring of auth_b_to_a_noninj, so a query carrying
    # _noninj matches both ids and the longer one wins.
    out = split_by_goal(
        [_qv("event(end_auth_b_to_a_noninj(x)) ==> event(begin_auth_b_to_a_noninj(x))",
             "true"),
         _qv("inj-event(end_auth_b_to_a(x)) ==> inj-event(begin_auth_b_to_a(x))",
             "false")],
        ["auth_b_to_a", "auth_b_to_a_noninj"], where="t",
    )
    assert out == {"auth_b_to_a_noninj": "true", "auth_b_to_a": "false"}


def test_unclaimed_query_raises():
    with pytest.raises(RuntimeError, match="cannot tell which goal"):
        split_by_goal([_qv("not attacker(secret[])", "true")], ["goal_x"], where="t")


def test_goal_without_verdict_raises():
    with pytest.raises(RuntimeError, match="no verdict at all"):
        split_by_goal([_qv("not attacker(w_a[])", "true")], ["a", "b"], where="t")


def test_cannot_be_proved_combines_to_unknown():
    assert combine(["true", "cannot_be_proved"]) == "unknown"
    assert combine(["cannot_be_proved", "false"]) == "false"


def test_direct_query_verdict_uses_owner_hint_from_source_comment():
    out = split_by_goal(
        [_qv("not attacker(session_key[!1 = v])", "true")],
        ["secrecy_session_key"], where="t",
        owner_hints={"session_key": ["secrecy_session_key"]},
    )
    assert out == {"secrecy_session_key": "true"}


def test_alpha_renamed_direct_query_uses_source_owner_hint():
    out = split_by_goal(
        [_qv("not attacker(Kab_2[Ksb_2 = v,!1 = sid])", "false")],
        ["secrecy_kab"], where="t",
        owner_hints={"Kab": ["secrecy_kab"]},
    )
    assert out == {"secrecy_kab": "false"}


def test_phase_direct_query_uses_source_owner_hint():
    out = split_by_goal(
        [_qv("not attacker_p1(APP_3[message_2_recv = v,!1 = sid])", "true")],
        ["secrecy_app3_phase0"], where="t",
        owner_hints={"APP_3": ["secrecy_app3_phase0"]},
    )
    assert out == {"secrecy_app3_phase0": "true"}
