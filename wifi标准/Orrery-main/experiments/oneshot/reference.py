"""Mainline-owned reference material carried by the one-shot prompt.

Vocabulary, primitive declarations, modeling idioms and the world/scenario/goal
rules all come from the same registries and prompt files as the mainline; this
module only selects and nests them. A rule several targets select is rendered
once with those targets under it; a multi-writing subtype ships both writings
tagged with the lifetime that selects each, since the prompt is built before
there is a model to project the lifetime from.
"""

from __future__ import annotations

import importlib
import inspect
import json

from orrery.modules.kbase.primitives.catalog import iter_render_primitives
from orrery.modules.kbase.modeling_idioms import (
    identity_idioms, structure_idioms, time_variant_idioms,
)
from orrery.nodes.apply.order import apply_order
from orrery.nodes.apply.realizers import realizer_for
from orrery.nodes.inject.injectors import injector_for
from orrery.nodes.world.builders import builder_for


def primitive_reference() -> str:
    """The standard primitive declarations, in copyable order.

    Every ``fun`` comes before every ``reduc`` because ProVerif requires
    declaration before use: ``reduc adec(aenc(x, pk(y)), y)`` needs ``pk``.
    """
    decls = [d for p in iter_render_primitives() for d in p.all_decls()]
    ordered = ([d for d in decls if d.lstrip().startswith("fun")]
               + [d for d in decls if not d.lstrip().startswith("fun")])
    return ("Standard primitive declarations, in the order to copy them:\n"
            + "\n".join(f"  {d}" for d in ordered))


_RULE_TAGS = ("task", "constraints", "success_criteria", "example", "failure")


def _source_rule(text: str) -> str:
    """Nest a mainline rule without creating duplicate top-level prompt tags."""
    out = text.strip()
    for tag in _RULE_TAGS:
        out = out.replace(f"<{tag}>", f"<rule_{tag}>")
        out = out.replace(f"</{tag}>", f"</rule_{tag}>")
    return out


def _rule(ident: str, text: str, *, form: str | None = None,
          lifetime: str | None = None, targets=(), mode: str = "llm") -> str:
    """One mainline rule, with every target that selected it.

    ``targets`` is a list because the mainline batches the same way. A global
    point contributes no target and the ``applies_to`` section is omitted.
    """
    attrs = f' id="{ident}" mode="{mode}"'
    if form is not None:
        attrs += f' form="{form}"'
    if lifetime is not None:
        attrs += f' lifetime="{lifetime}"'
    head = [f"<rule{attrs}>"]
    named = [t for t in targets if t]
    if named:
        head += ["<applies_to>",
                 *(json.dumps(t, ensure_ascii=False) for t in named),
                 "</applies_to>"]
    return "\n".join([*head, _source_rule(text), "</rule>"])


def _code_realizer_rule(realizer, targets) -> str:
    """The checked implementation's own module documentation, not a new rule."""
    module = importlib.import_module(type(realizer).__module__)
    text = inspect.getdoc(module) or realizer.description
    return _rule(realizer.id, text, targets=targets,
                 mode="deterministic-mainline-code")


def _lifetime_of(realizer, form: str | None) -> str | None:
    """Which lifetime selects this writing, as the realizer declares it."""
    if form is None:
        return None
    for lifetime, chosen in realizer.writings_by_lifetime.items():
        if chosen == form:
            return lifetime
    raise KeyError(
        f"[oneshot] realizer {realizer.id}: writing {form!r} is in `writings` "
        f"but no lifetime selects it; the registry should have refused that")


def _idiom_library() -> str:
    def block(name: str, items) -> list[str]:
        return [f"<{name}>",
                *(_rule(f"{i.id}/v{i.version}", i.prompt,
                        mode="mainline-library") for i in items),
                f"</{name}>"]

    return "\n".join([
        *block("identity_modeling_library", identity_idioms()),
        *block("time_variant_modeling_library", time_variant_idioms()),
        *block("structure_modeling_library", structure_idioms()),
    ])


def modeling_rules_reference(*, world, scenario, goals, lang: str = "en") -> str:
    """The exact mainline rules needed by one monolithic scenario request.

    No rule text is maintained a second time here: LLM-backed world/apply/inject
    rules come from each registered leaf's ``sys_prompt``, deterministic
    realizers contribute their implementation module's own docstring, and the
    idioms come from the same curated libraries the flow tools use.
    """
    world_rules = []
    for entry in sorted(world, key=lambda x: builder_for(x.axis, x.subtype).build_order):
        builder = builder_for(entry.axis, entry.subtype)
        if not builder.noop:
            world_rules.append(_rule(builder.id, builder.sys_prompt(lang),
                                     targets=[entry.target]))

    # One entry per (realizer, writing), in the mainline's apply order, carrying
    # every target that selected it.
    groups: dict[tuple[str, str | None], list] = {}
    selected: dict[str, object] = {}
    for point in apply_order(list(scenario.points)):
        realizer = realizer_for(point.axis, point.subtype)
        if realizer.is_noop:
            continue
        selected[realizer.id] = realizer
        for form in realizer.writings or (None,):
            groups.setdefault((realizer.id, form), []).append(point.target)

    assumption_rules = []
    for (rid, form), targets in groups.items():
        realizer = selected[rid]
        if realizer.is_code:
            assumption_rules.append(_code_realizer_rule(realizer, targets))
        elif form is None:
            assumption_rules.append(_rule(
                rid, realizer.sys_prompt(lang=lang), targets=targets))
        else:
            assumption_rules.append(_rule(
                rid, realizer.sys_prompt(form, lang), form=form,
                lifetime=_lifetime_of(realizer, form), targets=targets))

    goal_rules, seen = [], set()
    for goal in goals:
        subtype = goal.subtype or ("basic" if goal.type == "Secrecy" else None)
        if subtype is None:
            raise ValueError(f"goal {goal.id}: type {goal.type!r} needs a subtype")
        injector = injector_for(goal.type, subtype)
        key = injector.rules_dir().resolve()
        if key in seen:
            continue
        seen.add(key)
        goal_rules.append(_rule(injector.id, injector.sys_prompt(lang)))

    def section(name: str, rules: list[str]) -> list[str]:
        return [f"<{name}>", *(rules or ["(no non-flow-state rule applies)"]),
                f"</{name}>"]

    blocks = [
        _idiom_library(),
        "\n".join(section("world_rules", world_rules)),
        "\n".join(section("object_assumption_rules", assumption_rules)),
        "\n".join(section("goal_rules", goal_rules)),
    ]
    return "\n\n".join(blocks)
