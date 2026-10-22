"""The one request this experiment sends — prompt assembly only, no I/O, no LLM.

Same shape as a node's ``build_prompt``: system block 0 is the document corpus,
byte-identical with what the pipeline's document readers get; block 1 is the
task, the vocabulary and the constraints. Language follows the same
``localized`` convention and the same ``prompt_lang`` config key the nodes read,
so prompt language stays one variable across baseline and pipeline.
"""

from __future__ import annotations

import json

from orrery.agent.compose import localized, render_prompt, render_system

from experiments.oneshot.reference import primitive_reference


def build_prompt(*, corpus: str, protocol: str, world_json: str,
                 scenario_name: str, scenario_json: str, properties_json: str,
                 goal_ids: list[str], modeling_rules: str,
                 lang: str = "en") -> tuple[list[str], str]:
    """Return ``(system_blocks, user_message)``."""
    system = render_system(__file__, localized("main.sys.md", lang),
                           cut_after=["document"],
                           document=corpus,
                           primitives=primitive_reference(),
                           modeling_rules=modeling_rules)
    user = render_prompt(__file__, localized("main.user.md", lang),
                         protocol=protocol,
                         world_json=world_json,
                         scenario_name=scenario_name,
                         scenario_json=scenario_json,
                         properties_json=properties_json,
                         goal_ids=", ".join(f"`{g}`" for g in goal_ids))
    return system, user


def scenario_json(scenario) -> str:
    """A scenario's complete assignment, rendered for the prompt.

    ``Point.to_json`` gives ``{id, subtype}`` and leaves the target implied by
    the id; a prompt has no such lookup, so axis and target are spelled out.
    """
    return json.dumps(
        [{"id": p.ref_id, "axis": p.axis, "subtype": p.subtype,
          **({"target": p.target} if p.target else {})}
         for p in scenario.points],
        ensure_ascii=False, indent=2)
