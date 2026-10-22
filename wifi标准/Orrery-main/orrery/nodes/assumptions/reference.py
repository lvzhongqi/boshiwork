"""The assumption and world vocabularies, rendered for the prompt.

Both are closed sets declared in code, so all of each fits inline. Inlining
keeps this node's tool array identical to the other document readers', which is
what lets the four share one cached copy of the corpus block. Rendered from the
vocabulary objects, so a new axis or subtype reaches the prompt as soon as it is
declared.
"""

from __future__ import annotations

from orrery.nodes.apply.realizers import VOCAB
from orrery.nodes.world.builders import WORLD_VOCAB


def assumption_reference() -> str:
    """Every axis, its object, and every subtype with the target keys it needs."""
    out: list[str] = []
    for axis in VOCAB.axes():
        out.append(f"**{axis}** (obj: {VOCAB.obj_of(axis)})")
        for st in VOCAB.dimension_values(axis):
            if VOCAB.is_stub(axis, st):
                # A stub has no realizer behind it, so naming one produces a
                # scenario the apply stage cannot build.
                out.append(f"  - {st} — NOT IMPLEMENTED, never choose this one")
                continue
            req = sorted(VOCAB.required_params(axis, st))
            keys = f"target keys: {', '.join(req)}" if req else "no target"
            out.append(f"  - {st} ({keys})")
            out.append(f"      {VOCAB.description(axis, st).strip()}")
        out.append("")
    return "\n".join(out).rstrip()


def world_reference() -> str:
    """Every world axis, its flow state, and the values it may take.

    The flow state is named on each axis because it is the one value never
    written: an axis left out already takes it.
    """
    out: list[str] = []
    for axis in WORLD_VOCAB.axes():
        flow = WORLD_VOCAB.flow_state(axis)
        out.append(f"**{axis}** (leave out for: {flow})")
        for st in WORLD_VOCAB.subtypes(axis):
            if st == flow:
                continue
            req = sorted(WORLD_VOCAB.required_params(axis, st))
            keys = f"target keys: {', '.join(req)}" if req else "no target"
            out.append(f"  - {st} ({keys})")
            out.append(f"      {WORLD_VOCAB.description(axis, st).strip()}")
        out.append("")
    return "\n".join(out).rstrip()
