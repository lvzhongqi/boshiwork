"""The claims gate's closure rules on the assumption vocabulary: every
multi-writing point has a writing on this model, a scenario may not hand the
attacker a value and claim its secrecy at once, the windowed data rungs
presuppose their arena, and one (axis, object) is answered once per scenario.
Name anchoring and its alias canonicalisation are covered here too."""

import pytest

from orrery.modules.libschema import io as lio
from orrery.modules.pvtext.lifetime import LONG_LIVED, value_lifetime
from orrery.nodes.base import NodeError
from orrery.version import VOCAB_VERSION
from orrery.nodes.claims.node import (
    _anchor_owners,
    anchor_names,
    canonicalize_anchored_names,
    validate_semantic_alignment,
    reject_commitment_conflicts,
    reject_double_answers,
    reject_degenerate_leaks,
    reject_window_without_arena,
    reject_writing_gaps,
)

# World-level assumptions live in their own section of assumptions.json; the
# gate reads it to check the windowed rungs' terrain. An axis nobody states
# takes its flow state, so an empty section is the unbounded world.
SINGLE_SESSION = [{"id": "world_one_session", "axis": "session_multiplicity",
                   "subtype": "single_session"}]

# KAB is long-lived (free), NA per-session (new inside a role body); the
# lifetime is read off the model text by pvtext.lifetime.
PV = """\
free c: channel.
free KAB: bitstring [private].
let roleA(A: host, KAB: bitstring) =
  new NA: bitstring;
  out(c, NA);
  0.
process
  !roleA(A, KAB)
"""

ASSUM = {
    "vocab_version": "2.2.0",
    "world": [], "fixed": [],
    "variable": [
        {"id": "kab_leak", "axis": "data",
         "target": {"of": "KAB"},
         "subtypes": ["none", "disclosed", "leaked_after_correct_session"]},
        {"id": "na_window", "axis": "data",
         "target": {"of": "NA"},
         "subtypes": ["none", "disclosed", "leaked_in_other_instances",
                      "leaked_after_correct_session"]},
    ],
}

PROPS = {
    "vocab_version": "2.2.0",
    "properties": [
        {"id": "sec_kab", "type": "Secrecy", "subtype": "basic",
         "values": ["KAB"], "parties": {"holders": ["A"]}},
        {"id": "sec_na", "type": "Secrecy", "subtype": "basic",
         "values": ["NA"], "parties": {"holders": ["A"]}},
    ],
}


def test_anchor_name_aliases_are_canonicalised_for_downstream_model_reads():
    """A supplied corpus may spell a value Kas while the flow model binds
    K_as. Anchoring carries the unambiguous match into the artifacts that
    lifetime selection and the apply/inject stages read."""
    assumptions = lio.parse_assumptions({
        "vocab_version": "2.2.0", "world": [], "fixed": [], "variable": [
            {"id": "reveal_A", "axis": "data",
             "target": {"of": "Kas"},
             "subtypes": ["none", "disclosed"]},
        ],
    })
    properties = lio.parse_properties({
        "vocab_version": "2.2.0", "properties": [
            {"id": "secret", "type": "Secrecy", "subtype": "basic",
             "values": ["Kas"], "parties": {"holders": ["A"]}},
        ],
    })
    pv = """\
process
  new A: host;
  new K_as: key;
  0.
"""

    anchoring = anchor_names(assumptions, properties, pv)

    assert anchoring.missing == []
    assert anchoring.value_aliases == {"Kas": "K_as"}
    assert anchoring.entity_aliases == {}
    canonicalize_anchored_names(assumptions, properties,
                                value_aliases=anchoring.value_aliases,
                                entity_aliases=anchoring.entity_aliases)
    assert assumptions.by_id("reveal_A").target["of"] == "K_as"
    assert properties.by_id("secret").values == ("K_as",)
    assert value_lifetime(pv, assumptions.by_id("reveal_A").target["of"]) == LONG_LIVED


def test_semantic_alignment_rewrites_uaf_roles_in_links_and_goal_parties():
    assumptions = lio.parse_assumptions({
        "vocab_version": VOCAB_VERSION, "world": [], "fixed": [
            {"id": "asm_auth", "axis": "channel",
             "target": {"link": ["ASM", "FIDO_Authenticator"]},
             "subtype": "secure"},
        ], "variable": [],
    })
    properties = lio.parse_properties({
        "vocab_version": VOCAB_VERSION, "properties": [
            {"id": "auth", "type": "Authentication",
             "subtype": "injective_agreement", "values": ["AAID"],
             "parties": {"asserter": "FIDO_Server",
                         "subject": "FIDO_Authenticator"}},
        ],
    })
    pv = """\
free channel_ASM_Authenticator: channel.
let processASM(ASM: host) =
  (* @ROLE ASM *)
  0.
let processServer(Server: host) =
  (* @ROLE Server *)
  0.
let processAuthenticator(Authenticator: host, AAID: bitstring) =
  (* @ROLE Authenticator *)
  0.
"""

    anchoring = anchor_names(assumptions, properties, pv)
    assert anchoring.value_aliases == {} and anchoring.entity_aliases == {}
    assert anchoring.missing == ["FIDO_Authenticator", "FIDO_Server"]
    missing = anchoring.missing

    semantic, contextual = validate_semantic_alignment({
        "mappings": [
            {"source": "FIDO_Authenticator", "target": "Authenticator",
             "evidence": "@ROLE Authenticator"},
            {"source": "FIDO_Server", "target": "Server",
             "evidence": "@ROLE Server"},
        ],
        "contextual": [],
    }, missing=missing, assumptions=assumptions, pv=pv)
    assert contextual == {}

    canonicalize_anchored_names(assumptions, properties,
                                entity_aliases=semantic)
    assert assumptions.by_id("asm_auth").target["link"] == ["ASM", "Authenticator"]
    assert properties.by_id("auth").parties == {
        "asserter": "Server", "subject": "Authenticator"}


def test_an_assumption_anchor_cannot_be_left_contextual():
    assumptions = lio.parse_assumptions({
        "vocab_version": VOCAB_VERSION, "world": [], "fixed": [
            {"id": "secure_link", "axis": "channel",
             "target": {"link": ["A", "RemotePeer"]},
             "subtype": "secure"},
        ], "variable": [],
    })
    pv = """\
let processA(A: host) = (* @ROLE A *) 0.
let processB(B: host) = (* @ROLE B *) 0.
let processC(C: host) = (* @ROLE C *) 0.
"""

    with pytest.raises(ValueError, match="need one concrete flow symbol"):
        validate_semantic_alignment({
            "mappings": [],
            "contextual": [{"source": "RemotePeer", "candidates": ["B", "C"],
                            "reason": "the declaration does not distinguish them"}],
        }, missing=["RemotePeer"], assumptions=assumptions, pv=pv)


def test_a_property_role_family_may_remain_contextual_for_inject():
    assumptions = lio.parse_assumptions({
        "vocab_version": VOCAB_VERSION, "world": [], "fixed": [], "variable": []})
    pv = """\
let processU(PSK: key) = (* @ROLE U *) let K_2_U = PSK in 0.
let processV(PSK: key) = (* @ROLE V *) let K_2_V = PSK in 0.
"""

    mappings, contextual = validate_semantic_alignment({
        "mappings": [],
        "contextual": [{"source": "K_2", "candidates": ["K_2_U", "K_2_V"],
                        "reason": "one binding per role"}],
    }, missing=["K_2"], assumptions=assumptions, pv=pv)

    assert mappings == {}
    assert contextual["K_2"]["candidates"] == ["K_2_U", "K_2_V"]


def test_a_value_bound_once_per_role_anchors_under_either_role_tag():
    """A document names one K_2 while the model gives each role its own
    binding, K_2_U and K_2_V. The role-tag level sees K_2 as bound where the
    whole-name and sub-token levels do not, and it must not alias: rewriting
    K_2 to K_2_U would name the initiator's copy in a goal the responder also
    holds."""
    assumptions = lio.parse_assumptions({
        "vocab_version": "2.2.0", "world": [], "fixed": [], "variable": [
            {"id": "reuse_K2", "axis": "key_reuse",
             "target": {"of": "K_2", "payload": "APP_2"},
             "subtypes": ["separated", "observed"]},
        ],
    })
    properties = lio.parse_properties({
        "vocab_version": "2.2.0", "properties": [
            {"id": "secret_k2", "type": "Secrecy", "subtype": "basic",
             "values": ["K_2"], "parties": {"holders": ["U", "V"]}},
        ],
    })
    pv = """\
let processU(PSK: key) =
  (* @ROLE U *)
  let K_2_U: key = HKDF(PSK) in
  0.

let processV(PSK: key) =
  (* @ROLE V *)
  let K_2_V: key = HKDF(PSK) in
  0.
"""

    anchoring = anchor_names(assumptions, properties, pv)

    assert anchoring.missing == []
    assert anchoring.value_aliases == {} and anchoring.entity_aliases == {}


def test_a_role_tag_does_not_conjure_a_value_the_model_never_binds():
    """The role-tag level is narrow: the model has to bind this exact name
    under a role's tag, not merely hold something that starts the same way."""
    properties = lio.parse_properties({
        "vocab_version": "2.2.0", "properties": [
            {"id": "secret_k9", "type": "Secrecy", "subtype": "basic",
             "values": ["K_9"], "parties": {"holders": ["U"]}},
        ],
    })
    empty = lio.parse_assumptions(
        {"vocab_version": "2.2.0", "world": [], "fixed": [], "variable": []})
    pv = """\
let processU(PSK: key) =
  (* @ROLE U *)
  let K_2_U: key = HKDF(PSK) in
  0.
"""

    assert anchor_names(empty, properties, pv)[0] == ["K_9"]


def test_a_sub_token_of_some_other_identifier_does_not_anchor_a_value():
    """``offer`` and ``mode`` appear only inside the longer identifiers
    ``checkOffer`` and ``tag_psk_mode``, which does not count as a binding.
    Reporting them absent is the useful answer: the unresolved names become
    the injector's hint."""
    properties = lio.parse_properties({
        "vocab_version": VOCAB_VERSION, "properties": [
            {"id": "handshake", "type": "Authentication",
             "subtype": "injective_agreement", "values": ["offer", "mode"],
             "parties": {"asserter": "Client", "subject": "Server"}},
        ],
    })
    empty = lio.parse_assumptions(
        {"vocab_version": VOCAB_VERSION, "world": [], "fixed": [], "variable": []})
    pv = """\
const tag_psk_mode: bitstring.
reduc forall t: bitstring, o: bitstring, s: bitstring;
  checkOffer(negotiate(t, o, s), t, o) = ok.

let processClient(offers: bitstring) =
  (* @ROLE Client *)
  0.

let processServer(Server: host) =
  (* @ROLE Server *)
  0.
"""

    assert anchor_names(empty, properties, pv)[0] == ["mode", "offer"]


def test_a_value_anchor_does_not_resolve_to_a_role_name():
    """``of = Client`` where the model has a role Client and binds the value
    as ``client_identity``. A role is not a value, so the name stays
    unresolved and reaches the alignment session."""
    assumptions = lio.parse_assumptions({
        "vocab_version": VOCAB_VERSION, "world": [], "fixed": [
            {"id": "data_client_public", "axis": "data",
             "target": {"of": "Client"}, "subtype": "disclosed"},
        ], "variable": [],
    })
    properties = lio.parse_properties({
        "vocab_version": VOCAB_VERSION, "properties": [
            {"id": "auth", "type": "Authentication",
             "subtype": "injective_agreement", "values": ["psk"],
             "parties": {"asserter": "Server", "subject": "Client"}},
        ],
    })
    pv = """\
free psk: bitstring [private].
let processClient(client_identity: bitstring) =
  (* @ROLE Client *)
  0.
let processServer(server_identity: bitstring) =
  (* @ROLE Server *)
  0.
"""

    anchoring = anchor_names(assumptions, properties, pv)

    assert "Client" in anchoring.missing_value
    assert anchoring.missing == ["Client"]
    assert anchoring.value_aliases == {} and anchoring.entity_aliases == {}


def test_a_value_mapping_does_not_rewrite_parties():
    """One spelling can sit in a value position and in parties; mapping the
    value leaves the principal name alone, or inject loses its role."""
    assumptions = lio.parse_assumptions({
        "vocab_version": VOCAB_VERSION, "world": [], "fixed": [
            {"id": "data_client_public", "axis": "data",
             "target": {"of": "Client"}, "subtype": "disclosed"},
        ], "variable": [],
    })
    properties = lio.parse_properties({
        "vocab_version": VOCAB_VERSION, "properties": [
            {"id": "auth", "type": "Authentication",
             "subtype": "injective_agreement", "values": ["psk"],
             "parties": {"asserter": "Server", "subject": "Client"}},
        ],
    })

    canonicalize_anchored_names(assumptions, properties,
                                value_aliases={"Client": "client_identity"})

    assert assumptions.by_id("data_client_public").target["of"] == "client_identity"
    assert properties.by_id("auth").parties == {
        "asserter": "Server", "subject": "Client"}


def test_unresolved_names_are_reported_with_the_declaration_that_wants_them():
    """A name the injector has to work out only means something next to the
    declaration referencing it, so the record carries the owner ids."""
    assumptions = lio.parse_assumptions({
        "vocab_version": VOCAB_VERSION, "world": [], "fixed": [], "variable": [
            {"id": "reveal_sk", "axis": "data", "target": {"of": "sk_Server"},
             "subtypes": ["none", "disclosed"]},
        ],
    })
    properties = lio.parse_properties({
        "vocab_version": VOCAB_VERSION, "properties": [
            {"id": "handshake", "type": "Authentication",
             "subtype": "injective_agreement", "values": ["ems", "sk_Server"],
             "parties": {"asserter": "Client", "subject": "Server"}},
        ],
    })

    owners = _anchor_owners(assumptions, properties)

    assert owners["ems"] == ["handshake"]
    assert owners["sk_Server"] == ["handshake", "reveal_sk"]


def _parsed(assum, scenarios, claim_rows):
    assumptions = lio.parse_assumptions(assum)
    claims = lio.parse_claims(
        {"vocab_version": "2.2.0", "scenarios": scenarios, "claims": claim_rows},
        assumptions)
    return assumptions, claims


# writing coverage

def test_a_covered_multi_writing_point_passes():
    assumptions, claims = _parsed(ASSUM,
        [{"name": "leaky", "conditions": [{"id": "kab_leak",
                                           "subtype": "disclosed"}]}],
        [{"property": "sec_na", "scenarios": ["leaky"]}])
    reject_writing_gaps(assumptions, claims, PV)   # no raise


def test_a_lifetime_selected_point_without_its_value_is_refused():
    """data.disclosed picks its writing off the target value's lifetime, so a
    point naming no value has no writing to pick. The gate states that gap
    before any session opens."""
    blank = {
        "vocab_version": "2.2.0", "world": [], "fixed": [],
        "variable": [{"id": "blank_leak", "axis": "data",
                      "subtypes": ["none", "disclosed"]}],
    }
    assumptions, claims = _parsed(blank,
        [{"name": "s", "conditions": [{"id": "blank_leak",
                                       "subtype": "disclosed"}]}],
        [{"property": "g", "scenarios": ["s"]}])
    with pytest.raises(NodeError, match="claims failed.*names no 'of'"):
        reject_writing_gaps(assumptions, claims, PV)


# degenerate leaks

def test_a_leak_of_the_claimed_secret_is_false_by_construction():
    assumptions, claims = _parsed(ASSUM,
        [{"name": "leaky", "conditions": [{"id": "kab_leak",
                                           "subtype": "disclosed"}]}],
        [{"property": "sec_kab", "scenarios": ["leaky"]}])
    properties = lio.parse_properties(PROPS)
    with pytest.raises(NodeError, match="false by construction"):
        reject_degenerate_leaks(assumptions, claims, properties)


def test_a_leak_of_a_different_value_passes():
    """One value handed over, another one's secrecy asked — the standard
    question, so the rule matches on the value, not on leak-plus-secrecy."""
    assumptions, claims = _parsed(ASSUM,
        [{"name": "leaky", "conditions": [{"id": "kab_leak",
                                           "subtype": "disclosed"}]}],
        [{"property": "sec_na", "scenarios": ["leaky"]}])
    properties = lio.parse_properties(PROPS)
    reject_degenerate_leaks(assumptions, claims, properties)   # no raise


def test_a_windowed_leak_of_the_claimed_secret_passes():
    """leaked_after_session restricts the read to outside the claim's own
    window, which is forward secrecy's shape rather than a contradiction."""
    assumptions, claims = _parsed(ASSUM,
        [{"name": "after", "conditions": [{"id": "kab_leak",
                                           "subtype": "leaked_after_correct_session"}]}],
        [{"property": "sec_kab", "scenarios": ["after"]}])
    properties = lio.parse_properties(PROPS)
    reject_degenerate_leaks(assumptions, claims, properties)   # no raise


# the windowed rungs' arena

def test_other_sessions_need_other_sessions_to_exist():
    """A per-session value's window is "other sessions", so under
    session_multiplicity = single_session there are no other copies to reveal
    and the gate refuses the scenario."""
    assumptions, claims = _parsed(ASSUM,
        [{"name": "others", "conditions": [{"id": "na_window",
                                            "subtype": "leaked_in_other_instances"}]}],
        [{"property": "sec_kab", "scenarios": ["others"]}])
    single, single_claims = _parsed({**ASSUM, "world": SINGLE_SESSION},
        [{"name": "others", "conditions": [{"id": "na_window",
                                            "subtype": "leaked_in_other_instances"}]}],
        [{"property": "sec_kab", "scenarios": ["others"]}])
    with pytest.raises(NodeError, match="no other copies"):
        reject_window_without_arena(single, single_claims)
    # sessions unbounded (the flow state, so no entry): the same point is fine
    reject_window_without_arena(assumptions, claims)


def test_lifetime_does_not_reject_a_restricted_leak_subtype():
    assumptions, claims = _parsed(ASSUM,
        [{"name": "owc_na", "conditions": [{"id": "na_window",
                                            "subtype": "leaked_after_correct_session"}]}],
        [{"property": "sec_kab", "scenarios": ["owc_na"]}])
    reject_writing_gaps(assumptions, claims, PV)


def test_correct_completion_on_a_long_lived_value_passes():
    assumptions, claims = _parsed(ASSUM,
        [{"name": "owc_kab", "conditions": [{"id": "kab_leak",
                                             "subtype": "leaked_after_correct_session"}]}],
        [{"property": "sec_na", "scenarios": ["owc_kab"]}])
    reject_writing_gaps(assumptions, claims, PV)   # no raise


# commitment conflicts: two points asserting opposite facts on one value.
# The instance key is `of` alone, so the fixed entry and the first variable
# dimension below are two answers about the same object even though their
# targets differ in the `phase` qualifier. ProVerif would accept
# `not attacker(kAS)` beside a leak of kAS by discarding every trace where the
# leak happens, and the verdict would then describe a world nobody asked about.
CONFLICT_ASSUM = {
    "vocab_version": "2.2.0",
    "world": [], "fixed": [
        {"id": "secure_kAS", "axis": "data",
         "target": {"of": "kAS"}, "subtype": "assumed_secure"},
    ],
    "variable": [
        # the same key, behind a phase boundary — a qualified target, one object
        {"id": "leak_kAS_at_S", "axis": "data",
         "target": {"of": "kAS", "phase": 1},
         "subtypes": ["none", "leaked_after_session"]},
        {"id": "leak_kBS", "axis": "data",
         "target": {"of": "kBS", "phase": 1},
         "subtypes": ["none", "leaked_after_session"]},
    ],
}
KNOWLEDGE = {"A": {"kAS"}, "S": {"kAS", "kBS"}}


def _conflict_claims(condition_id):
    return (
        [{"name": "s", "conditions": [{"id": condition_id,
                                       "subtype": "leaked_after_session"}]}],
        [{"property": "g", "scenarios": ["s"]}])


def test_two_answers_about_one_value_are_refused():
    """`assumed_secure` says the attacker never obtains kAS;
    `leaked_after_session` on the same value says it eventually does. The
    instance key is `of`, so those are two answers about one object whatever
    qualifiers the targets carry, and the gate refuses the scenario."""
    assumptions = lio.parse_assumptions(CONFLICT_ASSUM)
    scenarios, rows = _conflict_claims("leak_kAS_at_S")
    claims = lio.parse_claims(
        {"vocab_version": "2.2.0", "scenarios": scenarios, "claims": rows},
        assumptions)
    with pytest.raises(NodeError, match="answered twice|mutually exclusive"):
        reject_double_answers(assumptions, claims)


def test_a_fixed_assumption_may_name_a_value_it_will_create(tmp_path):
    """`key_reuse.observed` binds a fresh payload with `new` when applied,
    under the name its target gives, so that name is absent from the flow
    model and a property naming it anchors on the promise. Fixed only: a
    variable dimension's payload exists just in the scenarios assigning the
    reusing subtype, so a property naming it keeps its error."""
    pv = """\
let processV(V: host, skV: sskey) =
  (* @ROLE V *)
  0.
process
  new V: host;
  new skV: sskey;
  processV(V, skV)
"""
    props = {"vocab_version": "2.2.0", "properties": [
        {"id": "sec_payload", "type": "Secrecy", "subtype": "basic",
         "values": ["APP_2'"], "parties": {"holders": ["V"]}}]}

    def check(section):
        assumptions = lio.parse_assumptions({
            "vocab_version": "2.2.0", "world": [],
            "fixed": [], "variable": [], **section})
        return anchor_names(assumptions, lio.parse_properties(props), pv)[0]

    assert check({"fixed": [
        {"id": "reuse", "axis": "key_reuse",
         "target": {"of": "skV", "payload": "APP_2'"}, "subtype": "observed"}]}) == []
    assert check({"variable": [
        {"id": "reuse", "axis": "key_reuse",
         "target": {"of": "skV", "payload": "APP_2'"},
         "subtypes": ["separated", "observed"]}]}) == ["APP_2'"]


def test_a_leak_of_a_different_value_coexists():
    """'Server key still safe, the other key corrupt' is a legitimate
    scenario, so the rule keys on the object rather than the axis pair."""
    assumptions = lio.parse_assumptions(CONFLICT_ASSUM)
    scenarios, rows = _conflict_claims("leak_kBS")
    claims = lio.parse_claims(
        {"vocab_version": "2.2.0", "scenarios": scenarios, "claims": rows},
        assumptions)
    reject_double_answers(assumptions, claims)                    # no raise
    reject_commitment_conflicts(assumptions, claims, KNOWLEDGE)   # no raise


def test_no_realizer_declares_a_cross_axis_conflict():
    """The commitment-conflict gate is the backstop for two different axes
    that cannot both hold. The vocabulary declares none: same-axis
    contradictions are caught by 'one object, one answer', and the axes are
    orthogonal by construction (data holds, key_reuse uses; one key takes
    both at once). Adding a conflict means updating this test."""
    from orrery.nodes.apply.realizers import REALIZERS
    from orrery.nodes.apply.realizers.base import Realizer
    assert not [k for k, c in REALIZERS.items() if c.conflicts_with]
    assert not [k for k, c in REALIZERS.items()
                if c.conflict is not Realizer.conflict]
    leak = REALIZERS[("data", "disclosed")]()
    reuse = REALIZERS[("key_reuse", "observed")]()
    assert leak.conflict({"of": "kAS"}, reuse, {"of": "kAS"}, KNOWLEDGE) is None
