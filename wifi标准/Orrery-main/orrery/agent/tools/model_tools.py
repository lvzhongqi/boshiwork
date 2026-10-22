"""lookup_function_signature: the KB primitive catalog lookup.

An input-side lookup: when the model lacks a primitive's curated ProVerif
shape, there is no other source for it.
"""

from __future__ import annotations

from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.registry import ToolDef
from orrery.infra.llm.client import FunctionParameter
from orrery.modules.kbase.primitives import catalog as primitives


def _lookup(ctx: ToolContext, name: str) -> str:
    p = primitives.lookup_primitive(name)
    if p is None:
        return (f"{name!r} is not in the primitive catalog; names available (aliases "
                f"included): {sorted(primitives.library_function_names())}")
    parts = [f"[{p.name}] {p.description}", *p.all_decls()]
    if p.idiom:
        parts.append(f"\nidiom:\n{p.idiom}")
    if p.requires:
        parts.append(f"\nrequires (keep these too): {list(p.requires)}")
    return "\n".join(parts)


MODEL_TOOLS = [
    ToolDef(
        name="lookup_function_signature",
        description="Look a cryptographic primitive up in the catalog: its typed ProVerif declaration plus the idiom for using it. A deterministic table lookup; aliases are normalised (ECDH/X25519 -> exp, and so on).",
        parameters=FunctionParameter(type="object", properties={
            "name": FunctionParameter(type="string", description="primitive name or alias"),
        }, required=["name"]),
        handler=_lookup,
    ),
]
