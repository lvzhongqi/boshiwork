"""Apply assumption points to a model, one auditable unit per point.

The scenario stage applies each scenario's conditions one point per session;
``build_root`` does the same for fixed points, except that fixed data points
sharing a subtype and writing form go into one batched session. Identity,
directory and the scoped user-instruction block come from the caller.

Application is serial within one identity; concurrency across scenarios
belongs to pipeline/scenarios. A point writes
``<home>/apply/<NN>_<rid>/applied.pv``; a batch shares one directory and lists
its assumption ids in ``members.json``.

The model submits anchored edits, not a rewritten file. System block 1 is the
current model text — byte-identical across sessions starting from the same
text, which is what the prompt cache keys on — and block 2 is the realizer's
rules. The framework splices the edits (modules/pvtext/anchored) and runs the
SCENARIO checks; bad anchors, failing checks and an exhausted repair budget
surface as NodeError.
"""

from __future__ import annotations

import json
from pathlib import Path

import orrery.checks.rules.scenario  # noqa: F401  importing registers the checks
from orrery.agent.compose import (
    assembled_context, localized, render_prompt, render_system, resume_user,
    step_messages as messages_section,
)
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.infra.llm.client import Effort
from orrery.agent.tools import SCENARIO_TOOLS
from orrery.agent.tools.context import ToolContext
from orrery.checks.registry import must_failures, run_checks
from orrery.checks.rules.scenario import SCENARIO_CHECK_NAMES
from orrery.modules.pvtext.anchored import Edit, EditError, apply_edits
from orrery.modules.pvtext.lifetime import value_lifetime
from orrery.nodes.apply.realizers import check_writing_coverage, realizer_for
from orrery.nodes.apply.realizers.base import target_text
from orrery.nodes.base import NodeError, RoundLog, RunEnv
from orrery.services import facts as fact_store
from orrery.services.events import FrameworkAction, check_sink
from orrery.services.store.atomic import write_json, write_text
from orrery.services.store.layout import unit_name
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter

# Encoding rewrites the model under the realizer's rules, so a wrong rewrite
# changes what every later verdict is about. The scenario checks pass either
# way: whether the edit covered every value the assumption names is outside
# what they can see.
_ENCODE_EFFORT = Effort.MEDIUM

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

_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "coverage": {
            "type": "array", "minItems": 1,
            "description": (
                "one row per fixed data assumption in this batch; it is an "
                "audit record that every named assumption was encoded by the "
                "shared edits"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "assumption": {
                        "type": "string",
                        "description": "the assumption id exactly as the input spells it",
                    },
                    "model_term": {
                        "type": "string",
                        "description": (
                            "the exact term or binding in the current model used for "
                            "this assumption"
                        ),
                    },
                    "evidence": {
                        "type": "string",
                        "description": (
                            "a short quote or explanation locating that term in the model"
                        ),
                    },
                },
                "required": ["assumption", "model_term", "evidence"],
                "additionalProperties": False,
            },
        },
        "edits": {
            "type": "array", "minItems": 1, "items": _EDIT_ITEM,
            "description": (
                "one combined edit set for the complete batch; merge compatible "
                "changes instead of repeatedly replacing the same main-process anchor"
            ),
        },
    },
    "required": ["coverage", "edits"],
    "additionalProperties": False,
}

def build_encode_prompt(pv: str, realizer, target: dict | None, *,
                        form: str | None = None,
                        step_messages: str = "", lang: str = "en") -> Prompt:
    """The encoding round's request: the session that rewrites the model.
    Pure, so the prompt preview and the run render the same bytes."""
    # ``form`` selects which rules go into system block 2; the name itself is
    # a code identity and stays out of the prompt, since the session has
    # exactly one writing in front of it.
    return Prompt(
        system=render_system(__file__, localized("encode.sys.md", lang),
                             cut_after=[], cut_after_prefix=True, pv=pv,
                             rules=realizer.sys_prompt(form, lang=lang)),
        user=render_prompt(__file__, localized("encode.user.md", lang),
                           target=target_text(target, realizer.params),
                           step_messages=step_messages),
        submit=SubmitSpec(kind="tool", schema=_SCHEMA),
        label=f"apply encode {realizer.id}" + (f" ({form})" if form else ""),
    )


def build_batch_encode_prompt(pv: str, realizer, points, *,
                              form: str | None = None,
                              step_messages: str = "", lang: str = "en") -> Prompt:
    """One fixed-layer call covering several encoding-compatible data points.

    Every point in ``points`` shares the realizer and the writing form. All
    ids and targets go into one request, so the model can merge edits that
    attach to the same main-process branch.
    """
    assumptions = [
        {
            "id": rid_of(point, realizer),
            "target": target_text(point.target, realizer.params),
        }
        for point in points
    ]
    return Prompt(
        system=render_system(__file__, localized("encode_batch.sys.md", lang),
                             cut_after=[], cut_after_prefix=True, pv=pv,
                             rules=realizer.sys_prompt(form, lang=lang)),
        user=render_prompt(
            __file__, localized("encode_batch.user.md", lang),
            assumptions_json=json.dumps(assumptions, ensure_ascii=False, indent=2),
            step_messages=step_messages),
        submit=SubmitSpec(kind="tool", schema=_BATCH_SCHEMA),
        label=(f"apply fixed data batch {realizer.id}"
               + (f" ({form})" if form else "")),
    )


def rid_of(p, realizer) -> str:
    """A point's identity: the assumption it came from, or the realizer id.

    Not the subtype — one protocol can apply the same subtype to two different
    targets, and the number leading the directory is execution order, so the
    name is the only part left that can tell the two points apart.
    """
    return p.ref_id or realizer.id


def check_rids(points, realizers) -> None:
    """Refuse a chain whose points cannot be told apart by name.

    Corpus points carry the assumption's own id and assumptions.json rejects
    duplicates, so this only fires for engine-built points falling back to the
    same ``axis.subtype``. Raises NodeError on a collision: two points sharing
    a directory name would read as a re-work of one point.
    """
    seen: dict[str, object] = {}
    for p, r in zip(points, realizers):
        rid = rid_of(p, r)
        if rid in seen:
            raise NodeError(
                f"two apply points in one chain are both called {rid!r} "
                f"({seen[rid]} and {p}); a point is addressed by the "
                f"assumption it came from, so they must differ")
        seen[rid] = p


def fixed_data_groups(points, pv: str):
    """Group fixed data points that one encoding call may safely share.

    A group has one subtype and one mechanically selected writing form:
    different subtypes carry different semantic rules, and different writings
    touch different ProVerif syntax. Code realizers stay singleton groups.
    Raises NodeError on a non-data point or an undeclared writing form.
    """
    groups: dict[tuple[str, str | None, str | None], list] = {}
    realizers = [realizer_for(p.axis, p.subtype) for p in points]
    check_rids(points, realizers)
    for point, realizer in zip(points, realizers):
        if point.axis != "data":
            raise NodeError(
                f"fixed data batch received non-data point "
                f"{point.ref_id or realizer.id!r} on axis {point.axis!r}")
        form = None
        if realizer.writings:
            form = realizer.form_from_lifetime(
                value_lifetime(pv, point.target["of"]))
            if form not in realizer.writings:
                raise NodeError(
                    f"fixed data batch {point.ref_id or realizer.id}: "
                    f"form_from_lifetime returned {form!r}, not one of the "
                    f"declared writings {sorted(realizer.writings)}")
        singleton = rid_of(point, realizer) if realizer.is_code else None
        groups.setdefault((realizer.id, form, singleton), []).append(point)
    return [
        (realizer_for(group[0].axis, group[0].subtype), form, group)
        for (_realizer_id, form, _singleton), group in groups.items()
    ]


def _batch_rid(realizer, form: str | None) -> str:
    suffix = f"_{form}" if form else ""
    return f"fixed_data_batch_{realizer.subtype}{suffix}"


def _batch_coverage_problems(submission: dict, wanted: list[str]) -> list[str]:
    """The batch must explicitly account for every fixed assumption once."""
    rows = submission.get("coverage")
    if not isinstance(rows, list):
        return ["coverage must be an array"]
    got = [row.get("assumption") for row in rows if isinstance(row, dict)]
    problems: list[str] = []
    if len(got) != len(rows):
        problems.append("every coverage entry must be an object")
    duplicates = sorted({name for name in got if got.count(name) > 1})
    if duplicates:
        problems.append(f"coverage repeats assumption ids {duplicates}")
    missing = sorted(set(wanted) - set(got))
    extra = sorted(set(got) - set(wanted), key=str)
    if missing:
        problems.append(f"coverage omits fixed assumptions {missing}")
    if extra:
        problems.append(f"coverage names assumptions outside this batch {extra}")
    return problems


async def apply_fixed_data_points(env: RunEnv, points, runner, start_pv: str,
                                  notes: list[str], *, home: Path,
                                  step_path: str,
                                  step_messages: str = "") -> str:
    """Apply fixed data assumptions in encoding-compatible batches.

    Only ``build_root`` calls this. Scenario deltas, one-member groups and
    deterministic (code) realizers go through :func:`apply_points` instead,
    where batching would remove no model call. Returns the resulting model
    text and appends one note line per assumption; raises NodeError when a
    batch cannot pass acceptance.
    """
    if not points:
        return start_pv
    check_writing_coverage(points, start_pv)
    pv = start_pv
    lang = env.config.get("prompt_lang", "en")
    for realizer, form, group in fixed_data_groups(points, pv):
        if len(group) == 1 or realizer.is_code:
            pv = await apply_points(
                env, group, runner, pv, notes, ident="root",
                home=home, step_path=step_path,
                step_messages=step_messages)
            continue

        members = [rid_of(point, realizer) for point in group]
        batch_rid = _batch_rid(realizer, form)
        if batch_rid in members:
            raise NodeError(
                f"fixed data assumption id {batch_rid!r} collides with the "
                "framework's batch identity; rename that assumption")
        done = env.layout.find_apply_point_dir(home, batch_rid)
        what = env.plan(f"{step_path}/apply/{batch_rid}", done,
                        done is not None and (done / "applied.pv").exists())
        if what == "skip":
            pv = (done / "applied.pv").read_text(encoding="utf-8")
            notes.extend(
                f"-- {rid} = {point.subtype}: reused in {batch_rid} "
                f"(still current, in {done.name})"
                for rid, point in zip(members, group)
            )
            continue

        # An unfinished point carries on in its own directory, session and
        # all, the way a node does: opening another would throw away the
        # rounds already paid for and leave a numbered directory behind.
        batch_dir = (done if what == "carry"
                     else env.layout.open_apply_point(home, batch_rid))
        done_pv = batch_dir / "applied.pv"
        transcript = env.layout.apply_transcript(home, batch_rid)
        unit = unit_name(home, transcript.parent)
        resume = resume_messages(transcript)
        writer = TranscriptWriter(transcript)
        own_facts = fact_store.read(batch_dir)
        prompt = build_batch_encode_prompt(
            pv, realizer, group, form=form,
            step_messages=step_messages + messages_section(
                [fact.text for fact in own_facts]),
            lang=lang)
        submit = prompt.submit
        if resume is None:
            writer.meta(node="apply", scenario="root", assumption=batch_rid,
                        assumptions=members, step="encode_batch",
                        model=env.config["llm"].get("model", "?"),
                        effort=_ENCODE_EFFORT)
            user = prompt.user
        else:
            user = resume_user(submit)

        ctx = ToolContext(node="apply", doc_set=env.doc_set,
                          artifacts_root=env.layout.run_dir,
                          tool_return_chars=env.config["agent"]["tool_return_chars"])
        rounds = RoundLog(transcript.parent)
        final = {"pv": None}
        base_pv = pv
        emit = env.emitter("apply", scenario="root", unit=unit)

        def _framework(text: str) -> None:
            if emit is not None:
                emit(FrameworkAction(run="", text=text))

        async def _accept(submission, _fences, base_pv=base_pv,
                          realizer=realizer, group=group):
            rounds.submission(submission)
            problems = _batch_coverage_problems(submission, members)
            if problems:
                return problems
            try:
                edits = [Edit(anchor=e["anchor"], position=e["position"],
                              text=e["text"])
                         for e in submission["edits"]]
            except (KeyError, TypeError) as exc:
                return [f"edits entry malformed: {exc}"]
            try:
                new_pv = apply_edits(base_pv, edits)
            except EditError as exc:
                _framework(f"tried to splice {len(edits)} batch edit(s) — one "
                           "anchor did not match, nothing assembled")
                return [str(exc)]
            _framework(
                f"spliced {len(edits)} edit(s) for {len(group)} fixed data "
                "assumptions into the model, then ran the scenario checks")
            rounds.begin(new_pv)
            problems = realizer.verify_applied(
                base_pv, new_pv, [pt.target or {} for pt in group])
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
            env.llm(), system=prompt.system, user=user, emitter=emit,
            tools=SCENARIO_TOOLS, ctx=ctx, submit=submit,
            accept=_accept, budget=env.budget(), writer=writer,
            resume_from=resume, effort=_ENCODE_EFFORT)
        if result.status != "ok":
            raise NodeError(
                f"apply[root] {batch_rid}: {result.status}: {result.failure}")
        if final["pv"] is None:
            raise NodeError(
                f"apply[root] {batch_rid}: accepted submission left no "
                "assembled model (framework defect)")
        pv = final["pv"]
        write_json(batch_dir / "members.json", {
            "axis": "data", "subtype": realizer.subtype,
            "writing": form, "assumptions": members,
        })
        write_text(done_pv, pv)
        notes.extend(
            f"-- {rid} = {point.subtype}: applied in {batch_rid}"
            for rid, point in zip(members, group)
        )
    return pv


async def apply_points(env: RunEnv, points, runner, start_pv: str,
                       notes: list[str], *, ident: str, home: Path,
                       step_path: str, step_messages: str = "") -> str:
    """Apply ``points`` (already ordered, noops excluded) serially under the
    identity ``ident``, one sighted session per point, appending one note line
    each. Returns the resulting text; raises NodeError when an encoding cannot
    pass acceptance within its repair budget.

    ``home`` is the directory this batch's points land under (the root step's
    node directory, or one scenario's directory), ``step_path`` is how a person
    addresses that same place (``build_root``, ``scenarios/baseline``), and
    ``step_messages`` is the filed-messages block already scoped by the caller.
    All three come from the caller rather than from ``ident``, because two
    different steps call this."""
    realizers = [realizer_for(p.axis, p.subtype) for p in points]
    check_rids(points, realizers)
    # Checked before any session opens: a multi-writing point whose value
    # lifetime maps to no writing is a backend coverage gap.
    check_writing_coverage(points, start_pv)
    submit = SubmitSpec(kind="tool", schema=_SCHEMA)
    pv = start_pv
    for pos, (p, realizer) in enumerate(zip(points, realizers), start=1):
        rid = rid_of(p, realizer)
        # Reuse is decided by the chain's own numbering, not by hashing input:
        # a point is current when its directory is the newest of its identity
        # and it ran after the point before it, so a re-worked point lands with
        # a higher number and staleness propagates forward on its own.
        done = env.layout.find_apply_point_dir(home, rid)
        what = env.plan(f"{step_path}/apply/{rid}", done,
                        done is not None and (done / "applied.pv").exists())
        if what == "skip":
            pv = (done / "applied.pv").read_text(encoding="utf-8")
            notes.append(f"{pos:02d} {rid} = {p.subtype}: reused "
                         f"(still current, in {done.name})")
            continue
        # An unfinished point carries on in its own directory, session and
        # all, the way a node does (RunEnv.plan): opening another would throw
        # away the rounds already paid for and leave a numbered directory
        # behind.
        point_dir = (done if what == "carry"
                     else env.layout.open_apply_point(home, rid))
        done_pv = point_dir / "applied.pv"
        if realizer.is_code:
            try:
                new_pv = realizer.apply_code(pv, p.target)
            except ValueError as exc:
                raise NodeError(
                    f"apply[{ident}] {rid} failed: the assumption cannot be "
                    f"encoded on this model — {exc}"
                ) from exc
            emit = env.emitter(
                "apply", scenario=ident,
                unit=unit_name(home, point_dir),
            )
            if emit is not None:
                emit(FrameworkAction(
                    run="", text="applied the deterministic realizer, then "
                    "ran the scenario checks on the result"
                ))
            rounds = RoundLog(point_dir)
            rounds.begin(new_pv)
            problems = must_failures(await run_checks(
                SCENARIO_CHECK_NAMES,
                {"pv": new_pv, "runner": runner, "pv_log": rounds.stem},
                on=check_sink(emit),
            ))
            rounds.finish(problems)
            if problems:
                raise NodeError(
                    f"apply[{ident}] {rid}: deterministic realization failed "
                    f"scenario checks: {'; '.join(problems)}"
                )
            pv = new_pv
            write_text(done_pv, pv)
            notes.append(f"{pos:02d} {rid} = {p.subtype}: applied (code)")
            continue
        # A multi-writing realizer picks its form from the target value's
        # lifetime; single-writing ones leave the judgement to the session.
        form = None
        if realizer.writings:
            form = realizer.form_from_lifetime(
                value_lifetime(pv, p.target["of"]))
            if form not in realizer.writings:
                raise NodeError(
                    f"apply[{ident}] {rid}: form_from_lifetime returned {form!r}, "
                    f"not one of the declared writings {sorted(realizer.writings)}")
        transcript = env.layout.apply_transcript(home, rid)
        unit = unit_name(home, transcript.parent)
        resume = resume_messages(transcript)
        writer = TranscriptWriter(transcript)
        # The messages block stays the caller's, scoped to the root step or to
        # one scenario name, so a message aimed at one scenario cannot rewrite
        # what another scenario or the shared root model was told. Facts filed
        # against this one point ride after it: the seal that came with the fix
        # is what pushed this point off the reuse path.
        own_facts = fact_store.read(point_dir)
        prompt = build_encode_prompt(
            pv, realizer, p.target, form=form,
            step_messages=step_messages + messages_section(
                [f.text for f in own_facts]),
            lang=env.config.get("prompt_lang", "en"))
        system = prompt.system
        if resume is None:
            writer.meta(node="apply", scenario=ident, assumption=rid,
                        step="encode",
                        model=env.config["llm"].get("model", "?"),
                        effort=_ENCODE_EFFORT)
            user = prompt.user
        else:
            user = resume_user(submit)

        ctx = ToolContext(node="apply", doc_set=env.doc_set,
                          artifacts_root=env.layout.run_dir,
                          tool_return_chars=env.config["agent"]["tool_return_chars"])

        rounds = RoundLog(transcript.parent)
        final = {"pv": None}
        base_pv = pv
        # Bound to this point, so every event it emits carries the unit and
        # cannot be confused with the point running beside it.
        emit = env.emitter("apply", scenario=ident, unit=unit)

        def _framework(text: str) -> None:
            if emit is not None:
                emit(FrameworkAction(run="", text=text))

        async def _accept(submission, fences, base_pv=base_pv, form=form,
                          point=p, realizer=realizer):
            # Recorded first: the three ways out below all end the round
            # without assembling anything.
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
            rounds.begin(new_pv)     # assembled text lands first, then its checks
            problems = realizer.verify_applied(base_pv, new_pv,
                                               [point.target or {}])
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
            env.llm(), system=system, user=user,
            emitter=emit,
            tools=SCENARIO_TOOLS, ctx=ctx,
            submit=submit,
            accept=_accept, budget=env.budget(), writer=writer,
            resume_from=resume, effort=_ENCODE_EFFORT,
        )
        if result.status != "ok":
            raise NodeError(f"apply[{ident}] {rid}: {result.status}: {result.failure}")
        if final["pv"] is None:
            raise NodeError(f"apply[{ident}] {rid}: accepted submission left no "
                            f"assembled model (framework defect)")
        pv = final["pv"]
        # The point's whole completion contract: the file exists, so the point
        # is done. Written last, so a crash part-way through reads as "not
        # done" rather than as a false reuse.
        write_text(done_pv, pv)
        notes.append(f"{pos:02d} {rid} = {p.subtype}: applied"
                     + (f" (writing: {form})" if form else ""))
    return pv


async def apply_scenario(env: RunEnv, label: str, ordered_points, runner,
                         start_pv: str, *,
                         shared_keys=frozenset(),
                         base_label: str | None = None) -> str:
    """Assemble one scenario's scenario.pv and notes.md.

    ``ordered_points`` is the scenario's complete world in apply order; noops
    and points the base already carries are only noted, and the remaining
    delta is applied on ``start_pv`` (the run base, or the flow model when
    there is no fixed layer). Notes cover every point, so the file reads as
    the full assignment. Returns the resulting model text.
    """
    notes: list[str] = []
    delta = []
    n_noop = n_base = 0
    for p in ordered_points:
        realizer = realizer_for(p.axis, p.subtype)
        rid = p.ref_id or realizer.id
        if realizer.is_noop:
            n_noop += 1
            notes.append(f"-- {rid} = {p.subtype}: flow state, unchanged")
        elif p._key() in shared_keys:
            n_base += 1
            notes.append(f"-- {rid} = {p.subtype}: applied in {base_label}")
        else:
            delta.append(p)
    pv = await apply_points(
        env, delta, runner, start_pv, notes, ident=label,
        home=env.layout.scenario_dir(label), step_path=f"scenarios/{label}",
        step_messages=env.facts("scenarios", label))
    # normalise the tail so a zero-delta scenario is byte-identical to its base
    write_text(env.layout.scenario_pv(label), pv.rstrip("\n") + "\n")
    write_text(env.layout.scenario_notes(label), "\n".join(notes) + "\n")
    _emit_summary(env, label,
                  f"apply summary: {len(delta)} applied here, {n_base} from "
                  f"{base_label or 'no base'}, {n_noop} flow-state")
    return pv


def _emit_summary(env: RunEnv, ident: str, text: str) -> None:
    """One stage-summary line into the ledger, so work.md can report how many
    points a scenario applied without reading any artifact."""
    em = env.emitter("apply", scenario=ident)
    if em is None:
        return
    from orrery.services.events.pipeline import NodeProgress
    em(NodeProgress(run="", node="apply", text=text))
