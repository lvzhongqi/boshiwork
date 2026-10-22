"""8.3 solve: run ProVerif on one cell and split the verdicts back to their
goals by naming anchor. Pure code, and the only source of a verdict.

Three ordered forms, all derived from the untagged ``model.pv``:
``01_proverif.pv`` asks every goal with ``set reconstructTrace = false.``;
each unproved goal then gets ``02_proverif_trace_<goal>.pv`` carrying that
goal alone at ProVerif's bounded default; one still ``cannot_be_proved`` gets
``03_proverif_precise_<goal>.pv`` with ``set preciseActions = true.``.

A retry changes only ``unknown``, and only a repeated ``cannot_be_proved``
advances to the precise pass. The vacuity pass changes only ``true``: a goal
whose observation point is unreachable is proved on no traces, and is recorded
``vacuous``. A syntax error here is a framework bug, since the inject checks
already guaranteed the syntax.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from orrery.infra.proverif.outcome import OutcomeKind, classify
from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.pvtext.edits import replace_queries
from orrery.modules.pvtext.parse import (
    blank_comments, queries, query_owner_hints, query_owners,
)
from orrery.modules.pvtext.vacuity import (
    observation_points, unreachable, vacuity_form, vacuous_goals,
)
from orrery.modules.verdicts.split import split_by_goal, weak_secret_verdict
from orrery.nodes.base import NodeError
from orrery.services.events import FrameworkAction, SolveFinished

#: The first pass asks only whether the Horn abstraction proves the goals, and
#: does not pay to turn contradicting derivations into concrete process traces.
NO_TRACE = "set reconstructTrace = false.\n"

#: Prepended to the precise retry. ProVerif's imprecise default merges the
#: branches of a `let` destructuring, which is what leaves a query stuck at
#: cannot_be_proved on a model whose roles test what they received.
PRECISE = "set preciseActions = true.\n"


def _goal_source(pv: str, goal_ids: list[str], gid: str, *, where: str,
                 special_goal: str | None = None,
                 owner_hints: dict[str, list[str]] | None = None) -> str:
    """The untagged base model restricted to ``gid``'s own queries.

    Equivalence and weaksecret injectors already emit a one-goal file whose
    statements are not ordinary ``query`` declarations, so ``special_goal``
    returns ``pv`` unchanged. Raises NodeError if no query carries ``gid``.
    """
    if special_goal is not None:
        if goal_ids != [gid] or special_goal != gid:
            raise NodeError(
                f"solve[{where}]: special solve file must have exactly its one "
                f"owning goal {special_goal}, got {goal_ids}")
        return pv
    mine = [q for q in queries(pv)
            if query_owners(q, goal_ids, owner_hints) == [gid]]
    if not mine:
        raise NodeError(
            f"solve[{where}]: goal {gid} came back cannot_be_proved but no query in "
            f"the model carries its ownership anchor; generated query names must "
            f"contain goal.id and direct queries must carry their trailing id comment")
    return replace_queries(pv, mine)


def _special_verdict(out, gid: str, *, where: str,
                     equivalence: bool = False,
                     weaksecret: bool = False,
                     owner_hints: dict[str, list[str]] | None = None) -> str:
    """Read the one ownerless ProVerif verdict family used by a special goal."""
    if equivalence:
        matches = [v for v in out.verdicts
                   if v.query.strip().lower() == "observational equivalence"]
        if len(matches) != 1:
            raise NodeError(
                f"solve[{where}]: expected exactly one observational-equivalence "
                f"verdict, found {len(matches)}")
        return ("unknown" if matches[0].verdict == "cannot_be_proved"
                else matches[0].verdict)
    if weaksecret:
        try:
            return weak_secret_verdict(out.verdicts, where=f"solve[{where}]")
        except RuntimeError as e:
            raise NodeError(str(e)) from None
    return split_by_goal(out.verdicts, [gid], where=where,
                         owner_hints=owner_hints)[gid]


async def _retry_one(runner: ProVerifRunner, pv: str, goal_ids: list[str],
                     gid: str, *, cell_dir: Path, budget_s: int,
                     where: str, log_name: str, prefix: str = "",
                     special_goal: str | None = None,
                     equivalence: bool = False,
                     weaksecret: bool = False,
                     owner_hints: dict[str, list[str]] | None = None,
                     ) -> tuple[str, bool]:
    """Run one undecided goal from the untagged base model.

    The file keeps the whole model and drops only the other goals' queries, so
    the same protocol under the same assumptions is solved. Returns
    ``(verdict, still_cannot_be_proved)``; the second component gates the
    precise pass, so timeout, solver limit and silence keep the provisional
    unknown without authorising another retry.
    """
    source = _goal_source(pv, goal_ids, gid, where=where,
                          special_goal=special_goal,
                          owner_hints=owner_hints)
    raw = await runner.run(prefix + source,
                           log_to=cell_dir / log_name,
                           timeout_s=budget_s)
    out = classify(raw)
    if out.kind is OutcomeKind.SYNTAX_ERROR:
        raise NodeError(
            f"solve[{where}/{gid}]: a syntax error appeared in a mechanically "
            f"derived retry file: {out.errors[:3]}")
    if out.kind is not OutcomeKind.OK or not out.verdicts:
        return "unknown", False
    verdict = _special_verdict(
        out, gid, where=f"{where}/{log_name}", equivalence=equivalence,
        weaksecret=weaksecret, owner_hints=owner_hints)
    still_cannot = verdict == "unknown" and any(
        v.verdict == "cannot_be_proved" for v in out.verdicts)
    return verdict, still_cannot


async def _vacuity(runner: ProVerifRunner, pv: str, goal_ids: list[str],
                   proved: list[str], *, cell_dir: Path, budget_s: int,
                   where: str) -> tuple[list[str], str]:
    """The goals among ``proved`` whose observation point can never be reached,
    plus a note fragment.

    All points are asked in one run: they are independent queries over one
    model. A run that reaches no verdict changes nothing, since silence is not
    evidence that a point is unreachable.
    """
    wanted = set(proved)
    points = [(label, q) for label, q in observation_points(pv)
              if (who := query_owners(label, goal_ids)) and len(who) == 1
              and who[0] in wanted]
    if not points:
        return [], "no observation point to ask about"
    raw = await runner.run(vacuity_form(pv, points),
                           log_to=cell_dir / "proverif_vacuity",
                           timeout_s=budget_s)
    out = classify(raw)
    if out.kind is not OutcomeKind.OK or not out.verdicts:
        return [], f"the vacuity pass reached no verdict ({out.kind.value}); no verdict was changed"
    dead = unreachable(out.verdicts, points)
    hits = vacuous_goals(dead, points, proved)
    return hits, (f"vacuous: {', '.join(hits)}" if hits
                  else f"all {len(points)} observation point(s) reachable")


async def solve_grid(runner: ProVerifRunner, pv: str, goal_ids: list[str],
                     *, name: str, cell_dir: Path, precise_retry: bool = True,
                     trace_retry_timeout_s: int = 100,
                     precise_retry_timeout_s: int = 100,
                     vacuity_check: bool = True, vacuity_timeout_s: int = 120,
                     cell: str = "", emit: Callable | None = None,
                     equivalence_goal: str | None = None,
                     weaksecret_goal: str | None = None,
                     ) -> tuple[dict[str, str], str]:
    """Returns ({goal_id: verdict}, a note on how it was handled). A verdict is
    one of true / false / unknown / vacuous.

    ``pv`` must be an untagged solve input: a reconstructTrace or
    preciseActions setting in it is rejected. ``cell_dir`` collects the
    evidence in execution order, ``01_proverif.*`` then the per-goal trace and
    precise retry files. ``emit`` is a plain callback because a coroutine has
    no env; without one the step is silent."""
    def announce(kind: OutcomeKind, verdicts: dict[str, str], seconds: float,
                 retried: bool = False) -> None:
        if emit is not None:
            emit(SolveFinished(run="", cell=cell or name, kind=kind.value,
                               seconds=round(seconds, 1), verdicts=verdicts,
                               retried=retried))

    def starting(text: str) -> None:
        """Announce a step before the solver is handed the model, not after it
        answers, so a live run shows that solving is still under way."""
        if emit is not None:
            emit(FrameworkAction(run="", text=text))

    controls = blank_comments(pv)
    if (re.search(r"\bset\s+reconstructTrace\s*=", controls)
            or re.search(r"\bset\s+preciseActions\s*=", controls)):
        raise NodeError(
            f"solve[{name}]: model.pv must be an untagged solve input; "
            f"reconstructTrace and preciseActions belong to derived solver files")
    owner_hints = query_owner_hints(pv, goal_ids)

    starting(f"{cell or name}: handed to ProVerif without trace reconstruction — "
             f"{len(goal_ids)} goal(s), {len(pv.splitlines())} lines")
    raw = await runner.run(NO_TRACE + pv, log_to=cell_dir / "01_proverif")
    out = classify(raw)
    if out.kind is OutcomeKind.SYNTAX_ERROR:
        announce(out.kind, {}, raw.duration_s)
        raise NodeError(f"solve[{name}]: a syntax error should not survive to this step (the inject "
                        f"checks guarantee it): {out.errors[:3]}")
    if out.kind in (OutcomeKind.TIMEOUT, OutcomeKind.SOLVER_LIMIT,
                    OutcomeKind.RESOURCE_LIMIT):
        # The outcome's own name, not "unknown": "unknown" is ProVerif saying
        # it cannot prove the goal, which is an answer about the model. Here
        # the solver said nothing at all.
        no_answer = {g: out.kind.value for g in goal_ids}
        announce(out.kind, no_answer, raw.duration_s)
        return (no_answer,
                f"{out.kind.value}: the solver reached no verdict; every goal recorded "
                f"{out.kind.value}, no repair round")

    if equivalence_goal is not None:
        if goal_ids != [equivalence_goal]:
            raise NodeError(
                f"solve[{name}]: observational equivalence requires exactly its "
                f"one owning goal, got {goal_ids}")
        verdict = _special_verdict(out, equivalence_goal, where=name,
                                   equivalence=True)
        if verdict == "unknown":
            starting(f"{cell or name}/{equivalence_goal}: cannot_be_proved — "
                     f"restoring bounded trace reconstruction "
                     f"({trace_retry_timeout_s}s)")
            verdict, _ = await _retry_one(
                runner, pv, goal_ids, equivalence_goal, cell_dir=cell_dir,
                budget_s=trace_retry_timeout_s, where=name,
                log_name=f"02_proverif_trace_{equivalence_goal}",
                special_goal=equivalence_goal, equivalence=True,
                owner_hints=owner_hints)
        answer = {equivalence_goal: verdict}
        announce(out.kind, answer, raw.duration_s)
        return answer, "observational equivalence; one goal in its own biprocess file"

    if weaksecret_goal is not None:
        if goal_ids != [weaksecret_goal]:
            raise NodeError(
                f"solve[{name}]: weaksecret analysis requires exactly its one "
                f"owning goal, got {goal_ids}")
        verdict = _special_verdict(out, weaksecret_goal, where=name,
                                   weaksecret=True)
        if verdict == "unknown":
            starting(f"{cell or name}/{weaksecret_goal}: cannot_be_proved — "
                     f"restoring bounded trace reconstruction "
                     f"({trace_retry_timeout_s}s)")
            verdict, _ = await _retry_one(
                runner, pv, goal_ids, weaksecret_goal, cell_dir=cell_dir,
                budget_s=trace_retry_timeout_s, where=name,
                log_name=f"02_proverif_trace_{weaksecret_goal}",
                special_goal=weaksecret_goal, weaksecret=True,
                owner_hints=owner_hints)
        weak_count = sum(
            v.query.strip().lower().startswith("weak secret ")
            for v in out.verdicts)
        answer = {weaksecret_goal: verdict}
        announce(out.kind, answer, raw.duration_s)
        return answer, (f"weaksecret; {weak_count} value verdict(s) combined in "
                        "one goal-only file")

    verdicts = split_by_goal(out.verdicts, goal_ids, where=name,
                             owner_hints=owner_hints)
    note = "ok"
    seconds = raw.duration_s
    # split_by_goal folds cannot_be_proved into unknown, and on an OK run
    # unknown is its only undecided value, so this is the retry set.
    undecided = [g for g in goal_ids if verdicts[g] == "unknown"]
    still_cannot: list[str] = []
    trace_settled: list[str] = []
    for gid in undecided:
        starting(f"{cell or name}/{gid}: cannot_be_proved — restoring bounded "
                 f"trace reconstruction ({trace_retry_timeout_s}s)")
        verdict, retryable = await _retry_one(
            runner, pv, goal_ids, gid, cell_dir=cell_dir,
            budget_s=trace_retry_timeout_s, where=name,
            log_name=f"02_proverif_trace_{gid}", owner_hints=owner_hints)
        if verdict != "unknown":
            verdicts[gid] = verdict
            trace_settled.append(f"{gid}={verdict}")
        elif retryable:
            still_cannot.append(gid)

    precise_settled: list[str] = []
    if precise_retry:
        for gid in still_cannot:
            starting(f"{cell or name}/{gid}: still cannot_be_proved — handed to "
                     f"ProVerif with preciseActions ({precise_retry_timeout_s}s)")
            verdict, _ = await _retry_one(
                runner, pv, goal_ids, gid, cell_dir=cell_dir,
                budget_s=precise_retry_timeout_s, where=name,
                log_name=f"03_proverif_precise_{gid}", prefix=PRECISE,
                owner_hints=owner_hints)
            if verdict != "unknown":
                verdicts[gid] = verdict
                precise_settled.append(f"{gid}={verdict}")

    if undecided:
        note = (f"ok (trace retry on {len(undecided)} provisional goal(s)"
                + (f"; settled {', '.join(trace_settled)}" if trace_settled
                   else "; none settled")
                + (f"; preciseActions retry on {len(still_cannot)} goal(s)"
                   if precise_retry else "; preciseActions retry disabled")
                + (f"; settled {', '.join(precise_settled)}"
                   if precise_settled else "") + ")")

    # After the retries, because a retry can turn an unknown into a true and
    # true is the only verdict vacuity can act on.
    proved = [g for g in goal_ids if verdicts[g] == "true"]
    if vacuity_check and proved:
        starting(f"{cell or name}: {len(proved)} goal(s) proved — asking whether "
                 f"their observation points are reachable at all")
        hits, why = await _vacuity(runner, pv, goal_ids, proved, cell_dir=cell_dir,
                                   budget_s=vacuity_timeout_s, where=name)
        for gid in hits:
            verdicts[gid] = "vacuous"
        note += f"; vacuity check: {why}"

    announce(out.kind, verdicts, seconds, bool(undecided))
    return verdicts, note
