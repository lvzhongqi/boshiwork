"""Reading a supplied claim input, whichever shape it arrives in.

Shared by the claims gate and by the two extraction nodes that stand aside when
the file was supplied, so all three agree on what a valid input is.
"""

from __future__ import annotations

import json
from pathlib import Path

from orrery.nodes.base import NodeError


def load_claim_input(inp, what: str, where: str) -> dict:
    """Return ``inp`` as a dict: passed through, or parsed from the JSON file it
    points at. ``what`` names the input and ``where`` the caller, both only for
    error text. Raises NodeError on a missing path, JSON that is not an object,
    or an input of any other type.
    """
    if isinstance(inp, dict):
        return inp
    if isinstance(inp, (str, Path)):
        p = Path(inp)
        if not p.is_file():
            raise NodeError(f"{where} failed: {what} path does not exist: {p}")
        value = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise NodeError(f"{where} failed: {what} file must contain a JSON "
                            f"object, got {type(value).__name__}: {p}")
        return value
    raise NodeError(f"{where} failed: {what} input is neither a dict nor a "
                    f"path: {type(inp).__name__}")
