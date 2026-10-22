"""The weak-secret path: prompt, one-goal batching, injection contract and solve."""

import asyncio
from types import SimpleNamespace

from orrery.infra.proverif.runner import ProVerifRunner, RawRun
from orrery.nodes.inject.injectors import injector_for
from orrery.nodes.inject.node import weaksecret_contract_problems
from orrery.nodes.solve.node import solve_grid
from orrery.pipeline.scenarios import family_batches


def _goal(gid="weak_secret_pi", values=("pi",)):
    return SimpleNamespace(
        id=gid, type="Secrecy",
        subtype="weak_secret_guessing_resistance",
        values=values, parties={"holders": ["A", "B"]})


def test_weaksecret_injector_is_live_and_has_bilingual_rules():
    inj = injector_for("Secrecy", "weak_secret_guessing_resistance")
    assert inj.one_goal_per_file and not inj.unimplemented
    assert "weaksecret password." in inj.sys_prompt("en")
    assert "weaksecret password." in inj.sys_prompt("zh")


def test_each_weaksecret_goal_gets_its_own_file():
    goals = [_goal("weak_a", ("a",)), _goal("weak_b", ("b",))]
    batches = family_batches(
        [("Secrecy", "weak_secret_guessing_resistance", goals)], cap=8)
    assert [(family, [g.id for _, _, gs in cells for g in gs])
            for family, _, cells in batches] == [
        ("Secrecy.weak_secret_guessing_resistance.weak_a", ["weak_a"]),
        ("Secrecy.weak_secret_guessing_resistance.weak_b", ["weak_b"]),
    ]


def test_weaksecret_contract_accepts_only_private_free_values_and_no_edits():
    pv = "free pi: password [private].\nprocess 0\n"
    assert weaksecret_contract_problems(
        pv, ["weaksecret pi."], [], [_goal()]) == []

    wrong = weaksecret_contract_problems(
        "free pi: password.\nprocess 0\n",
        ["weaksecret pi."], [], [_goal()])
    assert any("top-level private free" in p for p in wrong)

    wrong = weaksecret_contract_problems(
        pv, ["query attacker(pi)."], [], [_goal()])
    assert any("may declare only" in p for p in wrong)


def test_solve_attributes_proverif_weak_secret_output_to_the_one_goal(tmp_path):
    class FakeRunner(ProVerifRunner):
        def __init__(self):
            super().__init__(executable="/bin/true", timeout_s=1)

        async def run(self, pv, log_to):
            return RawRun(stdout="RESULT Weak secret pi is true.\n",
                          stderr="", returncode=0, duration_s=0.2,
                          timed_out=False)

    verdicts, note = asyncio.run(solve_grid(
        FakeRunner(), "free pi: password [private].\nweaksecret pi.\nprocess 0",
        ["weak_secret_pi"], name="weak", cell_dir=tmp_path,
        weaksecret_goal="weak_secret_pi"))
    assert verdicts == {"weak_secret_pi": "true"}
    assert "weaksecret" in note


def test_multiple_values_of_one_goal_are_conjoined(tmp_path):
    class FakeRunner(ProVerifRunner):
        def __init__(self):
            super().__init__(executable="/bin/true", timeout_s=1)

        async def run(self, pv, log_to):
            return RawRun(
                stdout=("RESULT Weak secret pin is true.\n"
                        "RESULT Weak secret password is false.\n"),
                stderr="", returncode=0, duration_s=0.2, timed_out=False)

    verdicts, _ = asyncio.run(solve_grid(
        FakeRunner(), "pv", ["weak_credentials"], name="weak",
        cell_dir=tmp_path, weaksecret_goal="weak_credentials"))
    assert verdicts == {"weak_credentials": "false"}
