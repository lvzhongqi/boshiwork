"""extract_claims: which goals the document claims in which scenarios.

The assumption space, the goal vocabulary and the claims that pair them meet
here for the first time, so this is the only step that can check the three
against each other.

Artifacts: claims.json, plus validated copies of assumptions.json and
properties.json whose model names have been canonicalised. build_world,
build_root and scenarios all read this directory.

The closure rules (no dangling dimension ids, conditions assign only variable
dimensions, no writing-coverage hole, no degenerate leak-vs-secrecy pairing,
windowed rungs have their arena, goal references resolve) are the extraction
session's acceptance test and come back as a repair round. Anchoring —
resolving each declaration name to this run's flow spelling — runs before the
session and never blocks: those names come from the other two artifacts, which
this session cannot rewrite.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

from orrery.modules.libschema.io import (
    parse_assumptions, parse_claims, parse_properties,
)
from orrery.modules.libschema.validate import (
    validate_assumptions, validate_claims, validate_properties,
)
from orrery.modules.pvtext.parse import blank_comments
from orrery.modules.pvtext.roles import model_roles
from orrery.nodes.apply.order import fixed_points
from orrery.nodes.apply.realizers import (
    REALIZERS, VOCAB, check_writing_coverage, subtype_is_noop,
)
from orrery.nodes.inject.injectors import PROP_VOCAB
from orrery.agent.compose import localized, render_prompt, render_system, resume_user
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.agent.tools import claims_tools
from orrery.agent.tools.context import ToolContext
from orrery.infra.llm.client import Effort
from orrery.modules.document.corpus import inline_analysis_corpus
from orrery.version import VOCAB_VERSION
from orrery.nodes.base import GapRaised, Node, NodeError, RunEnv
from orrery.nodes.claims.load import load_claim_input
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter
from orrery.services.events import NodeProgress
from orrery.services.store.atomic import write_json, write_text


def _upstream(env: RunEnv, node: str, filename: str) -> dict:
    """One of the two vocabularies, as its extraction node left it."""
    p = env.layout.node_dir(node) / filename
    if not p.is_file():
        raise NodeError(
            f"claims failed: {node} did not write {filename}; the vocabularies "
            f"reach this gate as upstream artifacts, not as arguments")
    return json.loads(p.read_text(encoding="utf-8"))


# Target fields that anchor to the model text, split by what they must denote.
# A value position resolves to something the model binds as a value (for
# admission scopes, the spelling its @orrery-idiom markers carry), so a role is
# never a referent there; an entity position names principals, where a role is.
# "family" and "payload" need not exist in the flow model, so they are not
# searched here; validate_assumptions and the realizer sessions check them.
_VALUE_ANCHOR_KEYS = {"value", "of", "scope"}
_ENTITY_ANCHOR_KEYS = {"link"}
_ANCHOR_KEYS = _VALUE_ANCHOR_KEYS | _ENTITY_ANCHOR_KEYS

#: The data rungs that hand the attacker the value itself, from the start.
_FULL_READ = {"chosen", "disclosed"}
#: The per-session data rung that presupposes other session instances.
_OTHER_INSTANCES = "leaked_in_other_instances"


def _scenario_worlds(assumptions, claims):
    """(label, points) for the fixed section and each scenario's full point set,
    the shape the pairwise checks iterate over."""
    fixed = list(fixed_points(assumptions))
    worlds = [("the fixed section", fixed)]
    worlds += [(f"scenario {ns.name!r}", fixed + list(ns.conditions))
               for ns in claims.scenarios]
    return worlds


def reject_double_answers(assumptions, claims) -> None:
    """In each scenario's world, one axis answers once per object.

    validate_assumptions holds the declarations to this, but a scenario is
    fixed ∪ conditions, so two individually fine entries can collide here. The
    subtypes are mutually exclusive answers about one object, so a world holding
    two of them is ill-defined rather than merely hard. Raises NodeError."""
    for label, pts in _scenario_worlds(assumptions, claims):
        seen: dict[tuple[str, object], str] = {}
        for p in pts:
            inst = VOCAB.instance_of(p.axis, p.target)
            if inst is None and VOCAB.instance_key(p.axis) is not None:
                continue
            key = (p.axis, tuple(inst) if isinstance(inst, list) else inst)
            if key in seen:
                what = (f"the object {inst!r}" if inst is not None
                        else "this protocol (a global axis)")
                raise NodeError(
                    f"claims failed: {label} answers axis {p.axis!r} twice for "
                    f"{what} — {seen[key]!r} and {p.ref_id or p.axis}. The "
                    f"subtypes of one axis are mutually exclusive, so no world "
                    f"holds both; drop one of them from this scenario.")
            seen[key] = p.ref_id or p.axis


def reject_writing_gaps(assumptions, claims, pv) -> None:
    """Every mechanically selected multi-writing point needs an encoding for the
    target value's lifetime. Lifetime selects syntax only; it does not constrain
    which subtype a claim may name. Run at the gate so a missing encoding shows
    up before an apply session opens. Raises NodeError."""
    pts = list(fixed_points(assumptions))
    pts += [c for ns in claims.scenarios for c in ns.conditions]
    try:
        check_writing_coverage(pts, pv)
    except (ValueError, KeyError) as e:
        raise NodeError(f"claims failed: {e}") from None


def reject_degenerate_leaks(assumptions, claims, properties) -> None:
    """Refuse a scenario that hands the attacker a value outright (data
    chosen/disclosed) while a claim there asserts that value's secrecy: the
    verdict is false by construction and measures nothing. Raises NodeError so
    the extraction session restates either the condition or the claim."""
    goals = {g.id: g for g in properties.properties}
    scen_claims: dict[str, list] = {}
    for c in claims.claims:
        for s in c.scenarios:
            scen_claims.setdefault(s, []).append(c.property)
    for ns in claims.scenarios:
        leaked = {(c.target or {}).get("of")
                  for c in list(ns.conditions)
                  if c.axis == "data" and c.subtype in _FULL_READ}
        leaked |= {(f.target or {}).get("of")
                   for f in fixed_points(assumptions)
                   if f.axis == "data" and f.subtype in _FULL_READ}
        leaked.discard(None)
        if not leaked:
            continue
        for pid in scen_claims.get(ns.name, ()):
            g = goals.get(pid)
            if g is None or g.type != "Secrecy":
                continue
            hit = sorted(leaked & set(g.values))
            if hit:
                raise NodeError(
                    f"claims failed: scenario {ns.name!r} grants the attacker "
                    f"{hit} outright (data.disclosed/chosen) while claim "
                    f"{pid!r} asserts its secrecy there — false by "
                    f"construction. State the leak on a different value, "
                    f"restrict it to outside the window, or drop the claim "
                    f"from this scenario.")


def reject_window_without_arena(assumptions, claims) -> None:
    """The other-instances data rung needs other sessions to exist, so it
    requires session_multiplicity = unbounded_sessions. Only that arena
    precondition is checked; value lifetime is not a subtype-admission rule. The
    world comes from the assumptions document's world section, where an axis
    nobody states takes its flow state. Raises NodeError."""
    single = any(w.axis == "session_multiplicity"
                 and w.subtype == "single_session"
                 for w in assumptions.world)
    pts = list(fixed_points(assumptions))
    pts += [c for ns in claims.scenarios for c in ns.conditions]
    for p in pts:
        if p.axis != "data" or p.subtype != _OTHER_INSTANCES:
            continue
        of = (p.target or {}).get("of")
        if not of:
            continue
        if single:
            raise NodeError(
                f"claims failed: {p.ref_id or p.axis} reveals the other "
                f"sessions' copies of {of!r}, but this world declares "
                f"session_multiplicity = single_session — with one session "
                f"there are no other copies to reveal. Fix the condition, or "
                f"drop the world entry.")


def reject_commitment_conflicts(assumptions, claims, knowledge) -> None:
    """Refuse a world whose points make opposite commitments about one value,
    such as a leak of a party's whole knowledge against a never-obtained axiom
    on a value inside it. Concrete cross-target conflicts belong to realizers;
    this only pairs each world's points, asks both directions, and raises
    NodeError on the first reason. ``knowledge`` is an empty context: holder
    semantics live in the flow model, so nothing can be projected yet."""
    for label, pts in _scenario_worlds(assumptions, claims):
        for i, p in enumerate(pts):
            rp = REALIZERS[(p.axis, p.subtype)]()
            for q in pts[i + 1:]:
                rq = REALIZERS[(q.axis, q.subtype)]()
                reason = (rp.conflict(p.target, rq, q.target, knowledge)
                          or rq.conflict(q.target, rp, p.target, knowledge))
                if reason:
                    raise NodeError(
                        f"claims failed: {label} pairs "
                        f"{p.ref_id or rp.id} with {q.ref_id or rq.id}, and "
                        f"they cannot hold together — {reason}. Adjust one of "
                        f"them (demote the axiom to a variable dimension, or "
                        f"drop the condition).")


def _introduced_names(assumptions) -> set[str]:
    """Names a fixed assumption will create in the model when it is applied.

    Only ``payload`` so far: key_reuse's reusing subtypes bind a fresh value
    with ``new`` and re-run the key's existing use over it. That name is absent
    from the flow model by construction, since a flow already carrying the
    second use would have the assumption baked into the baseline. Fixed only —
    a variable dimension's payload exists in some scenarios and not others, so
    a property naming it is a real defect and keeps its error.
    """
    out: set[str] = set()
    for a in assumptions.fixed:
        payload = (a.target or {}).get("payload")
        if isinstance(payload, str):
            out.add(payload)
    return out


#: The model's own structured comments, which count as part of the model: an
#: ``@orrery-idiom`` line declares an identity scope and is often the only place
#: the scope name appears. The rest of ``(* *)`` is prose.
_MARKER_COMMENT = re.compile(r"\(\*\s*@orrery-[^\n]*?\*\)")


def _model_code(pv: str) -> str:
    """The model with prose blanked and its own ``@orrery-`` markers standing.

    Offsets are unchanged, so the result is interchangeable with the source for
    matching. A name occurring only in prose is anchored to nothing, and
    counting it as resolved sends the injector a goal with no hint while the
    model binds several candidates.
    """
    code = list(blank_comments(pv))
    for m in _MARKER_COMMENT.finditer(pv):
        code[m.start():m.end()] = pv[m.start():m.end()]
    return "".join(code)


def _anchor_names(assumptions, properties) -> tuple[set[str], set[str]]:
    """The model names the claims reference, as ``(value_names, entity_names)``.

    Value positions (a target's value keys, a property's ``values``) denote
    something the model binds as a value; entity positions (a target's entity
    keys, a property's ``parties``) name principals. Both sides subtract the
    names a fixed assumption introduces, which are absent until apply runs.
    """
    value_names: set[str] = set()
    entity_names: set[str] = set()
    for a in assumptions.entries():
        for k, v in (a.target or {}).items():
            if k not in _ANCHOR_KEYS:
                continue
            bucket = value_names if k in _VALUE_ANCHOR_KEYS else entity_names
            if isinstance(v, str):
                bucket.add(v)
            elif isinstance(v, (list, tuple)):
                bucket.update(x for x in v if isinstance(x, str))
    for g in properties.properties:
        value_names.update(_string_leaves(g.values))
        entity_names.update(_string_leaves(g.parties))
    introduced = _introduced_names(assumptions)
    return value_names - introduced, entity_names - introduced


def _anchor_owners(assumptions, properties) -> dict[str, list[str]]:
    """Which declaration each anchoring name came from — ``{name: [ids]}``.

    The same walk as ``_anchor_names``, keyed by owner instead of by position:
    a name the injector has to work out is only meaningful next to the goal
    that references it.
    """
    owners: dict[str, set[str]] = {}
    introduced = _introduced_names(assumptions)

    def add(name, owner: str) -> None:
        if isinstance(name, str) and name not in introduced:
            owners.setdefault(name, set()).add(owner)

    for a in assumptions.entries():
        for k, v in (a.target or {}).items():
            if k not in _ANCHOR_KEYS:
                continue
            if isinstance(v, str):
                add(v, a.id)
            elif isinstance(v, (list, tuple)):
                for x in v:
                    add(x, a.id)
    for g in properties.properties:
        for v in _string_leaves(g.values):
            add(v, g.id)
        for v in _string_leaves(g.parties):
            add(v, g.id)
    return {k: sorted(v) for k, v in owners.items()}


def _string_leaves(value) -> set[str]:
    """String leaves of one model-reference value, preserving no JSON shape."""
    if isinstance(value, dict):
        return set().union(*(_string_leaves(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_string_leaves(v) for v in value)) if value else set()
    return {value} if isinstance(value, str) else set()


def _assumption_anchor_names(assumptions) -> set[str]:
    """Anchors an apply realizer must receive as one concrete model symbol."""
    names: set[str] = set()
    for a in assumptions.entries():
        for key, value in (a.target or {}).items():
            if key in _ANCHOR_KEYS:
                names.update(_string_leaves(value))
    return names - _introduced_names(assumptions)


def _say(env: RunEnv, node: str, text: str) -> None:
    """One progress line on the ledger, dropped when the run has no bus."""
    if env.bus is not None:
        env.bus.emit(NodeProgress(run=env.layout.run_name, node=node, text=text))


# ────────────────────────────────────────────────────────────────────────────
# Anchoring, run before the session
# ────────────────────────────────────────────────────────────────────────────

class Anchoring(NamedTuple):
    """anchor_names' result. ``missing`` is the flat sorted list the alignment
    session receives; the per-position splits keep a resolution from crossing
    positions, so a value mapping never rewrites a ``parties`` entry."""
    missing: list
    missing_value: frozenset
    missing_entity: frozenset
    value_aliases: dict
    entity_aliases: dict


def anchor_names(assumptions, properties, pv: str) -> Anchoring:
    """Resolve declaration names to the spelling the flow model uses.

    Matching runs over the model's code with prose blanked and its ``@orrery-``
    markers kept, at three levels: an exact word-boundary match; a normalised
    whole name (underscores stripped, case-insensitive, absorbing K_ab vs Kab),
    the only level that yields an alias; and a role-tagged binding — one
    document ``K_2`` bound as ``K_2_U`` and ``K_2_V`` — which shows presence
    but names no single value to substitute, so the realizer and injector
    sessions pick the binding their role needs. A name occurring only as a
    sub-token of a larger identifier does not anchor.

    Positions differ: an entity position may resolve to a role, a value
    position may not, so a value anchor matching only a role goes unresolved to
    the alignment session. Aliases such as ``{"Kas": "K_as"}`` must be applied
    by the caller before the downstream gates run, or later model readers
    cannot find the value.
    """
    # Roles are read from `@ROLE` markers, so model_roles takes the raw text;
    # every match below runs over the blanked code instead (see _model_code).
    code = _model_code(pv)
    all_idents = set(re.findall(r"[A-Za-z_][A-Za-z0-9_']*", code))
    idents: dict[str, set[str]] = {}
    for tok in all_idents:
        idents.setdefault(tok.replace("_", "").lower(), set()).add(tok)
    roles = model_roles(pv)
    role_idents: dict[str, set[str]] = {}
    for role in roles:
        role_idents.setdefault(role.replace("_", "").lower(), set()).add(role)
    tags = {r.lower() for r in roles}

    def resolve(n: str, *, entity: bool) -> str | None:
        """The model spelling for ``n`` (``n`` itself when spelled as written),
        or None when the model gives it no unambiguous referent."""
        if re.search(rf"\b{re.escape(n)}\b", code):
            return n
        key = n.replace("_", "").lower()
        if entity:
            role_hits = role_idents.get(key, set())
            if len(role_hits) == 1:
                return next(iter(role_hits))
            if role_hits:
                return None
        whole_hits = idents.get(key, set())
        if len(whole_hits) == 1:
            return next(iter(whole_hits))
        # A whole-name collision gives no unambiguous referent, so it counts
        # the same as an absent name.
        if whole_hits:
            return None
        if any(key + t in idents or t + key in idents for t in tags):
            return n
        return None

    value_names, entity_names = _anchor_names(assumptions, properties)
    missing_value: set[str] = set()
    missing_entity: set[str] = set()
    value_aliases: dict[str, str] = {}
    entity_aliases: dict[str, str] = {}
    for n in sorted(value_names):
        spelling = resolve(n, entity=False)
        if spelling is None:
            missing_value.add(n)
        elif spelling != n:
            value_aliases[n] = spelling
    for n in sorted(entity_names):
        spelling = resolve(n, entity=True)
        if spelling is None:
            missing_entity.add(n)
        elif spelling != n:
            entity_aliases[n] = spelling
    return Anchoring(sorted(missing_value | missing_entity),
                     frozenset(missing_value), frozenset(missing_entity),
                     value_aliases, entity_aliases)


def canonicalize_anchored_names(assumptions, properties, *,
                                value_aliases: dict[str, str] | None = None,
                                entity_aliases: dict[str, str] | None = None) -> None:
    """Rewrite model-anchored fields in place to their flow-model spellings.

    Each alias map reaches only its own positions — value aliases a target's
    value keys and a goal's ``values``, entity aliases a target's entity keys
    and a goal's ``parties`` — so a name used in both is mapped where it denotes
    the value and kept where it names the principal. Only this node's private
    parsed copies are touched; ids and free text are not model identifiers and
    stay as they are.
    """
    value_aliases = value_aliases or {}
    entity_aliases = entity_aliases or {}
    if not value_aliases and not entity_aliases:
        return

    def rewrite(value, aliases):
        if isinstance(value, str):
            return aliases.get(value, value)
        if isinstance(value, dict):
            return {key: rewrite(item, aliases) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item, aliases) for item in value]
        if isinstance(value, tuple):
            return tuple(rewrite(item, aliases) for item in value)
        return value

    for assumption in assumptions.entries():
        if not isinstance(assumption.target, dict):
            continue
        assumption.target = {
            key: (rewrite(value, value_aliases) if key in _VALUE_ANCHOR_KEYS
                  else rewrite(value, entity_aliases)
                  if key in _ENTITY_ANCHOR_KEYS else value)
            for key, value in assumption.target.items()
        }
    for goal in properties.properties:
        goal.values = tuple(rewrite(value, value_aliases)
                            for value in goal.values)
        goal.parties = rewrite(goal.parties, entity_aliases)


_ALIGN_ROW = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "description": "the unresolved declaration spelling"},
        "target": {"type": "string", "description": "one exact identifier present in the flow model"},
        "evidence": {"type": "string", "description": "a short flow-model quote or binding that proves the correspondence"},
    },
    "required": ["source", "target", "evidence"],
    "additionalProperties": False,
}
_CONTEXT_ROW = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "description": "the unresolved declaration spelling"},
        "candidates": {
            "type": "array", "items": {"type": "string"},
            "description": "exact flow identifiers involved, possibly empty when the value is embedded in a term",
        },
        "reason": {"type": "string", "description": "why there is no single safe alpha-renaming"},
    },
    "required": ["source", "candidates", "reason"],
    "additionalProperties": False,
}
_ALIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "mappings": {"type": "array", "items": _ALIGN_ROW},
        "contextual": {"type": "array", "items": _CONTEXT_ROW},
    },
    "required": ["mappings", "contextual"],
    "additionalProperties": False,
}


def build_alignment_prompt(*, pv: str, unresolved: dict[str, list[str]],
                           assumptions_json: str, properties_json: str,
                           lang: str = "en") -> Prompt:
    """One low-effort alpha-renaming pass over this run's own declarations."""
    return Prompt(
        system=render_system(__file__, localized("alignment.sys.md", lang),
                             cut_after=["flow_model"], flow_pv=pv),
        user=render_prompt(
            __file__, localized("alignment.user.md", lang),
            unresolved_json=json.dumps(unresolved, ensure_ascii=False, indent=2),
            assumptions_json=assumptions_json,
            properties_json=properties_json),
        tools=tuple(claims_tools(GAP_TARGETS)),
        submit=SubmitSpec(kind="tool", schema=_ALIGN_SCHEMA),
        label="extract_claims_symbol_alignment",
    )


def validate_semantic_alignment(submission: dict, *, missing: list[str],
                                assumptions, pv: str
                                ) -> tuple[dict[str, str], dict[str, dict]]:
    """Validate a complete, one-to-one alignment against this flow's code.

    Returns ``(mappings, contextual)``; raises ValueError on an unknown source,
    a target absent from the model, a name answered twice or not at all. A
    property-only name may stay contextual, since the injector reads the whole
    model and can resolve a role family or tuple component; an assumption
    target may not, since apply realizers run first and need one symbol.
    """
    wanted = set(missing)
    code_idents = set(re.findall(r"[A-Za-z_][A-Za-z0-9_']*", _model_code(pv)))
    mappings: dict[str, str] = {}
    reverse: dict[str, str] = {}
    contextual: dict[str, dict] = {}

    for i, row in enumerate(submission.get("mappings", [])):
        source, target = row.get("source"), row.get("target")
        if source not in wanted:
            raise ValueError(f"mappings[{i}] names unknown unresolved source {source!r}")
        if target not in code_idents:
            raise ValueError(f"mappings[{i}] target {target!r} is not an identifier in the flow model")
        if source in mappings or source in contextual:
            raise ValueError(f"unresolved source {source!r} is answered more than once")
        if target in reverse:
            raise ValueError(
                f"flow symbol {target!r} is mapped from both {reverse[target]!r} and {source!r}")
        mappings[source] = target
        reverse[target] = source

    for i, row in enumerate(submission.get("contextual", [])):
        source = row.get("source")
        if source not in wanted:
            raise ValueError(f"contextual[{i}] names unknown unresolved source {source!r}")
        if source in mappings or source in contextual:
            raise ValueError(f"unresolved source {source!r} is answered more than once")
        candidates = row.get("candidates", [])
        unknown = [c for c in candidates if c not in code_idents]
        if unknown:
            raise ValueError(
                f"contextual[{i}] names identifiers absent from the flow model: {unknown}")
        contextual[source] = {
            "candidates": list(candidates), "reason": str(row.get("reason", ""))}

    unanswered = sorted(wanted - set(mappings) - set(contextual))
    if unanswered:
        raise ValueError(f"the alignment did not answer unresolved names {unanswered}")
    hard = sorted(set(contextual) & _assumption_anchor_names(assumptions))
    if hard:
        raise ValueError(
            f"assumption anchors need one concrete flow symbol and cannot remain contextual: {hard}")
    return mappings, contextual


# ────────────────────────────────────────────────────────────────────────────
# The session
# ────────────────────────────────────────────────────────────────────────────

#: What this step may report a gap against. Each reverse edge points at an
#: upstream artifact whose shape turned out to be wrong for the claim being
#: written: a dimension too coarse for the distinction the document draws, a
#: goal whose required assumption was never declared, a stated condition the
#: assumption space has no axis for. tests/contracts holds this list.
GAP_TARGETS = ("extract_flow", "extract_assumptions", "extract_properties")

_SCHEMA = {
    "type": "object",
    "properties": {
        "scenarios": {
            "type": "array", "minItems": 1,
            "description": "the worlds this run asks about; one with no conditions is the document's own world",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "lower_snake_case, unique; say what is different about it, e.g. data_ck_leaked_after_session"},
                    "conditions": {
                        "type": "array",
                        "description": "which variable dimension takes which value here; empty means the flow state throughout",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "a variable dimension's id, exactly as assumptions.json spells it"},
                                "subtype": {"type": "string", "description": "one of that dimension's declared subtypes"},
                            },
                            "required": ["id", "subtype"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "conditions"],
                "additionalProperties": False,
            },
        },
        "claims": {
            "type": "array", "minItems": 1,
            "description": "which goal the document claims in which scenarios",
            "items": {
                "type": "object",
                "properties": {
                    "property": {"type": "string", "description": "a goal id, exactly as properties.json spells it"},
                    "scenarios": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "string"},
                        "description": "scenario names from the list above",
                    },
                },
                "required": ["property", "scenarios"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scenarios", "claims"],
    "additionalProperties": False,
}


def coupling_reference() -> str:
    """The goal subtypes that must be claimed together with an assumption, as
    prompt lines. Rendered from the injector registry, so the prompt cannot
    drift from the gate that enforces it."""
    out: list[str] = []
    for gtype in PROP_VOCAB.types():
        for st in PROP_VOCAB.subtypes_of(gtype):
            if PROP_VOCAB.is_stub(gtype, st):
                continue
            need = PROP_VOCAB.requires_assumption(gtype, st)
            if need:
                subs = ", ".join(need["subtypes"])
                out.append(f"- {gtype}.{st}: axis {need['axis']}, "
                           f"one of [{subs}]")
    return "\n".join(out)


def build_prompt(*, corpus: str, protocol: str, assumptions_json: str = "{}",
                 properties_json: str = "{}", flow_pv: str = "",
                 step_messages: str = "", lang: str = "en") -> Prompt:
    """This node's one request. No I/O and no LLM, so the prompt preview can
    call it to render exactly what a run sends."""
    return Prompt(
        system=render_system(__file__, localized("main.sys.md", lang),
                             cut_after=["document"], document=corpus,
                             couplings=coupling_reference()),
        user=render_prompt(__file__, localized("main.user.md", lang),
                           protocol=protocol, assumptions_json=assumptions_json,
                           properties_json=properties_json,
                           flow_pv=flow_pv,
                           step_messages=step_messages),
        tools=tuple(claims_tools(GAP_TARGETS)),
        submit=SubmitSpec(kind="tool", schema=_SCHEMA),
        label="extract_claims",
    )


class ExtractClaimsNode(Node):
    name = "extract_claims"
    short = "claims"
    task = (
        "Read which goals the document claims under which conditions, and gate "
        "the three declarations against each other and against the flow model")
    model_driven = True
    gap_targets = GAP_TARGETS
    depends_on = ("extract_flow", "extract_assumptions", "extract_properties")
    # The judgement is which sentences of the document are claims rather than
    # description, and which declared dimension each one is conditioned on. A
    # wrong condition moves a goal into the wrong world, and the verdict is
    # then an answer to a question nobody asked.
    effort = Effort.HIGH

    def is_done(self, env: RunEnv) -> bool:
        return all(env.layout.has(self.name, f)
                   for f in ("assumptions.json", "properties.json", "claims.json"))

    async def run(self, env: RunEnv) -> None:
        if env.doc_set is None:
            raise NodeError(f"{self.name} failed: no document set upstream")
        out = env.layout.node_dir(self.name)

        # ── the two vocabularies, as their own steps left them ───────────────
        assumptions = validate_assumptions(
            parse_assumptions(
                _upstream(env, "extract_assumptions", "assumptions.json"),
                where="assumptions"), VOCAB)
        properties = validate_properties(
            parse_properties(
                _upstream(env, "extract_properties", "properties.json"),
                where="properties"), PROP_VOCAB)

        flow_pv = env.layout.flow_pv
        if not flow_pv.exists():
            raise NodeError(f"{self.name} failed: the upstream flow model does not exist")
        pv = flow_pv.read_text(encoding="utf-8")

        # Holder semantics belong to the generated flow, and no realizer
        # declares a cross-target conflict needing such a projection, so the
        # conflict check gets an empty context.
        knowledge = {}

        # ── anchoring, before any model call ─────────────────────────────────
        # Anchoring is about the other two artifacts' names, which neither this
        # session nor a repair round can rewrite, so it runs outside the
        # extraction session where the only outcomes are "fine" and "stop".
        anchoring = anchor_names(assumptions, properties, pv)
        mechanical = {**anchoring.entity_aliases, **anchoring.value_aliases}
        if anchoring.value_aliases or anchoring.entity_aliases:
            canonicalize_anchored_names(
                assumptions, properties,
                value_aliases=anchoring.value_aliases,
                entity_aliases=anchoring.entity_aliases)
            _say(env, self.name,
                 "naming drift between the declarations and the flow model, "
                 "canonicalised: "
                 + "; ".join(f"{old} → {new}"
                             for old, new in sorted(mechanical.items())))
        owners = _anchor_owners(assumptions, properties)
        semantic: dict[str, str] = {}
        contextual: dict[str, dict] = {}
        if anchoring.missing:
            semantic, contextual = await self._align_names(
                env, out, assumptions, properties, pv, anchoring.missing,
                owners)
            if semantic:
                canonicalize_anchored_names(
                    assumptions, properties,
                    value_aliases={n: s for n, s in semantic.items()
                                   if n in anchoring.missing_value},
                    entity_aliases={n: s for n, s in semantic.items()
                                    if n in anchoring.missing_entity})
                _say(env, self.name,
                     "semantic naming drift between the declarations and the "
                     "flow model, canonicalised: "
                     + "; ".join(f"{old} → {new}"
                                  for old, new in semantic.items()))

        # A property-only name may legitimately have no single model symbol —
        # one document value split by role, or carried inside a tuple — and
        # travels on as an injector hint. Assumption targets cannot, since
        # apply realizers run before inject and need a concrete object.
        write_json(out / "anchoring.json",
                   {"normalised": mechanical,
                    "semantic": semantic,
                    "contextual": contextual,
                    "unresolved": {n: owners.get(n, []) for n in contextual}})
        if contextual:
            _say(env, self.name,
                 f"{len(contextual)} declaration name(s) have no single safe "
                 f"alpha-renaming and were passed to inject as contextual "
                 f"hints: {sorted(contextual)}")

        # ── the claims themselves: supplied, or read from the document ───────
        if env.claims_input is not None:
            claims = self._gate(
                load_claim_input(env.claims_input, "claims", self.name),
                assumptions, properties, env, knowledge, pv)
            _say(env, self.name,
                 "claims.json was supplied, so nothing was read from the document")
        else:
            claims = await self._extract(env, assumptions, properties, pv,
                                         out, knowledge)

        write_json(out / "assumptions.json", assumptions.to_json())
        write_json(out / "properties.json", properties.to_json())
        write_json(out / "claims.json", claims.to_json())

    async def _align_names(self, env: RunEnv, out, assumptions, properties,
                           pv: str, missing: list[str], owners: dict[str, list[str]]
                           ) -> tuple[dict[str, str], dict[str, dict]]:
        """Resolve the names regex cannot settle, using only this run's model.

        Ground-truth alignment is not an input: the standard declarations speak
        in document terms, and this session translates them into the
        alpha-renaming the freshly generated flow chose. Returns
        ``(mappings, contextual)``; raises GapRaised or NodeError.
        """
        prompt = build_alignment_prompt(
            pv=pv,
            unresolved={name: owners.get(name, []) for name in missing},
            assumptions_json=json.dumps(assumptions.to_json(),
                                        ensure_ascii=False, indent=2),
            properties_json=json.dumps(properties.to_json(),
                                       ensure_ascii=False, indent=2),
            lang=env.config.get("prompt_lang", "en"),
        )
        home = out / "alignment"
        home.mkdir(parents=True, exist_ok=True)
        transcript = home / "transcript.jsonl"
        resume = resume_messages(transcript)
        writer = TranscriptWriter(transcript)
        if resume is None:
            writer.meta(node=self.name, step="symbol_alignment",
                        model=env.config["llm"].get("model", "?"),
                        effort=Effort.LOW)
            user = prompt.user
        else:
            user = resume_user(prompt.submit)

        ctx = ToolContext(
            node=self.name, doc_set=env.doc_set,
            artifacts_root=env.layout.run_dir,
            upstream_nodes=env.upstream(self.name),
            tool_return_chars=env.config["agent"]["tool_return_chars"],
        )
        box: dict = {}

        async def _accept(submission, _fences):
            try:
                box["answer"] = validate_semantic_alignment(
                    submission, missing=missing, assumptions=assumptions, pv=pv)
                return []
            except ValueError as exc:
                return [f"the symbol alignment is invalid: {exc}"]

        result = await run_agent(
            env.llm(), system=prompt.system, user=user,
            tools=list(prompt.tools), ctx=ctx, submit=prompt.submit,
            accept=_accept, budget=env.budget(), writer=writer,
            resume_from=resume, effort=Effort.LOW,
            # The unit is the session's directory under the step, which is
            # how the console finds its transcript.
            emitter=env.emitter(self.name, unit=home.name),
        )
        if result.status == "gap":
            raise GapRaised(result.gap, transcript, result.gap_tool_call_id)
        if result.status != "ok":
            raise NodeError(
                f"{self.name} symbol alignment: {result.status}: {result.failure}")
        return box["answer"]

    def _gate(self, data: dict, assumptions, properties, env: RunEnv,
              knowledge: dict, pv: str):
        """The cross-artifact gate: parse the claims against the assumption
        space, then run the closure rules. Raises on the supplied path, where a
        hand-written file is a configuration error rather than something to
        retry; ``_extract`` catches the same exceptions and turns them into a
        repair round, since there the session can rewrite the answer."""
        claims = parse_claims(data, assumptions, where="claims")
        reject_double_answers(assumptions, claims)
        reject_writing_gaps(assumptions, claims, pv)
        reject_degenerate_leaks(assumptions, claims, properties)
        reject_window_without_arena(assumptions, claims)
        reject_commitment_conflicts(assumptions, claims, knowledge)
        # The vocabularies and the noop predicate are realizer/injector
        # knowledge, passed in as parameters so libschema never imports upward.
        unclaimed = validate_claims(claims, assumptions, properties,
                                    is_noop=subtype_is_noop, vocab=VOCAB,
                                    prop_vocab=PROP_VOCAB)
        if unclaimed:
            _say(env, self.name,
                 f"{len(unclaimed)} vocabulary goals are not named by the claims "
                 f"and will not run: {unclaimed}")
        return claims

    async def _extract(self, env: RunEnv, assumptions, properties, pv: str,
                       out, knowledge: dict):
        prompt = build_prompt(
            corpus=inline_analysis_corpus(
                env.doc_set, env.config["document"]["inline_max_chars"]),
            protocol=env.protocol_id,
            assumptions_json=json.dumps(assumptions.to_json(),
                                        ensure_ascii=False, indent=2),
            properties_json=json.dumps(properties.to_json(),
                                       ensure_ascii=False, indent=2),
            flow_pv=pv,
            step_messages=env.facts(self.name),
            lang=env.config.get("prompt_lang", "en"),
        )
        submit = prompt.submit
        transcript = env.layout.node_transcript(self.name)
        resume = resume_messages(transcript)
        writer = TranscriptWriter(transcript)
        if resume is None:
            writer.meta(node=self.name,
                        model=env.config["llm"].get("model", "?"),
                        effort=self.effort)
            user = prompt.user
        else:
            user = resume_user(submit)

        ctx = ToolContext(
            node=self.name, doc_set=env.doc_set,
            artifacts_root=env.layout.run_dir,
            upstream_nodes=env.upstream(self.name),
            tool_return_chars=env.config["agent"]["tool_return_chars"],
        )

        box: dict = {}

        async def _accept(s, fences):
            # The gate is the acceptance test. Everything it raises — a
            # degenerate leak-vs-secrecy pairing, a dangling dimension id, a
            # goal whose required assumption is not in the claim — the session
            # can fix by rewriting claims.json, so it comes back as a repair
            # round instead of ending the run. Anchoring, the one check
            # deletion would satisfy, already ran before this session opened.
            problems = []
            if not (fences.get("quotes") or "").strip():
                problems.append(
                    "the reply carrying the submit call has no ```quotes block. "
                    "Write the supporting quotes as a ```quotes fenced block in "
                    "the reply text, then call submit in that same reply.")
            try:
                box["claims"] = self._gate(
                    {**s, "vocab_version": VOCAB_VERSION},
                    assumptions, properties, env, knowledge, pv)
            except Exception as e:
                problems.append(f"the submission does not pass the claims gate: {e}")
            return problems

        result = await run_agent(
            env.llm(), system=prompt.system, user=user,
            tools=list(prompt.tools), ctx=ctx, submit=submit, accept=_accept,
            budget=env.budget(), writer=writer, resume_from=resume,
            effort=self.effort, emitter=env.emitter(self.name),
        )
        if result.status == "gap":
            raise GapRaised(result.gap, transcript, result.gap_tool_call_id)
        if result.status != "ok":
            raise NodeError(f"{self.name}: {result.status}: {result.failure}")
        write_text(out / "quotes.md", result.fences["quotes"] + "\n")
        return box["claims"]
