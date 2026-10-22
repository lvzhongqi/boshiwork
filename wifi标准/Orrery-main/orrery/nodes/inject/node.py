"""8.2 inject: one LLM call per (scenario x family) batch, writing one model.pv.
A family is a goal type whose subtypes share one modelling machinery, so one
reading of the scenario model serves every cell; different families are never
batched together, since their rules contaminate each other silently.

The model submits fragments, not a rewritten file: ``declarations`` are
complete declaration lines the framework places in the declaration area,
``edits`` are anchored insertions inside role bodies. A declaration line found
in ``edits`` is rejected before assembly.

Assembly splices the fragments into a fresh copy of scenario.pv and the GOALS
checks run on it; a batch whose model.pv already exists on re-entry is returned
unchanged. There are no tools — a failed acceptance returns the findings and
the assembled file, and the model resubmits anchored against scenario.pv.
"""

from __future__ import annotations

import json
import re

import orrery.checks.rules.goals  # noqa: F401  importing registers the checks
from orrery.agent.compose import (
    RepairContext, assembled_context, localized, render_prompt, render_system,
    resume_user,
    step_messages as messages_section,
)
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.services import facts as fact_store
from orrery.infra.llm.client import Effort
from orrery.agent.tools import SCENARIO_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.checks.registry import must_failures, run_checks
from orrery.checks.rules.goals import GOALS_CHECK_NAMES
from orrery.modules.pvtext.anchored import Edit, EditError, apply_edits
from orrery.modules.pvtext.edits import append_declarations
from orrery.modules.pvtext.parse import (
    PvTextError, blank_comments, duplicate_destructor_declarations, free_decls,
    process_blocks, queries,
)
from orrery.nodes.base import NodeError, RoundLog, RunEnv
from orrery.nodes.inject.injectors import injector_for
from orrery.services.events import FrameworkAction, check_sink
from orrery.services.store.layout import unit_name
from orrery.services.store.atomic import write_text
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

# The subtype to inject when goal.subtype is absent (per the KB: a Secrecy
# goal with no subtype means plain secrecy).
_DEFAULT_SUBTYPE = {"Secrecy": "basic"}

# Every semantic decision this step makes is covered by a goal check that fails
# loudly with a diagnosis, so a thin first attempt costs a repair round rather
# than a wrong model; measurement gives the higher rungs no advantage here.
_INJECT_EFFORT = Effort.MEDIUM

_EDIT_ITEM = {
    "type": "object",
    "properties": {
        "anchor": {
            "type": "string",
            "description": "verbatim quote of the line(s) in the scenario "
                           "model this edit attaches to; must match exactly "
                           "once — extend the quote with an adjacent line if "
                           "it is ambiguous",
        },
        "position": {
            "type": "string", "enum": ["before", "after", "replace"],
            "description": "before/after insert text as new line(s) next to the "
                           "anchor; replace substitutes the anchor span (empty "
                           "text deletes — quote everything you delete). A role "
                           "body's final `0.` is the process terminator: a "
                           "replace whose anchor takes it in must end with it "
                           "too, or the file stops being a .pv",
        },
        "text": {"type": "string",
                 "description": "the fragment to insert, exactly as it should "
                                "appear in the file"},
    },
    "required": ["anchor", "position", "text"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "declarations": {
            "type": "array", "items": {"type": "string"},
            "description": "complete declaration lines for the whole batch — "
                           "event declarations, witness frees, the wenc/wdec "
                           "pair, every goal's query, and observation-only "
                           "membership tables — in order; the framework "
                           "places them in the declaration area (never anchor "
                           "a declaration through edits). Machinery two goals "
                           "share is declared once: they are going into one "
                           "file",
        },
        "edits": {
            "type": "array", "items": _EDIT_ITEM,
            "description": "anchored model edits: process statements (event "
                           "calls, witness outputs, and guards), plus role "
                           "signature and main-call replacements needed to "
                           "pass existing stable observation values into a "
                           "role, all as anchored edits applied in "
                           "submission order, each matching against the result "
                           "of the previous one. An event two goals both need "
                           "is inserted once",
        },
    },
    "required": ["declarations", "edits"],
    "additionalProperties": False,
}


# A declaration line has no business inside an anchored edit: its position is
# the framework's. `event` needs the trailing period to count — `event e(x);`
# is a call and belongs in edits, `event e(t).` is a declaration.
_DECL_LINE = re.compile(
    r"(?m)^\s*(?:query|weaksecret|free|fun|reduc|table)\b"
    r"|^\s*event\s+\w+\s*(?:\([^)]*\))?\s*\.\s*$"
)

_WEAKSECRET_DECL = re.compile(
    r"^\s*weaksecret\s+([A-Za-z_]\w*)\s*\.\s*$")


def stray_declarations(edits: list[Edit]) -> list[str]:
    """Declaration-like lines found inside edits, for rejection before assembly."""
    return [m.group(0).strip()
            for e in edits for m in _DECL_LINE.finditer(e.text)]


def open_guard_before_else_problems(base_pv: str,
                                    edits: list[Edit]) -> list[str]:
    """Reject an injected open conditional that can steal a protocol ``else``.

    ProVerif binds ``else`` to the nearest unmatched ``if``, so a guard added at
    the tail of an existing ``then`` arm turns the old alternative arm into the
    new guard's alternative. Fires only when an edit adds more ``if`` than
    ``else`` tokens ahead of an original ``else`` in the same role; inexact
    anchors are left to the ordinary anchored-edit error path.
    """
    blank_base = blank_comments(base_pv)
    blocks = tuple(process_blocks(base_pv).values())
    problems: list[str] = []
    for index, edit in enumerate(edits, start=1):
        fragment = blank_comments(edit.text)
        open_ifs = len(re.findall(r"\bif\b", fragment))
        closed_ifs = len(re.findall(r"\belse\b", fragment))
        if open_ifs <= closed_ifs:
            continue
        if base_pv.count(edit.anchor) != 1:
            continue
        at = base_pv.index(edit.anchor)
        block = next((b for b in blocks
                      if b.body_start <= at < b.body_end), None)
        if block is None:
            continue
        if re.search(r"\belse\b", blank_base[at:block.body_end]) is None:
            continue
        problems.append(
            f"edit {index} adds {open_ifs - closed_ifs} unmatched observation "
            f"`if` guard(s) before an existing `else` in role {block.role}; "
            "that `else` would bind to the new guard and change which protocol "
            "branch is reachable. Reuse the enclosing honest-peer branch as "
            "the guard, or replace the complete branch tail with a conditional "
            "that has its own explicit `else` while preserving the original "
            "then/else structure")
    return problems


def weaksecret_contract_problems(base_pv: str, declarations: list[str],
                                 edits: list[Edit], goals: list) -> list[str]:
    """Mechanical contract for ProVerif's goal-id-free ``weaksecret`` mode.

    A weaksecret verdict is attributed by its one-goal file, so the file must
    stay pure: one weaksecret declaration per goal value, no role edits, and
    every named value already a top-level private free from the assumption
    layer. Only facts visible in the text are checked — which model name
    denotes a document-level value stays the model's judgment.
    """
    weak = [g for g in goals
            if g.type == "Secrecy"
            and g.subtype == "weak_secret_guessing_resistance"]
    if not weak:
        return []

    problems: list[str] = []
    if len(goals) != 1 or len(weak) != 1:
        problems.append(
            "weak_secret_guessing_resistance must be the only goal in its "
            "model file because ProVerif's `Weak secret <value>` verdict "
            "carries no goal id")
        return problems
    if edits:
        problems.append(
            "weak_secret_guessing_resistance adds only top-level `weaksecret` "
            "declarations; edits must be empty")

    names: list[str] = []
    for line in declarations:
        match = _WEAKSECRET_DECL.fullmatch(line)
        if match is None:
            problems.append(
                "a weaksecret-only file may declare only complete "
                f"`weaksecret <value>.` lines, got: {line!r}")
        else:
            names.append(match.group(1))
    expected = len(weak[0].values)
    if len(names) != expected:
        problems.append(
            f"goal {weak[0].id} names {expected} value(s), but the submission "
            f"contains {len(names)} weaksecret declaration(s): {names}")
    if len(names) != len(set(names)):
        problems.append(f"weaksecret declarations contain duplicate values: {names}")

    private_free = {name for name, _, private in free_decls(base_pv) if private}
    for name in names:
        if name not in private_free:
            problems.append(
                f"`weaksecret {name}.` does not name a top-level private free "
                "in the scenario model; primitive.broken must hoist the "
                "low-entropy value before goal injection")
    return problems


def _flat_call_args(text: str, event_name: str, *, declaration: bool = False
                    ) -> list[tuple[str, ...]]:
    """Arguments of simple event declarations/calls with an exact name.

    Event observations bind local variables, not constructor expressions, so
    nested parentheses are outside this small structural parser: a nested
    expression fails the exact-count contract and goes back to the model.
    """
    prefix = r"event\s+" if not declaration else r"(?m)^\s*event\s+"
    suffix = r"\s*\." if declaration else ""
    pattern = prefix + re.escape(event_name) + r"\s*\(([^()]*)\)" + suffix
    out = []
    for match in re.finditer(pattern, text):
        inner = match.group(1).strip()
        out.append(tuple(x.strip() for x in inner.split(",")) if inner else ())
    return out


def _named_args(text: str, name: str) -> list[tuple[str, ...]]:
    """Arguments of exact-name invocations such as those inside a query."""
    out = []
    for match in re.finditer(re.escape(name) + r"\s*\(([^()]*)\)", text):
        inner = match.group(1).strip()
        out.append(tuple(x.strip() for x in inner.split(",")) if inner else ())
    return out


def authentication_contract_problems(pv: str, goals: list,
                                    submitted: str = "") -> list[str]:
    """Mechanical part of Authentication injection's property contract.

    ``parties`` fixes direction and ``values`` fixes the event vector; the model
    still chooses which binding denotes each value and where the commit and
    completion points sit. ``submitted`` is the raw edit text, used only to tell
    "never written" apart from "written but not in a role body" — the two
    failures need different repairs.
    """
    problems: list[str] = []
    blanked = blank_comments(pv)
    blocks = process_blocks(pv)
    queries = re.findall(r"(?ms)^\s*query\b.*?\.\s*$", blanked)

    for goal in goals:
        if goal.type != "Authentication":
            continue
        begin = f"begin_{goal.id}"
        end = f"end_{goal.id}"
        expected = len(goal.values)
        subject = str(goal.parties.get("subject", ""))
        asserter = str(goal.parties.get("asserter", ""))

        for name in (begin, end):
            decl_args = _flat_call_args(blanked, name, declaration=True)
            if len(decl_args) != 1:
                problems.append(
                    f"Authentication goal {goal.id}: expected exactly one "
                    f"declaration `event {name}(...)`, found {len(decl_args)}")
            elif len(decl_args[0]) != expected:
                problems.append(
                    f"Authentication goal {goal.id}: `{name}` declares "
                    f"{len(decl_args[0])} argument(s), but values={list(goal.values)} "
                    f"requires exactly {expected}; parties add no arguments")

        calls: dict[str, list[tuple[str, tuple[str, ...]]]] = {begin: [], end: []}
        for role, block in blocks.items():
            body = blanked[block.body_start:block.body_end]
            for name in (begin, end):
                calls[name].extend((role, args)
                                   for args in _flat_call_args(body, name))

        for name, wanted_role in ((begin, subject), (end, asserter)):
            found = calls[name]
            if len(found) != 1:
                places = [role for role, _ in found]
                if not found and submitted and name not in submitted:
                    problems.append(
                        f"Authentication goal {goal.id}: your edits never write "
                        f"`{name}`. It is missing from the submission itself, not "
                        f"misplaced — add the call to the edit that lands in role "
                        f"{wanted_role}'s body. Moving an anchor cannot fix this")
                else:
                    problems.append(
                        f"Authentication goal {goal.id}: `{name}` must be called "
                        f"exactly once in role {wanted_role}, found {len(found)} "
                        f"call(s) in roles {places}")
                continue
            role, args = found[0]
            if role != wanted_role:
                problems.append(
                    f"Authentication goal {goal.id}: `{name}` is in role "
                    f"{role}, but parties requires role {wanted_role}")
            if len(args) != expected:
                problems.append(
                    f"Authentication goal {goal.id}: call `{name}` has "
                    f"{len(args)} argument(s), but values={list(goal.values)} "
                    f"requires exactly {expected}")

        own_queries = [q for q in queries if re.search(
            rf"\b{re.escape(end)}\s*\(", q)]
        if len(own_queries) != 1:
            problems.append(
                f"Authentication goal {goal.id}: expected exactly one query "
                f"over `{end}`, found {len(own_queries)}")
            continue
        query = own_queries[0]
        for name in (begin, end):
            args = _named_args(query, name)
            if len(args) != 1 or len(args[0]) != expected:
                problems.append(
                    f"Authentication goal {goal.id}: query call `{name}` must "
                    f"occur once with exactly {expected} argument(s)")
        injective = goal.subtype == "injective_agreement"
        has_inj_begin = bool(re.search(
            rf"inj-event\s*\(\s*{re.escape(begin)}\s*\(", query))
        has_inj_end = bool(re.search(
            rf"inj-event\s*\(\s*{re.escape(end)}\s*\(", query))
        if injective and not (has_inj_begin and has_inj_end):
            problems.append(
                f"Authentication goal {goal.id}: injective_agreement requires "
                "inj-event on both sides of the query")
        if not injective and (has_inj_begin or has_inj_end):
            problems.append(
                f"Authentication goal {goal.id}: subtype {goal.subtype} "
                "requires plain event on both sides of the query")
    return problems


def unlinkability_contract_problems(pv: str, goals: list) -> list[str]:
    """Mechanical contract for the one-goal observational-equivalence game."""
    privacy = [g for g in goals if g.type == "Privacy"
               and g.subtype == "unlinkability"]
    if not privacy:
        return []
    if len(goals) != 1 or len(privacy) != 1:
        return ["Privacy.unlinkability must be injected one goal per model file"]
    goal = privacy[0]
    marker = f"@orrery-unlinkability {goal.id}"
    if pv.count(marker) != 1:
        return [f"Privacy goal {goal.id}: expected exactly one comment marker "
                f"`(* {marker} *)`, found {pv.count(marker)}"]
    choices = re.findall(r"choice\s*\[\s*([^,\[\]]+)\s*,\s*([^\[\]]+)\s*\]", pv)
    if not choices:
        return [f"Privacy goal {goal.id}: the model contains no `choice[left,right]`, "
                "so it is not a biprocess and cannot ask observational equivalence"]
    if not any(left.strip() != right.strip() for left, right in choices):
        return [f"Privacy goal {goal.id}: every choice has identical left and "
                "right arms, so the equivalence game compares a world with itself"]
    if queries(pv):
        return [f"Privacy goal {goal.id}: unlinkability is answered by the "
                "biprocess's unnamed observational-equivalence result; do not add "
                "a reachability query"]
    return []


def grid_subtype(goal) -> str:
    """The subtype naming this goal's grid cell, falling back to the type's
    default. Raises NodeError when the type has neither."""
    sub = goal.subtype or _DEFAULT_SUBTYPE.get(goal.type)
    if sub is None:
        raise NodeError(f"inject failed: goal {goal.id} of type {goal.type} has no subtype and no default")
    return sub


def assemble(scenario_pv: str, edits: list[Edit],
             declarations: list[str]) -> str:
    """Splice one cell's fragments into scenario.pv: edits at their anchors
    against the pristine text, declarations into the declaration area.

    Raises EditError when an anchor does not match, and PvTextError when the
    edits applied but left something that is no longer a .pv. Both are the
    model's mistake, and the caller turns either into a repair round."""
    pv = apply_edits(scenario_pv, edits)
    if declarations:
        pv = append_declarations(pv, declarations)
    return pv


def parse_batch(submission, goal_ids: list[str]):
    """Shape-validate one submission against the batch's goals. Pure, so it is
    testable without an agent loop.

    Returns (active_goal_ids, problems): active is every goal in the batch,
    since inject has no partial-success shape, and a non-empty problems list
    means a repair round before any assembly is attempted.
    """
    problems: list[str] = []
    active = list(goal_ids)
    decls, edits = submission["declarations"], submission["edits"]
    if not decls and not edits:
        problems.append(
            f"declarations and edits are both empty; inject every goal in "
            f"{sorted(active)}")
    return active, problems


def build_prompt(scenario_pv: str, cells, *, step_messages: str = "",
                 unresolved: dict[str, list[str]] | None = None,
                 lang: str = "en") -> Prompt:
    """One batch's request — one session, one file. No I/O and no LLM, so the
    prompt preview renders exactly what a run sends.

    System block 1 is the scenario model, shared verbatim by every batch of this
    scenario (the cacheable big block); block 2 is the injection rules,
    deduplicated by rendered text. Neither names an assumption: the model
    arrives already rewritten by apply, and what an injection does depend on —
    a phase boundary — is read off the model text. ``unresolved`` is the names
    extract_claims could not place, narrowed to this batch: a hint only."""
    rules = list(dict.fromkeys(injector_for(gt, st).sys_prompt(lang=lang)
                               for gt, st, _ in cells))
    goals_json = json.dumps([
        {"id": g.id, "type": g.type, "subtype": st,
         "values": list(g.values), "parties": g.parties}
        for gt, st, goals in cells for g in goals], ensure_ascii=False, indent=2)
    return Prompt(
        system=render_system(__file__, localized("main.sys.md", lang),
                             cut_after=["scenario_model"], pv=scenario_pv,
                             rules="\n\n".join(rules)),
        user=render_prompt(__file__, localized("main.user.md", lang),
                           goals_json=goals_json,
                           unresolved_json=(json.dumps(unresolved, ensure_ascii=False,
                                                       indent=2)
                                            if unresolved else ""),
                           step_messages=step_messages),
        submit=SubmitSpec(kind="tool", schema=_SCHEMA),
        label="inject " + ", ".join(f"{gt}.{st}" for gt, st, _ in cells),
    )


def _unresolved_for(env: RunEnv, goal_ids: list[str]) -> dict[str, list[str]]:
    """extract_claims' unresolved names, narrowed to this batch's goals.

    Names owned only by an assumption are left out — those are apply's to
    place. extract_claims writes the file on every pass, supplied claims
    included, so its absence means the run is not one this engine produced.
    """
    p = env.layout.node_dir("extract_claims") / "anchoring.json"
    if not p.exists():
        raise NodeError(
            f"inject: {p} is missing; extract_claims writes it on every pass, "
            f"so this run's claims stage was not produced by this engine")
    unresolved = json.loads(p.read_text(encoding="utf-8")).get("unresolved", {})
    mine = set(goal_ids)
    return {name: owners for name, owners in unresolved.items()
            if mine.intersection(owners)}


async def inject_family(env: RunEnv, label: str, scenario_pv: str,
                        family: str, cells, runner) -> str:
    """Inject one batch — one session, one ``.pv`` — and return its text,
    writing it as the batch's model.pv.

    ``cells`` is [(gtype, subtype, goals)]: the subtypes that may share a file,
    decided by ``perturbs_model`` upstream in ``family_batches``. One submission
    writes them all into one file, so machinery two of them share is written
    once and their verdicts stay comparable. ``family`` is the batch's
    identity: the goal family, or ``<family>_c<N>`` for one chunk of a family
    the per-call cap split, which is a family directory like any other.
    """
    batch_label = family
    goal_ids = [g.id for _, _, goals in cells for g in goals]
    goals_by_id = {g.id: g for _, _, goals in cells for g in goals}

    # Families are the scenario's own fan-out — concurrent, none upstream of
    # another — so they are generation-numbered: carry on in the existing
    # directory unless the re-work is aimed at this family itself.
    prev = env.layout.find_inject_family_dir(label, family)
    what = env.plan(f"scenarios/{label}/inject/{family}", prev, True)
    home = prev if what != "open" else env.layout.open_inject_family(label, family)

    # Re-entry: a model.pv on disk passed its checks in a previous attempt.
    done = env.layout.inject_model(label, family)
    if done.exists():
        return done.read_text(encoding="utf-8").rstrip("\n")

    # A fact filed for this one family rides after the scenario-scoped block; a
    # fix aimed here gives the family a new directory, off the reuse path.
    own_facts = fact_store.read(home)
    prompt = build_prompt(scenario_pv, cells,
                          step_messages=env.facts("scenarios", label)
                          + messages_section([f.text for f in own_facts]),
                          unresolved=_unresolved_for(env, goal_ids),
                          lang=env.config.get("prompt_lang", "en"))
    submit = prompt.submit
    system = prompt.system

    transcript = env.layout.inject_transcript(label, family)
    resume = resume_messages(transcript)
    writer = TranscriptWriter(transcript)
    if resume is None:
        writer.meta(node="inject", scenario=label, grid=batch_label,
                    model=env.config["llm"].get("model", "?"),
                    effort=_INJECT_EFFORT)
        user = prompt.user
    else:
        user = resume_user(submit)

    rounds = RoundLog(home)
    ctx = ToolContext(node="inject", doc_set=env.doc_set,
                      artifacts_root=env.layout.run_dir,
                      tool_return_chars=env.config["agent"]["tool_return_chars"])

    # Bound to this call, so concurrent families' fragments do not interleave.
    emit = env.emitter("inject", scenario=label,
                       unit=unit_name(env.layout.scenario_dir(label),
                                      transcript.parent))

    def _framework(text: str) -> None:
        if emit is not None:
            emit(FrameworkAction(run="", text=text))

    built: dict[str, str] = {}

    async def _accept(submission, fences):
        active, problems = parse_batch(submission, goal_ids)
        if problems:
            _framework("read the submission — it did not line up with the "
                       "batch's goals, so nothing was assembled")
            return problems
        rounds.submission(submission)
        try:
            edits = [Edit(anchor=e["anchor"], position=e["position"],
                          text=e["text"]) for e in submission["edits"]]
        except (KeyError, TypeError) as exc:
            return [f"edits entry malformed: {exc}"]
        decls = list(submission["declarations"])
        active_goals = [goals_by_id[goal_id] for goal_id in active]
        if weaksecret_problems := weaksecret_contract_problems(
                scenario_pv, decls, edits, active_goals):
            return weaksecret_problems
        if stray := stray_declarations(edits):
            return [f"declaration line(s) inside edits: {stray}; declarations "
                    f"go in the `declarations` field — the framework places "
                    f"them, edits carry in-body statements only"]
        if duplicates := duplicate_destructor_declarations(decls):
            return [f"symbol(s) {duplicates} are declared with `fun` and also "
                    f"introduced as the outer destructor of a `reduc`; declare "
                    f"only the constructor with `fun` and introduce each "
                    f"destructor only through its reduction rule"]
        if branch_problems := open_guard_before_else_problems(
                scenario_pv, edits):
            return branch_problems
        if (any("wenc(" in e.text for e in edits)
                and not any("fun wenc" in d for d in decls)
                and "fun wenc" not in scenario_pv):
            return ["a witness output uses wenc but no declaration defines it; "
                    "declare the pair in `declarations`, typing the second "
                    "argument as the secret value's own type"]
        try:
            pv = assemble(scenario_pv, edits, decls)
        except EditError as exc:
            _framework("an anchor did not match, not assembled")
            return [str(exc)]
        except PvTextError as exc:
            # e.g. a `replace` that ends a role's body and drops its closing
            # period. Caught and repaired in the same round.
            _framework("the spliced text no longer parses, not assembled")
            return [f"the edits applied, but the result is no longer a "
                    f"well-formed .pv: {exc}. Every process definition has to "
                    f"stay terminated — a `replace` that rewrites the end of a "
                    f"role's body must keep its closing period."]
        contract = authentication_contract_problems(
            pv, active_goals,
            submitted="\n".join(e.text for e in edits))
        contract.extend(unlinkability_contract_problems(
            pv, active_goals))
        if contract:
            _framework("the spliced text violates a property "
                       "contract, not sent to ProVerif")
            return contract
        # Announced before the checks run: they are ProVerif runs over the whole
        # model, minutes of silence that would otherwise look like a dead run.
        _framework(f"spliced {len(decls)} declaration(s) + {len(edits)} edit(s) "
                   f"into scenario.pv ({len(pv.splitlines())} lines) covering "
                   f"{len(active)} goal(s) — running the goal checks on it")
        rounds.begin(pv)         # the assembled model lands first, then its checks
        # base_pv is the pre-injection text: a check that orders a construct
        # moved needs it to tell the model's constructs from the protocol's.
        equivalence_only = (len(active_goals) == 1
                            and active_goals[0].type == "Privacy"
                            and active_goals[0].subtype == "unlinkability")
        weaksecret_only = (len(active_goals) == 1
                           and active_goals[0].type == "Secrecy"
                           and active_goals[0].subtype
                           == "weak_secret_guessing_resistance")
        # Both modes produce a solver verdict with no goal-id-bearing `query`
        # statement. Their one-goal file and property contract replace the
        # ordinary naming-anchor check; the shared typecheck still runs.
        check_names = (["goals_typecheck"] if equivalence_only or weaksecret_only
                       else GOALS_CHECK_NAMES)
        found = must_failures(await run_checks(
            check_names, {
                "pv": pv, "base_pv": scenario_pv, "runner": runner,
                "pv_log": rounds.stem, "goal_ids": active},
            on=check_sink(emit)))
        rounds.finish(found)
        if found:
            # a repair attachment, not a finding: RepairContext keeps the
            # assembled file out of the ledger digest
            return [*found, RepairContext(assembled_context(pv))]
        built["pv"] = pv
        write_text(done, pv + "\n")
        return []

    result = await run_agent(
        env.llm(), system=system, user=user,
        emitter=emit,
        tools=SCENARIO_TOOLS, ctx=ctx,
        submit=submit,
        accept=_accept, budget=env.budget(), writer=writer, resume_from=resume,
        effort=_INJECT_EFFORT,
    )
    if result.status != "ok":
        raise NodeError(f"inject[{label}] {batch_label}: "
                        f"{result.status}: {result.failure}")
    if "pv" not in built:
        raise NodeError(f"inject[{label}] {batch_label}: accepted submission "
                        f"left no assembled model (framework defect)")
    return built["pv"]
