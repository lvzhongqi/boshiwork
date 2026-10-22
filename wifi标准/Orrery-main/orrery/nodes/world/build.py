"""The world-assumption builder engine: one agent session per non-default world
entry, on the anchored-edit, check and transcript machinery the object-level
apply engine uses.

Builders run in a fixed total order — population, role_binding,
session_multiplicity — because each edits the terrain the previous one left. An
axis sitting at its default value produces no step, only a note.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import orrery.checks.rules.scenario  # noqa: F401  importing registers the checks
from orrery.agent.compose import (
    assembled_context, localized, render_file, render_prompt, render_system,
    resume_user, step_messages as messages_section,
)
from orrery.agent.runner import SubmitSpec, run_agent
from orrery.agent.tools import SCENARIO_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.checks.registry import must_failures, run_checks
from orrery.checks.rules.scenario import SCENARIO_CHECK_NAMES
from orrery.infra.llm.client import Effort
from orrery.modules.pvtext.anchored import Edit, EditError, apply_edits
from orrery.modules.pvtext.parse import blank_comments
from orrery.nodes.world.builders import WORLD_VOCAB, builder_for
from orrery.nodes.base import NodeError, RoundLog, RunEnv
from orrery.services import facts as fact_store
from orrery.services.events import FrameworkAction, check_sink
from orrery.services.store.atomic import write_text
from orrery.services.store.layout import unit_name
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

_BUILD_EFFORT = Effort.MEDIUM

#: one anchored edit in the submission schema
_EDIT_ITEM = {
    "type": "object",
    "properties": {
        "anchor": {
            "type": "string",
            "description": "verbatim quote of the line(s) in the current model "
                           "this edit attaches to; must match exactly once — "
                           "extend the quote with an adjacent line if it is "
                           "ambiguous",
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
                 "description": "the fragment, exactly as it should appear in "
                                "the file"},
    },
    "required": ["anchor", "position", "text"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array", "minItems": 1, "items": _EDIT_ITEM,
            "description": "applied in submission order, each matching against "
                           "the result of the previous one",
        },
    },
    "required": ["edits"],
    "additionalProperties": False,
}

def binder_inventory(pv: str) -> Counter:
    """The model's binder-name multiset: every ``new`` and ``let`` binder plus
    top-level ``free``/``const``/``table``/``event`` declarations. A
    deterministic text extraction, so a difference between two sides of a diff
    is a real edit. Pattern binders (``let (x, y) = …``) fall outside the
    single-name regex on both sides alike."""
    text = blank_comments(pv)
    names: Counter = Counter()
    for m in re.finditer(r"\bnew\s+([A-Za-z0-9_']+)\s*:", text):
        names["new " + m.group(1)] += 1
    for kw in ("free", "const"):
        for m in re.finditer(rf"(?m)^\s*{kw}\s+([^:\n]+):", text):
            for n in m.group(1).split(","):
                names[f"{kw} " + n.strip()] += 1
    for m in re.finditer(r"(?m)^\s*table\s+([A-Za-z0-9_']+)\s*\(", text):
        names["table " + m.group(1)] += 1
    for m in re.finditer(r"(?m)^\s*event\s+([A-Za-z0-9_']+)", text):
        names["event " + m.group(1)] += 1
    for m in re.finditer(r"\blet\s+([A-Za-z0-9_']+)\s*(?::\s*[A-Za-z0-9_']+)?\s*=", text):
        names["let " + m.group(1)] += 1
    return names


def inventory_violations(builder, base_pv: str, new_pv: str) -> list[str]:
    """The inventory-conservation gate for a re-seating builder: the complaints
    about bindings this edit minted or dropped, empty for a builder that
    restructures material (``preserves_inventory`` False). A row wired to a
    wrong existing value is outside its reach."""
    if not builder.preserves_inventory:
        return []
    before = binder_inventory(base_pv)
    after = binder_inventory(new_pv)
    added = sorted((after - before).keys())
    removed = sorted((before - after).keys())
    if not added and not removed:
        return []
    parts = []
    if added:
        parts.append(f"adds {added}")
    if removed:
        parts.append(f"removes {removed}")
    return [
        f"{builder.id} re-seats the input model's principals over the input "
        f"model's material, so the binder inventory must not change, but this "
        f"edit " + " and ".join(parts) + ". Reuse the input model's existing "
        f"values — a value shared between two principals is one value in every "
        f"seat and every lookup order — instead of minting or dropping "
        f"bindings."]


def builder_steps(world_entries) -> list[tuple[str, object, str]]:
    """The live steps for this world, in build order, as
    ``(axis, builder, statement)``. Entries are grouped by axis because one
    axis is one build: a per-instance axis names one principal per entry and
    the statement needs all of them at once, since the enumeration it produces
    has to be exactly the named set. Raises NodeError when one axis is answered
    with more than one subtype."""
    by_axis: dict[str, list] = {}
    for e in world_entries:
        by_axis.setdefault(e.axis, []).append(e)
    steps: list[tuple[str, object, str]] = []
    for axis in WORLD_VOCAB.axes():                       # the total build order
        group = by_axis.get(axis)
        if not group:
            continue
        subtypes = {e.subtype for e in group}
        if len(subtypes) > 1:
            raise NodeError(
                f"build_world: axis {axis} is answered with {sorted(subtypes)} "
                f"in one world; a run analyses one world, so an axis holds one "
                f"value across every object it names")
        value, = subtypes
        builder = builder_for(axis, value)
        key = WORLD_VOCAB.instance_key(axis)
        if key:
            field, = key
            names = ", ".join(str((e.target or {})[field]) for e in group)
            statement = f"{axis} = {value}; principals = {names}"
        else:
            statement = f"{axis} = {value}"
        steps.append((axis, builder, statement))
    return steps


def dropped_stable_values(names: list[str], base_pv: str,
                          new_pv: str) -> list[str]:
    """The semantic inventory's names present in ``base_pv`` and gone from
    ``new_pv``. A world assumption re-seats and restructures, but every stable
    value keeps its exact name, named derived bindings included, because fixed
    assumptions, scenario conditions and goals all address the model through
    those names."""
    base_pv, new_pv = blank_comments(base_pv), blank_comments(new_pv)
    return [n for n in names
            if re.search(rf"\b{re.escape(n)}\b", base_pv)
            and not re.search(rf"\b{re.escape(n)}\b", new_pv)]


def _stable_value_names(env: RunEnv) -> list[str]:
    d = env.layout.find_node_dir("extract_principals")
    p = None if d is None else d / "principals.json"
    if p is None or not p.is_file():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    return [v["name"] for v in doc.get("values", [])]


async def build_steps(env: RunEnv, steps, runner, start_pv: str,
                      notes: list[str], *, home: Path,
                      step_messages: str = "") -> str:
    """Run the live builder steps serially, one sighted session each, on the
    reuse/transcript layout the apply engine uses. Returns the resulting model
    text; raises NodeError if a step's agent fails or leaves no model."""
    lang = env.config.get("prompt_lang", "en")
    submit = SubmitSpec(kind="tool", schema=_SCHEMA)
    stable_names = _stable_value_names(env)
    pv = start_pv
    for pos, (field, builder, statement) in enumerate(steps, start=1):
        done = env.layout.find_apply_point_dir(home, field)
        what = env.plan(f"build_world/apply/{field}", done,
                        done is not None and (done / "applied.pv").exists())
        if what == "skip":
            pv = (done / "applied.pv").read_text(encoding="utf-8")
            notes.append(f"{pos:02d} {field} = {statement.split(';')[0].split('=')[1].strip()}: "
                         f"reused (still current, in {done.name})")
            continue
        # An unfinished point carries on in its own directory, session and
        # all (RunEnv.plan), rather than opening another and losing its rounds.
        point_dir = (done if what == "carry"
                     else env.layout.open_apply_point(home, field))
        done_pv = point_dir / "applied.pv"
        transcript = env.layout.apply_transcript(home, field)
        unit = unit_name(home, transcript.parent)
        resume = resume_messages(transcript)
        writer = TranscriptWriter(transcript)
        own_facts = fact_store.read(point_dir)
        rules = builder.sys_prompt(lang)
        system = render_system(__file__, localized("build.sys.md", lang),
                               cut_after=[], cut_after_prefix=True,
                               pv=pv, rules=rules)
        if resume is None:
            writer.meta(node="build_world", scenario="world", assumption=field,
                        step="build",
                        model=env.config["llm"].get("model", "?"),
                        effort=_BUILD_EFFORT)
            user = render_prompt(__file__, localized("build.user.md", lang),
                                 statement=statement,
                                 step_messages=step_messages + messages_section(
                                     [f.text for f in own_facts]))
        else:
            user = resume_user(submit)

        ctx = ToolContext(node="build_world", doc_set=env.doc_set,
                          artifacts_root=env.layout.run_dir,
                          tool_return_chars=env.config["agent"]["tool_return_chars"])
        rounds = RoundLog(transcript.parent)
        final = {"pv": None}
        base_pv = pv
        emit = env.emitter("build_world", scenario="world", unit=unit)

        def _framework(text: str) -> None:
            if emit is not None:
                emit(FrameworkAction(run="", text=text))

        async def _accept(submission, fences, base_pv=base_pv):
            rounds.submission(submission)
            try:
                edits = [Edit(anchor=e["anchor"], position=e["position"],
                              text=e["text"])
                         for e in submission["edits"]]
            except (KeyError, TypeError) as exc:
                return [f"edits entry malformed: {exc}"]
            try:
                new_pv = apply_edits(base_pv, edits)
            except EditError as exc:
                _framework(f"tried to splice {len(edits)} edit(s) — one anchor "
                           f"did not match, nothing assembled")
                return [str(exc)]
            _framework(f"spliced {len(edits)} edit(s) into the model "
                       f"({len(base_pv.splitlines())} → "
                       f"{len(new_pv.splitlines())} lines), then ran the "
                       f"scenario checks on the result")
            rounds.begin(new_pv)
            problems = inventory_violations(builder, base_pv, new_pv)
            if not problems:
                dropped = dropped_stable_values(stable_names, base_pv, new_pv)
                if dropped:
                    problems = [
                        f"this rewrite dropped stable named value(s) "
                        f"{dropped}; every value in the semantic inventory "
                        f"keeps its exact name — a named derived binding such "
                        f"as `let pk_U = spk(sk_U)` stays verbatim, and new "
                        f"members are added beside the named principals, "
                        f"never in their place"]
            if not problems:
                problems = must_failures(await run_checks(
                    SCENARIO_CHECK_NAMES,
                    {"pv": new_pv, "runner": runner, "pv_log": rounds.stem},
                    on=check_sink(emit)))
            rounds.finish(problems)
            if problems:
                problems = list(problems) + [assembled_context(new_pv)]
            else:
                final["pv"] = new_pv
            return problems

        result = await run_agent(
            env.llm(), system=system, user=user, emitter=emit,
            tools=SCENARIO_TOOLS, ctx=ctx, submit=submit,
            accept=_accept, budget=env.budget(), writer=writer,
            resume_from=resume, effort=_BUILD_EFFORT,
        )
        if result.status != "ok":
            raise NodeError(f"build_world {field}: {result.status}: {result.failure}")
        if final["pv"] is None:
            raise NodeError(f"build_world {field}: accepted submission left no "
                            f"assembled model (framework defect)")
        pv = final["pv"]
        write_text(done_pv, pv)
        notes.append(f"{pos:02d} {field}: built ({builder.id})")
    return pv
