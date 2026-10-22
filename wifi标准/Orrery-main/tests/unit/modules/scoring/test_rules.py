"""The scoring judgements exercised on literals. Every case is a shape a real
extraction can produce, and none of them needs a run, a file or a corpus."""
from orrery.modules.scoring import rules as R
from orrery.nodes.apply.realizers import VOCAB, subtype_is_noop


# ── the matcher ──────────────────────────────────────────────────────────────
def test_one_gold_entry_is_claimed_once():
    """One corpus entry absorbs one candidate; the lookalikes left over are
    extras. Letting all three count is how a score comes out above the truth."""
    pairs, missed, extra = R.greedy_match(["a", "a", "a"], ["a"],
                                          lambda c, g: c == g)
    assert (len(pairs), missed, extra) == (1, [], ["a", "a"])


# ── principals ───────────────────────────────────────────────────────────────
_GOLD_P = {
    "principals": [{"name": "A"}, {"name": "B"}],
    "values": [
        {"name": "SKA", "derived_from": [], "description": "A private key"},
        {"name": "PKA", "derived_from": ["SKA"], "description": "A public key"},
        {"name": "SKB", "derived_from": [], "description": "B private key"},
        {"name": "PKB", "derived_from": ["SKB"], "description": "B public key"},
        {"name": "A", "derived_from": [], "description": "identity A"},
    ],
}


def test_principals_perfect_on_itself():
    s = R.score_principals(_GOLD_P, _GOLD_P)
    assert (s["num"], s["den"], s["extra"]) == (5, 5, 0)
    assert s["principals"] == {"num": 2, "den": 2}


def test_a_dropped_principal_keeps_its_share_of_the_denominator():
    """The corpus value inventory remains the denominator when a party and its
    values disappear."""
    cand = {"principals": [{"name": "A"}],
            "values": _GOLD_P["values"][:2] + _GOLD_P["values"][-1:]}
    s = R.score_principals(cand, _GOLD_P)
    assert s["den"] == 5 and s["num"] == 3
    assert s["principals"] == {"num": 1, "den": 2}


def test_a_reordered_source_list_is_the_same_fact():
    """derived_from records which values a term depends on, not the order they
    were written in, so it is compared as a set. Comparing it as a sequence
    turns a key derived from two nonces into a miss plus an extra."""
    gold = {"principals": [{"name": "A"}],
            "values": [
                {"name": "Na", "derived_from": [], "description": "nonce"},
                {"name": "Nb", "derived_from": [], "description": "nonce"},
                {"name": "K", "derived_from": ["Na", "Nb"],
                 "description": "session key"},
            ]}
    cand = {**gold,
            "values": gold["values"][:2] + [
                {**gold["values"][2], "derived_from": ["Nb", "Na"]}]}
    s = R.score_principals(cand, gold)
    assert (s["num"], s["den"], s["extra"]) == (3, 3, 0)


def test_over_production_scores_nothing_and_is_counted():
    cand = {**_GOLD_P,
            "principals": _GOLD_P["principals"] + [{"name": "Mallory"}],
            "values": _GOLD_P["values"] + [
                {"name": "Z", "derived_from": [], "description": "extra"}]}
    s = R.score_principals(cand, _GOLD_P)
    assert s["num"] == 5 and s["extra"] == 1


def test_principals_alignment_renames_then_scores_exactly():
    cand = {
        "principals": [{"name": "Initiator"}, {"name": "Responder"}],
        "values": [
            {"name": "sk_Initiator", "derived_from": [], "description": "private"},
            {"name": "pk_Initiator", "derived_from": ["sk_Initiator"],
             "description": "public"},
            {"name": "sk_Responder", "derived_from": [], "description": "private"},
            {"name": "pk_Responder", "derived_from": ["sk_Responder"],
             "description": "public"},
            {"name": "initiator_id", "derived_from": [], "description": "identity"},
        ],
    }
    maps = {
        "principals": {"Initiator": "A", "Responder": "B"},
        "symbols": {
            "sk_Initiator": "SKA", "pk_Initiator": "PKA",
            "sk_Responder": "SKB", "pk_Responder": "PKB",
            "initiator_id": "A",
        },
    }
    s = R.score_principals_aligned(cand, _GOLD_P, maps)
    assert (s["num"], s["den"], s["extra"]) == (5, 5, 0)


# ── assumptions ──────────────────────────────────────────────────────────────
def _assum(**kw):
    return {"vocab_version": "2.2.0", "world": [], "fixed": [], "variable": [], **kw}


_GOLD_A = _assum(
    fixed=[{"id": "g1", "axis": "data", "target": {"of": "SKA"},
            "subtype": "assumed_secure"}],
    variable=[{"id": "g2", "axis": "admission", "target": {"scope": "peer_auth"},
               "subtypes": ["closed", "open"]}])


def test_assumption_matches_on_one_shared_target_value():
    """Ids differ and the target is written differently; the axis, the answer
    and one shared name are what identify the entry."""
    cand = _assum(fixed=[{"id": "x", "axis": "data", "target": {"of": "SKA"},
                          "subtype": "assumed_secure"}],
                  variable=[{"id": "y", "axis": "admission",
                             "target": {"scope": "peer_auth"},
                             "subtypes": ["open", "closed"]}])
    assert R.score_assumptions(cand, _GOLD_A)["num"] == 2


def test_wrong_subtype_is_a_miss():
    cand = _assum(fixed=[{"id": "x", "axis": "data", "target": {"of": "SKA"},
                          "subtype": "disclosed"}])
    s = R.score_assumptions(cand, _GOLD_A)
    assert (s["num"], s["den"], s["extra"]) == (0, 2, 1)


def test_a_variable_missing_a_rung_is_a_miss():
    """The subtypes of a variable dimension are its answer: leave one out and
    the run expands a different scenario space."""
    cand = _assum(variable=[{"id": "y", "axis": "admission",
                             "target": {"scope": "peer_auth"},
                             "subtypes": ["closed"]}])
    assert R.score_assumptions(cand, _GOLD_A)["num"] == 0


def test_a_variable_superset_covers_a_gold_variable():
    cand = _assum(variable=[{"id": "y", "axis": "admission",
                             "target": {"scope": "peer_auth"},
                             "subtypes": ["closed", "open", "invitation_only"]}])
    assert R.score_assumptions(cand, _GOLD_A)["num"] == 1


def test_a_variable_containing_a_fixed_rung_covers_the_gold_query():
    cand = _assum(variable=[{"id": "x", "axis": "data",
                             "target": {"of": "SKA"},
                             "subtypes": ["disclosed", "assumed_secure"]}])
    assert R.score_assumptions(cand, _GOLD_A)["num"] == 1


def test_a_fixed_entry_does_not_cover_a_gold_variable():
    cand = _assum(fixed=[{"id": "y", "axis": "admission",
                          "target": {"scope": "peer_auth"},
                          "subtype": "closed"}])
    assert R.score_assumptions(cand, _GOLD_A)["num"] == 0


def test_world_entries_remain_section_exact():
    gold = _assum(world=[{"id": "g", "axis": "population",
                          "target": {"role": "peer"}, "subtype": "bounded"}])
    cand = _assum(variable=[{"id": "c", "axis": "population",
                             "target": {"role": "peer"},
                             "subtypes": ["bounded", "unbounded"]}])
    assert R.score_assumptions(cand, gold)["num"] == 0


# ── properties ───────────────────────────────────────────────────────────────
_GOLD_R = {"properties": [
    {"id": "p1", "type": "Secrecy", "subtype": "basic", "values": ["I_A"],
     "parties": {"holders": ["A", "B"]}},
    {"id": "p2", "type": "Authentication", "subtype": "injective_agreement",
     "values": ["I_B"], "parties": {"asserter": "A", "subject": "B"}},
]}


def test_property_matches_on_type_subtype_and_one_shared_name():
    cand = {"properties": [
        {"id": "z", "type": "Secrecy", "subtype": "basic", "values": ["I_A"],
         "parties": {"holders": ["A"]}}]}
    assert R.score_properties(cand, _GOLD_R)["num"] == 1


def test_a_weaker_goal_of_the_right_shape_is_a_miss():
    """agreement where the corpus says injective_agreement is a different
    claim, not a near miss."""
    cand = {"properties": [
        {"id": "z", "type": "Authentication", "subtype": "agreement",
         "values": ["I_B"], "parties": {"asserter": "A", "subject": "B"}}]}
    assert R.score_properties(cand, _GOLD_R)["num"] == 0


# ── claims ───────────────────────────────────────────────────────────────────
# Claims are scored as the cells they assert, by the rule the verdicts are:
# each scenario spelled out as its complete world, the goal by what it is
# about. The candidate goal is _SAME_R's, the corpus's p1 under another id.
_GOLD_C = {"vocab_version": "2.2.0",
           "scenarios": [{"name": "baseline", "conditions": []},
                         {"name": "open", "conditions": [
                             {"id": "g2", "subtype": "open"}]}],
           "claims": [{"property": "p1", "scenarios": ["baseline", "open"]}]}


def _cand_claims(*scenarios):
    """The candidate claims z under the named scenarios: ``s0`` is the flow
    state, ``s1`` sets its admission open."""
    table = {"s0": [], "s1": [{"id": "y", "subtype": "open"}]}
    names = scenarios or ("s0", "s1")
    return {"vocab_version": "2.2.0",
            "scenarios": [{"name": n, "conditions": table[n]} for n in names],
            "claims": [{"property": "z", "scenarios": list(names)}]}


_CAND_A = _assum(fixed=[{"id": "x", "axis": "data", "target": {"of": "SKA"},
                         "subtype": "assumed_secure"}],
                 variable=[{"id": "y", "axis": "admission",
                            "target": {"scope": "peer_auth"},
                            "subtypes": ["closed", "open"]}])


#: A goal that shares a name with p1 but names one holder where p1 names two.
_CAND_R = {"properties": [{"id": "z", "type": "Secrecy", "subtype": "basic",
                           "values": ["I_A"], "parties": {"holders": ["A"]}}]}


def _claims(cand, cand_assum=_CAND_A, cand_props=None):
    return R.score_claims(cand, _GOLD_C, cand_assum, _GOLD_A,
                          cand_props or _SAME_R, _GOLD_R,
                          instance_of=VOCAB.instance_of, is_noop=subtype_is_noop)


def test_claims_pair_as_cells_whatever_the_names():
    s = _claims(_cand_claims())
    assert (s["num"], s["den"], s["extra"]) == (2, 2, 0)


def test_the_right_goal_under_the_wrong_world_does_not_count():
    """Both vocabularies match and the goal is claimed, but only in the flow
    state: the corpus's open-admission cell is missed, and nothing is extra."""
    s = _claims(_cand_claims("s0"))
    assert (s["num"], s["den"], s["extra"]) == (1, 2, 0)
    assert s["detail"][0]["miss"] == [
        "p1@[('g1', 'assumed_secure'), ('g2', 'open')]"]


def test_a_goal_about_something_else_claims_nothing():
    """Sharing a name used to be enough; the goal has to say the same thing."""
    s = _claims(_cand_claims(), cand_props=_CAND_R)
    assert (s["num"], s["extra"]) == (0, 2)


def test_worlds_that_differ_only_where_the_corpus_is_silent_pair_with_neither():
    """The run varies a channel the corpus never mentions: both its worlds
    answer the shared objects alike, so neither can be told for a corpus one."""
    bad = _assum(fixed=[{"id": "x", "axis": "data", "target": {"of": "SKA"},
                         "subtype": "assumed_secure"}],
                 variable=[{"id": "y", "axis": "channel", "target": {"link": "AB"},
                            "subtypes": ["public", "secure"]}])
    cand = {"vocab_version": "2.2.0",
            "scenarios": [{"name": "s0", "conditions": []},
                          {"name": "s1", "conditions": [{"id": "y", "subtype": "secure"}]}],
            "claims": [{"property": "z", "scenarios": ["s0", "s1"]}]}
    assert _claims(cand, cand_assum=bad)["num"] == 0


# ── verdicts ─────────────────────────────────────────────────────────────────
# A cell is the same cell on both sides when its goal is about the same thing
# and its scenario answers the shared objects alike (modules/verdicts/cells),
# the rule cross_check pairs by too. The candidate goal here says exactly what
# the corpus's p1 says, under another id.
_SAME_R = {"properties": [{"id": "z", "type": "Secrecy", "subtype": "basic",
                           "values": ["I_A"], "parties": {"holders": ["B", "A"]}}]}


def _cases(pid, aid, verdicts, more=()):
    return {"cases": [{"id": pid, "by_scenario": [
        {"scenario": [{"id": aid, "subtype": sub}, *more], "verdict": v}
        for sub, v in verdicts]}]}


def _verdicts(cand, gold, cand_assum=_CAND_A, cand_props=_SAME_R):
    return R.score_verdicts(cand, gold, cand_assum, _GOLD_A, cand_props, _GOLD_R,
                            instance_of=VOCAB.instance_of)


def test_a_cell_the_run_never_produced_counts_against_it():
    """The corpus's cell count is the denominator: leaving a scenario out is a
    wrong answer, not a smaller exam."""
    gold = _cases("p1", "g2", [("closed", "true"), ("open", "false")])
    cand = _cases("z", "y", [("closed", "true")])
    s = _verdicts(cand, gold)
    assert (s["num"], s["den"]) == (1, 2)


def test_a_disagreeing_cell_is_named():
    gold = _cases("p1", "g2", [("open", "false")])
    cand = _cases("z", "y", [("open", "true")])
    s = _verdicts(cand, gold)
    assert s["num"] == 0
    assert s["detail"] == [{"goal": "p1", "ours": "true", "expected": "false"}]


def test_an_object_only_the_run_speaks_about_is_left_out():
    """The run also declares something the corpus leaves unsaid; the cells
    still pair on the objects both speak about."""
    extra = _assum(fixed=[{"id": "x", "axis": "data", "target": {"of": "SKA"},
                           "subtype": "assumed_secure"},
                          {"id": "w", "axis": "data", "target": {"of": "PKI"},
                           "subtype": "disclosed"}],
                   variable=_CAND_A["variable"])
    gold = _cases("p1", "g2", [("closed", "true"), ("open", "false")])
    cand = _cases("z", "y", [("closed", "true"), ("open", "false")],
                  more=[{"id": "w", "subtype": "disclosed"}])
    s = _verdicts(cand, gold, cand_assum=extra)
    assert (s["num"], s["den"], s["extra"]) == (2, 2, 0)


def test_a_goal_about_less_than_the_corpus_goal_is_another_goal():
    """One holder where the corpus names two: the recall score may credit it,
    the cells do not pair with it."""
    gold = _cases("p1", "g2", [("open", "false")])
    cand = _cases("z", "y", [("open", "false")])
    s = _verdicts(cand, gold, cand_props=_CAND_R)
    assert (s["num"], s["den"], s["extra"]) == (0, 1, 1)


# ── results (the property's own answer) ──────────────────────────────────────
def _results(pairs):
    return {"results": [{"id": i, "verdict": v} for i, v in pairs]}


_GOLD_RES = _results([("p1", "false")])
_GOLD_CASES = _cases("p1", "g2", [("closed", "true"), ("open", "false")])
_CAND_CASES = _cases("z", "y", [("closed", "true"), ("open", "false")])


def _score_res(cand_res, cand_cases=_CAND_CASES):
    return R.score_results(cand_res, _GOLD_RES, cand_cases, _GOLD_CASES,
                           _CAND_A, _GOLD_A, _SAME_R, _GOLD_R,
                           instance_of=VOCAB.instance_of)


def test_the_property_answer_is_scored_through_the_goal_pairing():
    s = _score_res(_results([("z", "false")]))
    assert (s["num"], s["den"], s["extra"]) == (1, 1, 0)


def test_the_cells_behind_the_answer_are_scored_too():
    """Both levels come from one step, so they are scored in one place: a
    property answer that is right for the wrong reason shows up here."""
    s = _score_res(_results([("z", "false")]))
    assert s["cells"] == {"num": 2, "den": 2, "score": 1.0, "extra": 0}


def test_the_right_answer_out_of_the_wrong_world_is_visible_in_the_cells():
    """Conjoining `false` from the wrong scenario reaches the same property
    answer. The headline agrees and the cells do not."""
    swapped = _cases("z", "y", [("closed", "false"), ("open", "true")])
    s = _score_res(_results([("z", "false")]), swapped)
    assert s["num"] == 1                      # the conjunction is false either way
    assert s["cells"]["num"] == 0             # and both cells are on the wrong side


def test_a_property_the_run_never_answered_counts_against_it():
    s = _score_res(_results([]))
    assert (s["num"], s["den"]) == (0, 1)


def test_a_disagreeing_property_is_named():
    s = _score_res(_results([("z", "true")]))
    assert s["num"] == 0
    assert s["detail"] == [{"property": "p1", "ours": "true", "expected": "false"}]


# ── flow ─────────────────────────────────────────────────────────────────────
def test_flow_is_its_two_gates():
    s = R.score_flow({"flow_typecheck": True, "flow_reachability": False,
                      "flow_fixed_parts": True})
    assert (s["num"], s["den"]) == (1, 2)
    assert s["flow_typecheck"] is True and s["flow_reachability"] is False


def test_a_missing_gate_is_a_failed_gate():
    assert R.score_flow({})["num"] == 0
