"""The one-shot baseline shares the mainline's solver-only precise retry."""
from __future__ import annotations

import asyncio

from orrery.infra.proverif.outcome import QueryVerdict
from orrery.infra.proverif.runner import ProVerifRunner, RawRun

from experiments.oneshot.runner import _retry_cannot_be_proved


PV = """\
free w_g_a: bitstring [private].
free w_g_b: bitstring [private].
query attacker(w_g_a).
query attacker(w_g_b).
let processA() = 0.
process (!processA())
"""


class Fake(ProVerifRunner):
    def __init__(self):
        super().__init__(executable="/bin/true")
        self.calls = []

    async def run(self, pv, log_to, extra_args=(), timeout_s=None):
        self.calls.append((pv, str(log_to), timeout_s))
        return RawRun(
            stdout="RESULT not attacker(w_g_a[]) is false.\n",
            stderr="", returncode=0, duration_s=2.0, timed_out=False)


def test_only_cannot_be_proved_is_retried_with_precise_actions(tmp_path):
    runner = Fake()
    verdicts, notes, evidence = asyncio.run(_retry_cannot_be_proved(
        pv_runner=runner, out_dir=tmp_path, pv=PV,
        goal_ids=["g_a", "g_b"],
        verdicts={"g_a": "unknown", "g_b": "true"},
        raw_verdicts=[
            QueryVerdict("not attacker(w_g_a[])", "cannot_be_proved"),
            QueryVerdict("not attacker(w_g_b[])", "true"),
        ],
        timeout_s=100))

    assert verdicts == {"g_a": "false", "g_b": "true"}
    assert evidence == {"g_a": {
        "outcome": "ok", "verdict": "false", "duration_s": 2.0}}
    assert "g_a" in " ".join(notes)
    assert len(runner.calls) == 1
    source, log_to, budget = runner.calls[0]
    assert source.startswith("set preciseActions = true.\n")
    assert "attacker(w_g_a)" in source
    assert "attacker(w_g_b)" not in source
    assert log_to.endswith("proverif_precise_g_a")
    assert budget == 100
