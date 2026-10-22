"""The baseline's probe: where instrumentation may sit, what is asked of
ProVerif, and how the answers are read. The solver runs live in
``runner.measure``; these tests pin the text handed over and its reading.
"""

from orrery.infra.proverif.outcome import QueryVerdict
from orrery.modules.pvtext.parse import PvTextError, main_keyword_start, queries, strip_queries
from orrery.modules.pvtext.probe import remove_probe, strip_probe

from experiments.oneshot import probe

MODEL = """free c: channel.
free channel_A_B: channel [private].

event begin_auth(bitstring).
event end_auth(bitstring).
event reached_A().
event reached_B().

query attacker(w_secrecy).
query x: bitstring; inj-event(end_auth(x)) ==> inj-event(begin_auth(x)).
query event(reached_A()).
query event(reached_B()).

let processA(k: bitstring) =
    out(c, k);
    event reached_A().

let processB(k: bitstring) =
    in (c, m: bitstring);
    event end_auth(m);
    event reached_B().

process
  ( !processA(k) | !processB(k) )
"""


def _v(*pairs):
    return [QueryVerdict(query=q, verdict=v) for q, v in pairs]


# placement

def test_a_probe_at_the_end_of_each_body_marks_both_roles():
    place = probe.placement(MODEL)
    assert place == {"roles": ["A", "B"], "marked": ["A", "B"],
                     "probe_of": {"A": "A", "B": "B"}, "problems": []}


def test_the_event_need_not_be_named_after_the_role():
    """A model that wrote ``let process_initiator`` marks its end with
    ``reached_initiator``, so the role is read off the event name rather than
    the ``process`` prefix."""
    text = (MODEL.replace("processA", "process_initiator")
                 .replace("reached_A", "reached_initiator"))
    place = probe.placement(text)
    assert place["marked"] == ["B", "_initiator"]
    assert place["probe_of"]["_initiator"] == "initiator"
    assert place["problems"] == []


def test_the_roles_are_the_process_definitions_the_model_chose():
    # Process names are the model's own choice, so an unconventional name is
    # still a role, and one without a probe stays unmarked.
    text = (MODEL.replace("let processB(k: bitstring) =", "let helper(k: bitstring) =")
                 .replace("    event reached_B().", "    0."))
    place = probe.placement(text)
    assert place["roles"] == ["A", "helper"]
    assert place["marked"] == ["A"]
    assert place["problems"] == ["role helper's body never marks its honest end"]


def test_a_probe_followed_by_a_semicolon_is_a_waypoint_not_an_ending():
    text = MODEL.replace("    event reached_A().",
                         "    event reached_A();\n    0.")
    place = probe.placement(text)
    assert place["marked"] == ["B"]
    assert "is followed by `;`" in " ".join(place["problems"])


def test_a_probe_two_bodies_can_reach_speaks_for_neither():
    text = MODEL.replace("""let processB(k: bitstring) =
    in (c, m: bitstring);
    event end_auth(m);
    event reached_B().""",
                         """let processB(k: bitstring) =
    in (c, m: bitstring);
    event end_auth(m);
    event reached_A().""")
    place = probe.placement(text)
    assert place["marked"] == []
    assert "a probe that more than one role can reach" in " ".join(place["problems"])


def test_a_probe_in_the_main_process_disqualifies_that_role():
    text = MODEL.replace("  ( !processA(k) | !processB(k) )",
                         "  event reached_A();\n  ( !processA(k) | !processB(k) )")
    place = probe.placement(text)
    assert place["marked"] == ["B"]
    assert "the main process calls" in " ".join(place["problems"])


# reading the probe verdicts

def test_reachable_is_false_or_cannot_be_proved_never_true():
    place = probe.placement(MODEL)
    reach = probe.read_reach(
        _v(("not event(reached_A)", "false"),
           ("not event(reached_B)", "cannot_be_proved")), place)
    assert reach == {"per_role": {"A": True, "B": True}, "all": True,
                     "no_verdict": []}


def test_a_role_proverif_proved_unreachable_is_false():
    place = probe.placement(MODEL)
    reach = probe.read_reach(
        _v(("not event(reached_A)", "false"),
           ("not event(reached_B)", "true")), place)
    assert reach["per_role"] == {"A": True, "B": False}
    assert reach["all"] is False


def test_an_unmarked_role_is_unreachable_without_asking_the_solver():
    text = MODEL.replace("    event reached_B().", "    0.")
    place = probe.placement(text)
    reach = probe.read_reach(_v(("not event(reached_A)", "false")), place)
    assert reach["per_role"] == {"A": True, "B": False}
    assert reach["no_verdict"] == []


def test_a_marked_role_with_no_verdict_is_named_rather_than_guessed():
    place = probe.placement(MODEL)
    reach = probe.read_reach(_v(("not event(reached_A)", "false")), place)
    assert reach["per_role"]["B"] is False
    assert reach["no_verdict"] == ["B"]


# the vacuity queries

def test_only_goals_that_declared_an_end_event_get_a_vacuity_query():
    ends = probe.end_events(MODEL, ["auth", "secrecy"])
    assert ends == {"auth": ("bitstring",)}


def test_the_query_binds_one_variable_per_declared_type():
    assert (probe.vacuity_query("auth", ("bitstring", "host"))
            == "query x0: bitstring, x1: host; event(end_auth(x0, x1)).")
    assert probe.vacuity_query("auth", ()) == "query event(end_auth())."


def test_the_vacuity_form_carries_our_queries_and_no_others():
    ends = probe.end_events(MODEL, ["auth"])
    text = probe.vacuity_form(MODEL, ends)
    assert queries(text) == ["query x0: bitstring; event(end_auth(x0))."]
    assert "reached_" not in text
    # Declarations have to precede the main process or ProVerif refuses the file.
    assert text.index("event(end_auth") < main_keyword_start(text)


def test_vacuous_means_the_end_event_can_never_happen():
    ends = probe.end_events(MODEL, ["auth"])
    assert probe.read_vacuity(_v(("not event(end_auth(x0))", "true")), ends) == {"auth": True}
    assert probe.read_vacuity(_v(("not event(end_auth(x0))", "false")), ends) == {"auth": False}
    assert probe.read_vacuity(_v(), ends) == {}


# what the baseline reuses from the pipeline

def test_instrument_adds_the_fixed_reconstruct_setting_once():
    text = probe.instrument(MODEL)
    assert text.startswith("set reconstructTrace = false.\n")
    assert text.count("reconstructTrace") == 1
    assert "reconstructTrace" not in remove_probe(text)


def test_instrument_overrides_a_model_written_reconstruct_setting():
    text = probe.instrument("set reconstructTrace = true.\n" + MODEL)
    assert text.startswith("set reconstructTrace = false.\n")
    assert text.count("reconstructTrace") == 1

def test_remove_probe_leaves_the_channels_the_scenario_declared():
    # In a scenario model a [private] channel can be the scenario's own
    # confidential-channel assumption, so only strip_probe publishes it.
    assert "free channel_A_B: channel [private]." in remove_probe(MODEL)
    assert "free channel_A_B: channel." in strip_probe(MODEL)


def test_strip_queries_removes_exactly_what_queries_lists():
    assert queries(strip_queries(MODEL)) == []
    assert "let processA" in strip_queries(MODEL)


def test_a_file_with_no_main_process_is_an_error_not_an_empty_answer():
    try:
        main_keyword_start("free c: channel.\n")
    except PvTextError:
        return
    raise AssertionError("expected PvTextError")
