"""Split ProVerif query verdicts back to the goals that own them.

Ownership comes from the goal.id embedded in a generated query name, or from
the solve layer's hint for a direct query whose trailing id comment ProVerif
discards. An unattributable query, or a goal with no verdict, raises.

A weak-secret goal is the exception: its file declares ``weaksecret`` values
instead of queries, ProVerif answers ``Weak secret <value>`` for each, and the
file holds that one goal and nothing else, so every verdict in it is the
goal's (``weak_secret_verdict``).
"""

from __future__ import annotations

from orrery.infra.proverif.outcome import QueryVerdict
from orrery.modules.pvtext.parse import query_owners


def weak_secret_verdict(verdicts: list[QueryVerdict], *, where: str) -> str:
    """The one goal of a weak-secret file, over all of its values; raises when
    the output holds anything but weak-secret verdicts, or none."""
    weak = [v for v in verdicts
            if v.query.strip().lower().startswith("weak secret ")]
    if not weak or len(weak) != len(verdicts):
        raise RuntimeError(
            f"[verdicts] {where}: expected only weaksecret verdicts in the "
            f"one-goal file, got {[v.query for v in verdicts]}")
    return combine(["unknown" if v.verdict == "cannot_be_proved" else v.verdict
                    for v in weak])


def combine(verdicts: list[str]) -> str:
    """Fold one goal's query verdicts: all true → true, any false → false,
    otherwise unknown, which is where cannot_be_proved lands."""
    if all(v == "true" for v in verdicts):
        return "true"
    if any(v == "false" for v in verdicts):
        return "false"
    return "unknown"


def split_by_goal(
    verdicts: list[QueryVerdict], goal_ids: list[str], *, where: str,
    owner_hints: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """Map one run's verdicts to ``{goal_id: verdict}``.

    goal_ids is passed in because this layer knows nothing of goal objects;
    owner_hints maps a direct query's target to its owner. Raises on an empty
    verdict list, a query no single goal claims, or a goal with no verdict.
    """
    if not verdicts:
        raise RuntimeError(
            f"[verdicts] {where}: ProVerif produced no verdict (syntax or type failure)"
        )
    buckets: dict[str, list[str]] = {gid: [] for gid in goal_ids}
    for qv in verdicts:
        owners = query_owners(qv.query, goal_ids, owner_hints)
        if len(owners) != 1:
            raise RuntimeError(
                f"[verdicts] {where}: cannot tell which goal this query belongs to "
                f"(matched {owners or 'nothing'}, candidates {goal_ids}); the "
                f"injector must embed goal.id in every generated query name or "
                f"tag a direct query with its trailing goal-id comment. "
                f"query: {' '.join(qv.query.split())}"
            )
        buckets[owners[0]].append(qv.verdict)
    missing = [gid for gid, vs in buckets.items() if not vs]
    if missing:
        raise RuntimeError(f"[verdicts] {where}: no verdict at all for goals {missing}")
    return {gid: combine(vs) for gid, vs in buckets.items()}
