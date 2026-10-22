"""Render the thin scaffold for ``extract_flow``.

The scaffold fixes only what the framework owns: the role set, the directed
channel topology, and the honest-run probe. Types, process signatures,
declarations, initialisation, public outputs and the main process are the
model's to write; it receives the full ``principals.json`` in its prompt.
"""

from __future__ import annotations

from orrery.modules.kbase.primitives.catalog import iter_render_primitives
from orrery.modules.pvtext.channels import PUBLIC_CHANNEL, directed_channel_names
from orrery.modules.pvtext.knowledge import template_roles
from orrery.modules.pvtext.probe import PROBE_SECTION, probe_declarations

DECL_MARK = "(* @DECLARATIONS *)"
MAIN_MARK = "(* @MAIN *)"


def render_template(*, protocol_name: str, knowledge: dict) -> str:
    """Return the role/channel/probe scaffold and nothing knowledge-derived."""
    roles = template_roles(knowledge)
    channels = directed_channel_names(roles)
    parts = [
        f"(* Protocol: {protocol_name} *)",
        "",
        "(* -- Declarations -- *)",
        DECL_MARK,
        "",
        "(* -- Channels -- *)",
        f"free {PUBLIC_CHANNEL}: channel.",
        *[f"free {channel}: channel [private]." for channel in channels
          if channel != PUBLIC_CHANNEL],
        "",
        PROBE_SECTION,
        *probe_declarations(roles),
        "",
        "(* -- Role processes -- *)",
    ]
    for role in roles:
        parts.extend((f"(* @ROLE {role} *)", ""))
    parts.extend(("(* -- Main process -- *)", MAIN_MARK))
    return "\n".join(parts).rstrip() + "\n"


def template_reference(_knowledge: dict) -> str:
    """Standard primitive declarations, offered beside the scaffold rather than
    inside it.

    Constructors precede reductions because a reduction may use a constructor
    declared by another catalog entry.
    """
    declarations = [
        declaration
        for primitive in iter_render_primitives()
        for declaration in primitive.all_decls()
    ]
    ordered = ([d for d in declarations if d.lstrip().startswith("fun")]
               + [d for d in declarations
                  if not d.lstrip().startswith("fun")])
    return ("Standard primitive declarations, with constructors before "
            "reductions:\n" + "\n".join(f"  {line}" for line in ordered))
