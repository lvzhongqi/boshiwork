"""Checks for extract_flow: syntax and types, scoping, and honest reachability.

payload keys: pv, runner, pv_log (call it with a purpose for a log stem),
fixed_lines, roles, and the identity/structure idioms offered this session
(None for a supplied flow). The submitted file is itself the honest-run model,
so the checks run it as it stands, and typecheck and reachability share one
ProVerif subprocess cached in the payload for the round.
"""

from __future__ import annotations

import re

from orrery.checks.registry import CheckResult, register
from orrery.infra.proverif.outcome import (
    OutcomeKind, classify,
)
from orrery.modules.pvtext.parse import (
    blank_comments, parallel_branches, process_blocks, queries,
)
from orrery.modules.pvtext.probe import (
    any_call_spans, event_call, event_name, is_followed_by_semicolon, is_reached,
    main_process_calls,
    query_line,
)
from orrery.modules.kbase.modeling_idioms import identity_idiom, structure_idiom
from orrery.modules.pvtext.idioms import (
    entry_markers, identity_idiom_markers, malformed_idiom_marker_lines,
    structure_idiom_markers,
)


def _fixed_parts(payload) -> CheckResult:
    """The framework-owned channel and probe lines are kept verbatim."""
    pv = payload["pv"]
    f = [f"a fixed template line was changed or lost: {line!r}"
         for line in payload["fixed_lines"] if line not in pv]
    return CheckResult("flow_fixed_parts", "must", not f, f)


def _value_dependencies(payload) -> CheckResult:
    """Every principals value occurs in the model, and a value with
    ``derived_from`` is bound once as a named term over all of its sources.

    Warn level: a value bound once per role that computes it reads as several
    bindings and a term passed straight into a role reads as none, and both are
    correct models, so the findings name the shape found rather than gate.
    """
    pv = blank_comments(payload["pv"])
    findings: list[str] = []
    values = (payload.get("principals") or {}).get("values") or []
    for value in values:
        name = value["name"]
        sources = value.get("derived_from") or []
        if not re.search(rf"\b{re.escape(name)}\b", pv):
            findings.append(
                f"semantic value {name!r} does not occur in the flow model; "
                "every principals value is a stable downstream anchor")
            continue
        if not sources:
            continue
        independent = []
        if re.search(rf"\bnew\s+{re.escape(name)}\s*:", pv):
            independent.append("new")
        if re.search(rf"(?m)^\s*(?:free|const)\s+{re.escape(name)}\s*:", pv):
            independent.append("free/const")
        if independent:
            findings.append(
                f"semantic value {name!r} is derived_from {sources!r} but the "
                f"flow creates it independently with {' and '.join(independent)}")

        bindings = list(re.finditer(
            rf"\blet\s+{re.escape(name)}(?:\s*:\s*\w+)?\s*=\s*"
            rf"(?P<expression>.*?)\s+in\b", pv, re.S))
        if len(bindings) != 1:
            findings.append(
                f"semantic value {name!r} is derived_from {sources!r}, and the "
                f"flow has {len(bindings)} named `let {name} = ... in` "
                f"binding(s) rather than one stable one. Check it is deliberate: "
                f"several is right when each role recomputes the value from its "
                f"own parameter, and none is right when the term is passed "
                f"straight into a role instead of being named")
            continue
        expression = bindings[0].group("expression")
        missing = [source for source in sources
                   if not re.search(rf"\b{re.escape(source)}\b", expression)]
        if missing:
            findings.append(
                f"the binding of {name!r} does not use every derived_from "
                f"source; missing {missing!r}")
    return CheckResult("flow_value_dependencies", "warn",
                       not findings, findings)


def _no_extra_queries(payload) -> CheckResult:
    """The flow model carries no security goals: the only queries allowed are
    the honest-run probe's, which the template supplies. That the probe's
    queries are still there is flow_fixed_parts' to say.
    """
    allowed = {_squeeze(query_line(r)) for r in payload["roles"]}
    extra = [q for q in queries(payload["pv"]) if _squeeze(q) not in allowed]
    return CheckResult(
        "flow_no_extra_queries", "must", not extra,
        [f"the flow model must carry no query of its own (goals are injected "
         f"downstream); only the honest-run probe's queries belong here, found: {q}"
         for q in extra],
    )


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


_TABLE = re.compile(r"^\s*table\s+(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*\(", re.M)
_INSERT = re.compile(r"^\s*insert\s+(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*\(", re.M)
_GET = re.compile(r"^\s*get\s+(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*\(", re.M)
_PRIVATE_FUN = re.compile(r"^\s*fun\s+\w+\s*\([^\n]*\)\s*:\s*[^.\n]+\[private\]\s*\.", re.M)
_CERT_WORD = re.compile(r"\b(?:cert(?:ificate)?|opencert|checkcert|issuer)\w*\b", re.I)
_PUBLIC_REGISTRATION = re.compile(
    r"!\s*(?:\(\s*)?in\s*\(\s*c\s*,[\s\S]{0,1000}?\binsert\s+\w+\s*\(", re.M)


def _registry_findings(pv: str) -> list[str]:
    tables = {m.group("name") for m in _TABLE.finditer(pv)}
    inserts = {m.group("name") for m in _INSERT.finditer(pv)}
    gets = {m.group("name") for m in _GET.finditer(pv)}
    f = []
    if not tables:
        f.append("the selected identity binding declares no table")
    if tables and not tables & inserts:
        f.append("the selected identity table has no honest row inserted in the main process")
    if tables and not tables & gets:
        f.append("no role gets a credential from the selected identity table")
    if _PUBLIC_REGISTRATION.search(pv):
        f.append("the closed flow contains a replicated public registration intake; admission.open belongs downstream")
    return f


def _structure_findings(pv: str, roles: list[str], offered) -> list[str]:
    """The role-body-structure contract: a party the document gives several
    independent entries writes them as parallel branches of its own body, and
    the marker's ``entries=`` list has to match what the text does.

    Only the mechanical part is checked; independence itself is settled by
    ProVerif's scoping, since in ``P | Q`` nothing ``P`` binds is in scope in
    ``Q``. Which entry a later goal's event belongs in is semantics.
    """
    f: list[str] = []
    blocks = process_blocks(pv)
    blanked = blank_comments(pv)
    marked_roles: set[str] = set()

    for marker in structure_idiom_markers(pv):
        tag = f"{marker.id}/v{marker.version}"
        if structure_idiom(marker.id, marker.version) is None:
            f.append(f"unknown structure modelling idiom {tag}")
            continue
        if offered is not None and marker.key not in offered:
            f.append(f"the flow selected structure idiom {tag}, which this session was "
                     f"never shown; call lookup_structure_modeling first")
        owner = [r for r, blk in blocks.items()
                 if blk.body_start <= marker.start < blk.body_end]
        if len(owner) != 1:
            f.append(f"{tag}: the marker is not inside exactly one role body "
                     f"(found {owner or 'none'}); it declares the shape of the body it "
                     f"sits in, so it belongs between that body's `(* @ROLE ... *)` "
                     f"line and its parallel composition")
            continue
        role = owner[0]
        marked_roles.add(role)
        declared = list(marker.entries)
        if len(set(declared)) != len(declared):
            f.append(f"{tag}: role {role} declares a repeated entry name in "
                     f"entries={','.join(declared)}")
        if len(set(declared)) < 2:
            f.append(f"{tag}: role {role} declares {len(set(declared))} entry; this "
                     f"shape is for a party with two or more independent entries, and "
                     f"one entry is an ordinary linear body")
            continue
        branches = parallel_branches(pv, blocks[role])
        if branches is None:
            f.append(f"{tag}: role {role}'s body is not a parallel composition; the "
                     f"whole body must be `( <entry> | <entry> | ... )` with nothing "
                     f"else at its top level")
            continue
        if len(branches) != len(declared):
            f.append(f"{tag}: role {role} declares {len(declared)} entries "
                     f"({','.join(declared)}) but its body composes {len(branches)} "
                     f"parallel branches")
            continue
        seen: list[str] = []
        for index, (start, end) in enumerate(branches):
            names = [n for s, _e, n in entry_markers(pv) if start <= s < end]
            if len(names) != 1:
                f.append(f"{tag}: role {role}'s branch {index + 1} carries "
                         f"{len(names)} `(* @ENTRY <name> *)` marker(s); each branch "
                         f"opens with exactly one, naming which entry it is")
                continue
            seen.append(names[0])
            if not re.search(r"\b(?:in|out)\s*\(", blanked[start:end]):
                f.append(f"{tag}: role {role}'s entry {names[0]!r} neither sends nor "
                         f"receives; an entry is an exchange the party can be entered "
                         f"by, so it has at least one `in(...)` or `out(...)`")
            calls = len(re.findall(rf"event\s+{re.escape(event_name(role))}\s*\(",
                                   blanked[start:end]))
            if calls != 1:
                f.append(f"{tag}: role {role}'s entry {names[0]!r} calls "
                         f"`{event_call(role)}` {calls} time(s); each entry marks where "
                         f"its own honest run has succeeded, exactly once")
        if seen and sorted(seen) != sorted(set(declared)):
            f.append(f"{tag}: role {role} declares entries {sorted(set(declared))} but "
                     f"its branches are marked {sorted(seen)}")

    # Backstop: a parallel role body with no marker is not readable by the
    # checks that come after.
    for role, blk in blocks.items():
        if role in marked_roles or role not in roles:
            continue
        if parallel_branches(pv, blk) is not None:
            f.append(f"role {role}'s body is a parallel composition with no structure "
                     f"marker; call lookup_structure_modeling and write the method it "
                     f"returns, marker included")
    return f


def _modeling_idioms(payload) -> CheckResult:
    """The session may select one offered identity abstraction per scope, and
    the text has to implement it rather than merely carry its marker."""
    pv = payload["pv"]
    code = re.sub(r"\(\*[\s\S]*?\*\)", "", pv)
    markers = identity_idiom_markers(pv)
    f = [f"malformed modelling marker: {line!r}"
         for line in malformed_idiom_marker_lines(pv)]
    by_scope: dict[str, list] = {}
    for marker in markers:
        by_scope.setdefault(marker.scope, []).append(marker)
        item = identity_idiom(marker.id, marker.version)
        if item is None:
            f.append(f"unknown identity modelling idiom {marker.id}/v{marker.version}")
            continue
        if item.validator == "identity_registry_v1":
            f.extend(f"{marker.id}/v{marker.version}: {x}"
                     for x in _registry_findings(pv))
        elif item.validator == "identity_private_provisioning_v1":
            # On the comment-stripped text: a table mentioned in a comment is
            # not a table the model builds.
            if _TABLE.search(code) and _GET.search(code):
                f.append(f"{marker.id}/v{marker.version}: private provisioning must not also build an identity table")
            if not _PRIVATE_FUN.search(pv):
                f.append(f"{marker.id}/v{marker.version}: no private credential-identifier constructor was declared")
        elif item.validator == "identity_signed_certificate_v1":
            if not _CERT_WORD.search(code):
                f.append(f"{marker.id}/v{marker.version}: no certificate construction or validation symbol occurs")
            if _TABLE.search(code) and _GET.search(code):
                f.append(f"{marker.id}/v{marker.version}: certificate validation was mixed with an identity table")
        else:
            f.append(f"{marker.id}/v{marker.version}: unknown validator {item.validator!r}")
    for scope, selected in by_scope.items():
        if len(selected) > 1:
            f.append(f"identity scope {scope!r} selects {len(selected)} mutually exclusive idioms: "
                     f"{[f'{x.id}/v{x.version}' for x in selected]}")

    # None means a supplied mother model: no extraction session offered
    # candidates, so its in-text marker is the whole durable contract.
    offered = payload.get("offered_identity_idioms")
    if offered is not None:
        selected_keys = {x.key for x in markers}
        unseen = selected_keys - set(offered)
        if unseen:
            f.append("the flow selected identity idiom(s) the session was never shown: "
                     f"{sorted(unseen)}; call lookup_identity_modeling first")
        if offered and not markers:
            f.append("lookup_identity_modeling returned candidates, but the flow selected none; write exactly one candidate marker for this scope")
        if payload.get("identity_modeling_miss"):
            f.append("lookup_identity_modeling found no applicable method; this is a modelling-library coverage gap, so the identity mechanism may not be flattened or invented")

    # Unmarked table/get or certificate machinery has to name the KB contract
    # that owns it.
    if not markers and _TABLE.search(code) and _GET.search(code):
        f.append("the flow contains table/get machinery with no modelling marker; call lookup_identity_modeling and select one returned method")
    if not markers and _CERT_WORD.search(code):
        f.append("the flow contains certificate-shaped machinery with no modelling marker; call lookup_identity_modeling and select one returned method")

    f.extend(_structure_findings(pv, payload["roles"],
                                 payload.get("offered_structure_idioms")))

    return CheckResult("flow_modeling_idioms", "must", not f, f)


def _honest_end_marked(payload) -> CheckResult:
    """Each role's body reaches its own probe event, at the end of a branch.

    Where an honest run has succeeded cannot be found in the text, so the model
    marks it and only the mechanical part is checked: the call sits in this
    role's own body, not in the main process, and is not followed by ``;``,
    which is what makes it an ending rather than a waypoint.
    """
    pv = payload["pv"]
    blocks = process_blocks(pv)
    f = []
    for role in payload["roles"]:
        if role not in blocks:
            f.append(f"role {role} has no `let process{role}(...)` definition")
            continue
        spans = any_call_spans(pv, blocks[role])
        mine = [sp for sp in spans if sp[2] == role]
        others = sorted({sp[2] for sp in spans if sp[2] != role})
        for other in others:
            f.append(
                f"role {role}'s body calls `{event_call(other)}`, which belongs to "
                f"role {other}: each role marks its own honest end, in its own body")
        if not mine:
            f.append(
                f"role {role}'s body never reaches `{event_call(role)}`: put it at the "
                f"point where this role's honest run has succeeded -- after the last "
                f"message it handles and after every check the document has it make. "
                f"Every other branch ends on its own `0`.")
        for _start, end, _r in mine:
            if is_followed_by_semicolon(pv, end):
                f.append(
                    f"role {role}'s `{event_call(role)}` is followed by `;`, so it is a "
                    f"waypoint rather than the end of a branch: move it to where the "
                    f"branch ends and let nothing follow it.")
    for role in main_process_calls(pv):
        f.append(
            f"the main process calls `{event_call(role)}`: the honest end is a point "
            f"inside a role body, and marking it outside makes it reachable without "
            f"the role ever finishing")
    return CheckResult("flow_honest_end_marked", "must", not f, f)


async def _proverif(payload):
    """Run ProVerif once per round on the submitted file and cache the outcome
    in the payload, so typecheck and reachability share one subprocess. The file
    is already the honest-run model, so both questions are answered by the same
    call and every error is an error in the file the model submitted.
    """
    if "_outcome" not in payload:
        raw = await payload["runner"].run(
            payload["pv"], log_to=payload["pv_log"]("proverif"))
        payload["_outcome"] = classify(raw)
    return payload["_outcome"]


async def _typecheck(payload) -> CheckResult:
    """Syntax, types and scoping, as ProVerif sees the submitted file verbatim.

    Only a syntax or type error is this check's to report. A timeout or a solver
    that gave up says nothing about the file being well-formed and belongs to
    reachability, which was waiting on the same run.
    """
    out = await _proverif(payload)
    if out.kind is not OutcomeKind.SYNTAX_ERROR:
        return CheckResult("flow_typecheck", "must", True, [],
                           "" if out.kind is OutcomeKind.OK else
                           f"ProVerif did not reach a verdict ({out.kind.value}), "
                           f"so nothing beyond the file being well-formed was checked")
    return CheckResult("flow_typecheck", "must", False,
                       out.errors or [f"ProVerif rejected the file and reported no line-level error (outcome: {out.kind.value}); the failure is structural rather than local -- check that every declaration the bodies use is present and that the file ends with a complete main process"])


async def _reachability(payload) -> CheckResult:
    """Honest reachability: with the named channels private, each role reaches
    the probe event it marked its honest end with.

    Reachable means a verdict of false or cannot_be_proved. True means the event
    is never reached: the flow was modelled broken, or the event sits in a branch
    an honest run does not take.
    """
    out = await _proverif(payload)
    detail = (out.errors or ["no detail"])[0]
    if out.kind is not OutcomeKind.OK:
        # Worded apart from an unreachable verdict, so the model does not follow
        # a "fields do not line up" diagnosis and rewrite a model that was fine.
        return CheckResult("flow_reachability", "must", False, [
            f"ProVerif reached no verdict ({out.kind.value}: {detail}), so honest "
            f"reachability is unanswered; fix that first"])
    f = []
    for role in payload["roles"]:
        # Each role's verdict is found by its own event name, as a whole word:
        # ``reached_A`` is a prefix of ``reached_AS`` (NSSK's server), and a
        # substring match would let one role's verdict answer for the other.
        mine = [v for v in out.verdicts
                if re.search(rf"\breached_{re.escape(role)}\b", v.query)]
        if not mine:
            f.append(f"no verdict came back for role {role}'s reachability query; "
                     f"the queries that did report: "
                     f"{[v.query for v in out.verdicts] or 'none'}")
        elif not any(is_reached(v.verdict) for v in mine):
            f.append(f"role {role} never reaches `{event_call(role)}` on the honest run: "
                     f"either the send and receive fields, types or channels do not line "
                     f"up, or a check cannot pass even honestly -- or the event sits in a "
                     f"branch the honest run does not take (an error branch, or the wrong "
                     f"side of an `if`)")
    return CheckResult("flow_reachability", "must", not f, f)


register("flow_fixed_parts", "must", _fixed_parts)
register("flow_value_dependencies", "warn", _value_dependencies)
register("flow_no_extra_queries", "must", _no_extra_queries)
register("flow_honest_end_marked", "must", _honest_end_marked)
register("flow_modeling_idioms", "must", _modeling_idioms)
register("flow_typecheck", "must", _typecheck)
register("flow_reachability", "must", _reachability)

# Cost order: cheap text checks first, the ProVerif checks last.
# flow_value_dependencies rides along at warn level; its findings go into
# checks.md beside the gates.
FLOW_CHECK_NAMES = [
    "flow_fixed_parts", "flow_value_dependencies", "flow_no_extra_queries",
    "flow_honest_end_marked",
    "flow_modeling_idioms", "flow_typecheck", "flow_reachability",
]
