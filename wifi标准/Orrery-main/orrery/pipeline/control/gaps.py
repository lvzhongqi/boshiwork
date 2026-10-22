"""Accepting or rejecting a reported gap: five mechanical checks decide, none of
which requires understanding any meaning.

A rejection goes back as a tool_result that resumes the reporter's session; an
acceptance rolls the run back to the target and runs forward from there, so one
flow model underlies the whole run. Acceptances are bounded by ``gap_budget``,
rejections by ``gap_reject_limit`` — past either the run stops rather than
circling.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from orrery.modules.document.search import grep
from orrery.nodes.base import GapRaised, RunEnv
from orrery.services import facts
from orrery.services.store.atomic import append_line, read_jsonl_tolerant
from orrery.services.events import GapReported, GapVerdict
from orrery.services.transcript.prompt import is_session_file
from orrery.services.transcript.writer import TranscriptWriter


def _gaps_path(env: RunEnv):
    return env.layout.gaps_jsonl


def _accepted_count(env: RunEnv) -> int:
    return sum(1 for e in read_jsonl_tolerant(_gaps_path(env))
               if e.get("verdict") == "accepted")


def _rejected_count(env: RunEnv) -> int:
    return sum(1 for e in read_jsonl_tolerant(_gaps_path(env))
               if e.get("verdict") == "rejected")


def _log(env: RunEnv, gap, verdict: str, reason: str) -> None:
    append_line(_gaps_path(env), json.dumps({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "reporter": gap.reporter, "target": gap.target,
        "missing": gap.missing, "evidence": gap.evidence,
        "verdict": verdict, "reason": reason,
    }, ensure_ascii=False))


_MACHINE_SUFFIXES = (".json", ".pv")


def _target_products_text(env: RunEnv, target: str) -> str:
    """The target's current machine artifacts, for the is-it-present check.

    Only the files a downstream step reads (``.json`` / ``.pv``) in the current
    execution's directory. The prose a session writes alongside quotes the
    document, so a concept appearing there says nothing about what the artifact
    actually carries.
    """
    d = env.layout.find_node_dir(target)
    if d is None:
        return ""
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted(d.glob("*"))
                     if p.is_file() and p.suffix in _MACHINE_SUFFIXES
                     and not is_session_file(p.name))


def verify(env: RunEnv, raised: GapRaised, upstream_names: list[str]
           ) -> tuple[bool, str]:
    """The five mechanical checks, returning (accepted?, reason): the target is
    upstream, it is model-driven, the acceptance budget is not spent, the
    missing name is absent from the target's artifact, and it is present in the
    document."""
    gap = raised.gap
    if gap.target not in upstream_names:
        return False, (f"target {gap.target!r} is not upstream of the reporter "
                       f"(upstream: {upstream_names})")
    if gap.target in env.always_run_names:
        return False, (
            f"target {gap.target!r} runs on every pass and re-uses what it "
            f"already left, so sending the run back to it changes nothing. "
            f"Report the gap against the step whose artifact is missing the "
            f"name")
    if gap.target not in env.model_driven_names:
        return False, (
            f"target {gap.target!r} is pure code and reads no messages: its "
            f"artifact is a function of its inputs, so re-running it changes "
            f"nothing. Report the gap against the model-driven step whose "
            f"output it derives from (model-driven: "
            f"{', '.join(env.model_driven_names) or 'none declared'})")
    budget = env.config["pipeline"]["gap_budget"]
    if _accepted_count(env) >= budget:
        return False, f"rollback budget exhausted (gap_budget={budget})"
    products = _target_products_text(env, gap.target)
    if re.search(rf"\b{re.escape(gap.missing)}\b", products):
        return False, (f"{gap.missing!r} is in fact present in {gap.target}'s artifact "
                       f"(\\b{gap.missing}\\b matched); check again, or report a different name")
    if env.doc_set is not None:
        hits = grep(env.doc_set, gap.missing, max_matches=3)
        if "no matches" in hits:
            return False, (f"{gap.missing!r} is not in the document either, so upstream did not miss "
                           f"it; the problem is likely the claims or the spelling "
                           f"(the search is a substring match)")
    return True, "all checks passed"


def process(env: RunEnv, raised: GapRaised, upstream_names: list[str]
            ) -> tuple[str, str]:
    """Verify, record, and apply the side effects; returns
    ("accepted"|"rejected"|"exhausted", reason). A rejection writes the
    diagnosis back into the reporter's transcript as a tool_result so its
    session carries on; exhausted means gap_reject_limit rejections and the
    caller fails the run. An acceptance files a message for the target and
    leaves the rollback to the runner.
    """
    ok, reason = verify(env, raised, upstream_names)
    gap = raised.gap
    if env.bus is not None:
        env.bus.emit(GapReported(run=env.layout.run_name, node=gap.reporter,
                                 target=gap.target, missing=gap.missing))
        env.bus.emit(GapVerdict(run=env.layout.run_name, node=gap.target,
                                accepted=ok, reason=reason))
    if not ok:
        _log(env, gap, "rejected", reason)
        limit = env.config["pipeline"]["gap_reject_limit"]
        if _rejected_count(env) >= limit:
            return "exhausted", (
                f"gap reports rejected {limit} times in this run (latest: {reason}); "
                f"the reporter is circling instead of working, so the run stops here"
            )
        TranscriptWriter(raised.transcript_path).tool_result(
            raised.tool_call_id, "report_gap",
            f"gap rejected: {reason}. Carry on with the current task; if there really "
            f"is a gap, report it again with a concrete searchable name, otherwise "
            f"handle it at the value level (write it correctly and say why).")
        return "rejected", reason
    _log(env, gap, "accepted", reason)
    msg = (f"A downstream node ({gap.reporter}) reports that your artifact is missing "
           f"{gap.missing!r}; document evidence: {gap.evidence}. Check the document: "
           f"if it really is there, add it and resubmit the complete artifact in the "
           f"same format; if it really is not, leave the artifact as it is and say so.")
    # The durable copy: ``open_node`` copies a step's facts into the next
    # execution, so it arrives wherever the re-work lands and a fresh session
    # reads it at prompt build.
    facts.append(env.layout.node_dir(gap.target),
                 source=f"gap:{gap.reporter}", text=msg)
    # Live delivery, only into a transcript that already exists: a resumed
    # session replays that transcript rather than the fact file. A target with
    # no session at this path (a composite step) re-runs fresh and reads the
    # fact; writing a transcript here would leave one no session ever reads.
    tp = env.layout.node_transcript(gap.target)
    if tp.exists():
        TranscriptWriter(tp).user(msg)
    return "accepted", reason


