"""pvtext over the fixture protocol's main.pv: role signatures, process blocks,
queries and their owner hints, directed channel naming, the channel rewrite the
honest-run probe undoes, and the value-lifetime projection."""

import pytest

from orrery.modules.pvtext import channels, parse, probe
from orrery.modules.pvtext.edits import replace_queries
from orrery.modules.pvtext.lifetime import PER_SESSION, value_lifetime
from tests.fixtures import MAIN_PV


@pytest.mark.parametrize("roles, expected", [
    (["A", "B"], ["c", "channel_A_B", "channel_B_A"]),
    (["A", "B", "S"], ["c", "channel_A_B", "channel_A_S", "channel_B_A",
                       "channel_B_S", "channel_S_A", "channel_S_B"]),
    (["A"], ["c"]),
])
def test_directed_channels_are_the_full_topology(roles, expected):
    # Every ordered pair of distinct roles, in role order, public channel
    # first. The order is deterministic so the rendered template is byte-stable.
    assert channels.directed_channel_names(roles) == expected


def test_parse_fixture_model():
    text = MAIN_PV.read_text()
    blocks = parse.process_blocks(text)
    assert blocks                                   # the role processes
    assert parse.queries(text)                      # every query line
    assert parse.role_signatures(text)


def test_channel_naming_convention():
    assert channels.channel_name("A", "B") == "channel_A_B"
    assert channels.parse_channel_name("channel_A_B", ["A", "B"]) == ("A", "B")
    assert channels.parse_channel_name("not_a_channel", ["A", "B"]) is None


def test_publicize_channels_undoes_the_templates_private_band():
    """The flow model runs on a Dolev-Yao network, so [private] belongs to the
    honest run alone and comes off with the rest of the probe."""
    text = "free channel_A_B: channel [private].\nfree c: channel.\n"
    out = probe.publicize_named_channels(text)
    assert "free channel_A_B: channel.\n" in out   # no stray space left behind
    assert "free c: channel.\n" in out             # public c is untouched


def test_strip_queries_removes_exactly_what_queries_lists():
    """Listing and stripping run the same regex over the comment-blanked text,
    so what is cut is what was listed and a query inside a comment is neither."""
    text = MAIN_PV.read_text()
    assert parse.queries(text)
    assert parse.queries(parse.strip_queries(text)) == []
    assert parse.process_blocks(parse.strip_queries(text))

    commented = "(*\nquery attacker(x).\n*)\nprocess\n  0\n"
    assert parse.queries(commented) == []
    assert parse.strip_queries(commented) == commented


def test_direct_query_owner_comment_survives_only_as_framework_metadata():
    text = ("query attacker(new session_key). (* secrecy_session_key *)\n"
            "process\n"
            "  new session_key: bitstring; 0\n")
    assert parse.queries(text) == ["query attacker(new session_key)."]
    hints = parse.query_owner_hints(text, ["secrecy_session_key"])
    assert hints == {"session_key": ["secrecy_session_key"]}
    assert parse.query_owners(
        "not attacker(session_key[!1 = v])", ["secrecy_session_key"], hints
    ) == ["secrecy_session_key"]
    assert parse.query_owners(
        "not attacker(session_key_2[!1 = v])", ["secrecy_session_key"], hints
    ) == ["secrecy_session_key"]
    stripped = parse.strip_queries(text)
    assert "secrecy_session_key" not in stripped
    assert "query attacker" not in stripped


def test_direct_query_exact_name_precedes_alpha_rename_fallback():
    hints = {"K": ["secrecy_k"], "K_2": ["secrecy_k_2"]}
    assert parse.query_owners(
        "not attacker(K_2[!1 = v])", ["secrecy_k", "secrecy_k_2"], hints
    ) == ["secrecy_k_2"]


def test_replacing_queries_removes_their_owner_comments_too():
    text = ("query attacker(new session_key). (* secrecy_session_key *)\n"
            "let processA =\n"
            "  0.\n"
            "process\n"
            "  processA\n")
    replaced = replace_queries(text, ["query attacker(other)."])
    assert "secrecy_session_key" not in replaced
    assert parse.queries(replaced) == ["query attacker(other)."]


def test_declarations_go_in_front_of_the_main_process():
    text = MAIN_PV.read_text()
    at = parse.main_keyword_start(text)
    assert text[at:at + len("process")] == "process"
    assert at + len("process") == parse.main_block(text)[0]
    with pytest.raises(parse.PvTextError):
        parse.main_keyword_start("free c: channel.\n")


def test_value_lifetime_is_read_off_the_model():
    """The lifetime projection the data axis's writings key on: a role-body
    new is per-session because role bodies run under replication, while a free,
    a parameter or a main-process new is long-lived. A name the model binds
    nowhere raises rather than defaulting."""
    from orrery.modules.pvtext.lifetime import (
        LONG_LIVED, PER_SESSION, value_lifetime,
    )
    pv = ("free KAB: bitstring [private].\n"
          "let roleA(A: host, KAB: bitstring) =\n"
          "  new NA: bitstring;\n"
          "  out(c, NA);\n"
          "  0.\n"
          "process\n"
          "  new NS: bitstring;\n"
          "  !roleA(A, KAB)\n")
    assert value_lifetime(pv, "KAB") == LONG_LIVED      # a free declaration
    assert value_lifetime(pv, "NA") == PER_SESSION      # new inside a role body
    assert value_lifetime(pv, "NS") == LONG_LIVED       # a main-process new
    with pytest.raises(ValueError, match="does not occur"):
        value_lifetime(pv, "GHOST")                     # anchoring, not a guess


def test_a_value_the_model_tags_per_role_still_has_a_lifetime():
    """A document value can be bound once per role (K_2 as K_2_U and K_2_V),
    so the declaration keeps the document's name and the lifetime is read off
    the per-role bindings."""
    pv = """\
let processU(PSK: key) =
  (* @ROLE U *)
  new K_2_U: key;
  0.

let processV(PSK: key) =
  (* @ROLE V *)
  new K_2_V: key;
  0.
"""
    assert value_lifetime(pv, "K_2") == PER_SESSION


def test_a_name_the_model_binds_nowhere_is_still_an_error():
    pv = """\
let processU(PSK: key) =
  (* @ROLE U *)
  0.
"""
    with pytest.raises(ValueError, match="does not occur in the model"):
        value_lifetime(pv, "ems")


def test_parallel_branches_needs_the_group_to_be_the_whole_body():
    """``( A | B )`` followed by anything else is not a parallel composition
    of two branches: reading the group alone would hide the branch after it
    from every check that counts branches."""
    from orrery.modules.pvtext.parse import parallel_branches, process_blocks
    whole = ("let processA(c: channel) =\n"
             "  ( in(c, m: bitstring) | out(c, a) ).\n\nprocess\n  0\n")
    trailing = ("let processA(c: channel) =\n"
                "  ( in(c, m: bitstring) | out(c, a) ) | (new n: bitstring; 0).\n"
                "\nprocess\n  0\n")
    assert len(parallel_branches(whole, process_blocks(whole)["A"])) == 2
    assert parallel_branches(trailing, process_blocks(trailing)["A"]) is None


def test_unreachable_matches_a_label_as_a_whole_word():
    """``auth_b_to_a`` is a prefix of ``auth_b_to_a_noninj``; the short goal's
    dead observation point must not be hidden by the long goal's live one."""
    from types import SimpleNamespace as NS

    from orrery.modules.pvtext.vacuity import unreachable
    verdicts = [NS(query="not event(obs_auth_b_to_a)", verdict="true"),
                NS(query="not event(obs_auth_b_to_a_noninj)", verdict="false")]
    points = [("obs_auth_b_to_a", "q1"), ("obs_auth_b_to_a_noninj", "q2")]
    assert unreachable(verdicts, points) == ["obs_auth_b_to_a"]
