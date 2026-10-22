"""A small run for the attack reproduction tests: the toy protocol's claims,
three scenarios, four false cells, and stand-ins for the model and the solver
(the solver draws a real attack graph, Lowe's attack on NSPK)."""

import json
import shutil
from pathlib import Path

from orrery.infra.llm.client import ChatClient, ChatResponse, Role, TokenUsage
from orrery.infra.proverif.runner import RawRun
from orrery.modules.attacks.reproduce import LONG
from orrery.nodes.base import RunEnv
from orrery.pipeline.config import DEFAULTS
from orrery.services.store.atomic import write_json, write_text
from orrery.services.store.layout import RunLayout
from tests.fixtures import ATTACK_GRAPHS, CLAIMS

VERDICTS = {
    "baseline": {"secrecy_i_a": "true", "secrecy_i_b": "true",
                 "auth_a_to_b": "true", "auth_b_to_a": "true"},
    "peer_key_attacker_supplied": {"secrecy_i_a": "false", "secrecy_i_b": "false",
                                   "auth_a_to_b": "true", "auth_b_to_a": "false"},
    "shared_key_leaked": {"auth_b_to_a": "false"},
}
FAMILY = {"secrecy_i_a": "Secrecy", "secrecy_i_b": "Secrecy",
          "auth_a_to_b": "Authentication", "auth_b_to_a": "Authentication"}


def query(goal: str) -> str:
    if goal.startswith("secrecy"):
        return f"not attacker(witness_{goal}[])"
    return f"event(end_{goal}(x)) ==> event(begin_{goal}(x))"


def build_run(tmp_path, *, missing: str = "", replay: str = ""):
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    claims = lay.open_node("extract_claims")
    for name in ("assumptions.json", "claims.json", "properties.json"):
        shutil.copy(CLAIMS / name, claims / name)
    lay.open_node("scenarios")
    for label, verdicts in VERDICTS.items():
        home = lay.open_scenario(label)
        write_json(home / "verdict.json", {"verdicts": verdicts})
        for family in sorted({FAMILY[g] for g in verdicts}):
            fam = lay.open_inject_family(label, family)
            for goal, v in verdicts.items():
                if FAMILY[goal] != family or v != "false" \
                        or (label, goal) == ("shared_key_leaked", missing):
                    continue
                write_text(fam / f"02_proverif_trace_{goal}.pv", "process 0\n")
                text = f"RESULT {query(goal)} is false.\n"
                if goal == replay:
                    text += f"RESULT (but {query(goal)} is true.)\n"
                write_text(fam / f"02_proverif_trace_{goal}.txt", text)
    lay.open_node("aggregate")
    lay.open_node("cross_check")
    lay.open_node("reproduce_attacks")      # the pipeline's _prepare does this
    return lay


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, ev):
        self.events.append(ev)


class Writer(ChatClient):
    """Explains whatever it is handed: a note for every step number in the
    script, and every summary input cell in one group. ``fail`` names cells
    whose explanation it refuses to submit."""

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.users = []

    async def invoke(self, messages, tools=None, tool_choice=None,
                     temperature=None, response_format=None, json_schema=None,
                     **kw):
        user = next(m.content for m in messages if m.role == Role.USER)
        self.users.append(user)
        body = user.split("<input>")[1].split("</input>")[0]
        if "Group these failures" in user:
            cells = [ln for ln in body.split("\n") if "/" in ln and " " not in ln]
            args = {"groups": [{"problem": "one weakness", "cells": cells}],
                    "summary": f"{len(cells)} cell(s), one problem"}
        else:
            scenario = user.split("Scenario: ")[1].split("\n")[0]
            goal = user.split("The goal that does not hold:\n")[1].split(" ")[0]
            if f"{scenario}/{goal}" in self.fail:
                return ChatResponse(content="I will not.", usage=TokenUsage())
            numbers = [int(ln.split(".")[0]) for ln in body.split("\n")
                       if ln[:1].isdigit()]
            args = {"opening": "the attacker is registered",
                    "steps": [{"n": n, "note": f"step {n}"} for n in numbers],
                    "conclusion": f"{goal} fails in {scenario}"}
        return ChatResponse(content="", usage=TokenUsage(), tool_calls=[{
            "id": "c1", "type": "function", "name": "submit",
            "arguments": json.dumps(args), "arguments_json": args}])


def attack_env(lay, *, ground_truth=None, writer=None, **attacks):
    config = json.loads(json.dumps(DEFAULTS))
    config["attacks"].update(attacks)
    config["proverif"]["executable"] = "proverif"
    config["llm"]["model"] = "stand-in"
    env = RunEnv(protocol_dir=lay.root, layout=lay, config=config,
                 ground_truth=ground_truth, bus=Bus(), protocol_id="TOY")
    env._llm = writer or Writer()
    return env


class Solver:
    """Answers false for whatever goal it is handed and draws the graph."""

    def __init__(self, *, graph="nspk_auth.dot", long_times_out=False):
        self.graph, self.long_times_out = graph, long_times_out
        self.calls = []

    async def run(self, pv, log_to, extra_args=(), timeout_s=None):
        # like the real runner: the source and the output land beside log_to
        self.calls.append(pv)
        write_text(Path(f"{log_to}.pv"), pv)
        long = pv.startswith(LONG)
        if long and self.long_times_out:
            write_text(Path(f"{log_to}.txt"), "")
            return RawRun(stdout="", stderr="", returncode=-1, duration_s=1.0,
                          timed_out=True)
        goal = Path(log_to).parent.name
        write_text(Path(f"{log_to}.txt"), f"1st process: long display\n"
                                          f"RESULT {query(goal)} is false.\n")
        where = Path(extra_args[extra_args.index("-graph") + 1])
        source = ATTACK_GRAPHS / self.graph if self.graph else None
        (where / "trace1.dot").write_text(
            source.read_text() if source else "digraph { what is this }")
        return RawRun(stdout=f"RESULT {query(goal)} is false.\n", stderr="",
                      returncode=0, duration_s=0.3, timed_out=False)
