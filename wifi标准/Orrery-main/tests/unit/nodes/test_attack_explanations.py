"""The explanation sessions: what they are shown, and what their answers must
satisfy before they are kept. A scripted model plays the writer."""

import asyncio
import json
from pathlib import Path

from orrery.infra.llm.client import ChatClient, ChatResponse, Role, TokenUsage
from orrery.modules.attacks.graph import read
from orrery.modules.attacks.script import build
from orrery.nodes.base import RunEnv
from orrery.nodes.reproduce_attacks.explain import (
    explain_cell, render_script, summarize, unfound_quotes,
)
from orrery.pipeline.config import DEFAULTS
from orrery.services.store.atomic import write_json, write_text
from orrery.services.store.layout import RunLayout
from tests.fixtures import ATTACK_GRAPHS


class _Scripted(ChatClient):
    """Hands back the given submissions in turn and keeps every request."""

    def __init__(self, *submissions):
        self.submissions = list(submissions)
        self.requests = []

    async def invoke(self, messages, tools=None, **kw):
        self.requests.append(list(messages))
        args = self.submissions.pop(0)
        return ChatResponse(content="", usage=TokenUsage(), tool_calls=[{
            "id": f"c{len(self.requests)}", "type": "function", "name": "submit",
            "arguments": json.dumps(args), "arguments_json": args}])


def _env(tmp_path, llm):
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    lay.open_node("reproduce_attacks")
    config = json.loads(json.dumps(DEFAULTS))
    config["llm"]["model"] = "stand-in"
    env = RunEnv(protocol_dir=tmp_path, layout=lay, config=config,
                 protocol_id="NSPK")
    env._llm = llm
    return env


def _cell(env):
    home = env.layout.attack_dir("lowe", "auth_b_to_a", manual=False)
    script = build(read(ATTACK_GRAPHS / "nspk_auth.dot")).to_json()
    write_json(home / "msc.json", script)
    write_text(home / "trace.txt", "2nd process: if (A_3 = A_3) succeeds\n")
    write_text(home / "trace.pv", "if A_recv = A_honest then\n")
    return home, [s["n"] for s in script["steps"]]


def _explanation(numbers, **over):
    out = {"opening": "the attacker is registered",
           "steps": [{"n": n, "note": f"step {n}"} for n in numbers],
           "conclusion": "B accepts because `if (A_3 = A_3)` succeeds"}
    out.update(over)
    return out


def _last_user(request):
    return [m.content for m in request if m.role == Role.USER][-1]


def _feedback(request):
    """What the loop told the writer after its last submission: the reply to
    the submit call."""
    return [m.content for m in request if m.role == Role.TOOL][-1]


def test_the_script_and_the_goal_reach_the_writer(tmp_path):
    env = _env(tmp_path, None)
    home, numbers = _cell(env)
    writer = _Scripted(_explanation(numbers))
    env._llm = writer
    got = asyncio.run(explain_cell(
        env, home=home, scenario="lowe", goal="auth_b_to_a",
        assumptions="- admission_peer_auth = open", goal_text="auth_b_to_a (…)",
        replay=True))
    user = _last_user(writer.requests[0])
    assert "Scenario: lowe" in user and "- admission_peer_auth = open" in user
    assert "10. X -> S2  forge  msg10" in user
    assert "X defines msg10 = aenc(I_B,PKB)" in user
    assert "X works out I_B as adec(msg9,private_key_I)" in user
    assert "PKB = pk(SKB)" in user           # the names are defined for it
    assert "The solver reported a replay" in user
    assert [s["n"] for s in got["steps"]] == numbers
    assert json.loads((home / "explanation.json").read_text()) == got
    # a second call reads it back and asks nobody
    assert asyncio.run(explain_cell(
        env, home=home, scenario="lowe", goal="auth_b_to_a",
        assumptions="", goal_text="", replay=False)) == got
    assert len(writer.requests) == 1


def test_missing_notes_and_invented_quotes_go_back_for_repair(tmp_path):
    env = _env(tmp_path, None)
    home, numbers = _cell(env)
    bad = _explanation(numbers[:-1] + [99],
                       opening="the attacker holds `a key nobody printed`")
    writer = _Scripted(bad, _explanation(numbers))
    env._llm = writer
    got = asyncio.run(explain_cell(
        env, home=home, scenario="lowe", goal="auth_b_to_a",
        assumptions="", goal_text="", replay=False))
    feedback = _feedback(writer.requests[1])
    assert f"these steps have no note: [{numbers[-1]}]" in feedback
    assert "the script has no step [99]" in feedback
    assert "a key nobody printed" in feedback
    assert [s["n"] for s in got["steps"]] == numbers


def test_quotes_may_use_the_scripts_names_and_any_spacing():
    sources = ["in(c, aenc((I_A_3, A_3), pk(SKB_2)))", "1. S1 -> X  send  (A,I)"]
    assert unfound_quotes(["`aenc((I_A,A),pk(SKB))` and `( A , I )`"], sources) == []
    assert unfound_quotes(["`aenc((I_B,A),pk(SKB))`"], sources) == ["aenc((I_B,A),pk(SKB))"]


def test_every_cell_lands_in_one_group_or_the_summary_goes_back(tmp_path):
    env = _env(tmp_path, None)
    cells = [("lowe/auth_b_to_a", {"conclusion": "B is fooled"}),
             ("lowe/secrecy_i_a", {"conclusion": "I_A leaks"})]
    bad = {"groups": [{"problem": "p", "cells": ["lowe/auth_b_to_a", "lowe/nothing"]}],
           "summary": "s"}
    good = {"groups": [{"problem": "p", "cells": ["lowe/auth_b_to_a", "lowe/secrecy_i_a"]}],
            "summary": "one problem"}
    writer = _Scripted(bad, good)
    env._llm = writer
    home = env.layout.node_dir("reproduce_attacks") / "summary"
    doc = asyncio.run(summarize(env, home=home, cells=cells, pending=3))
    feedback = _feedback(writer.requests[1])
    assert "these are not cells in the input: ['lowe/nothing']" in feedback
    assert "these cells are in no group: ['lowe/secrecy_i_a']" in feedback
    assert doc["covered"] == ["lowe/auth_b_to_a", "lowe/secrecy_i_a"]
    assert doc["pending"] == 3 and doc["summary"] == "one problem"
    assert "3 further false cell(s)" in _last_user(writer.requests[0])


def test_a_summary_over_other_cells_is_kept_aside_and_redone(tmp_path):
    env = _env(tmp_path, None)
    home = env.layout.node_dir("reproduce_attacks") / "summary"
    one = [("lowe/a", {"conclusion": "x"})]
    two = one + [("lowe/b", {"conclusion": "y"})]
    writer = _Scripted(
        {"groups": [{"problem": "p", "cells": ["lowe/a"]}], "summary": "first"},
        {"groups": [{"problem": "p", "cells": ["lowe/a", "lowe/b"]}], "summary": "second"})
    env._llm = writer
    asyncio.run(summarize(env, home=home, cells=one, pending=1))
    # the same cells again: read back, nobody asked
    assert asyncio.run(summarize(env, home=home, cells=one, pending=1))["summary"] == "first"
    assert len(writer.requests) == 1
    doc = asyncio.run(summarize(env, home=home, cells=two, pending=0))
    assert doc["summary"] == "second" and len(writer.requests) == 2
    assert json.loads((home / "summary-1.json").read_text())["summary"] == "first"
    assert (home / "transcript-1.jsonl").is_file()
    # the redone session started fresh rather than resuming the first
    assert len([m for m in writer.requests[1] if m.role == Role.USER]) == 1


def test_the_script_text_names_sessions_and_the_broken_goal():
    text = render_script(build(read(ATTACK_GRAPHS / "iso_leaked_key.dot")).to_json())
    assert "S1 = processA" in text
    assert "the attacker knows from the start: I_A, I_B, I_P, K_AP" in text
    assert "reads: ~M_4 = R_A; ~M_1 = I_B; ~M_3 = K_AP" in text
    assert "goal broken: S1 executes end_alice_injective_agreement_with_trusted_party(R_A,a_4)" in text
    assert "no matching begin event was executed" in text
    text = render_script(build(read(ATTACK_GRAPHS / "nspk_secrecy.dot")).to_json())
    assert "S2 = processB" in text
    assert ("goal broken: the attacker obtains witness_secrecy_i_a_I_A_B, "
            "using I_A") in text
    assert ("which S2 sent after its last protocol message: the value the "
            "attacker obtains is S2's copy") in text
