"""The role names a model declares, and the per-role bindings of one value.

A projection from the model text like :mod:`.lifetime` and :mod:`.machinery`:
computed from the file, never declared beside it. The claims gate and
:mod:`.lifetime` both read it, so it lives on its own here.
"""

from __future__ import annotations

import re


def model_roles(pv: str) -> set[str]:
    """The role names the model declares, from the two places it writes them:
    the ``@ROLE`` marker the flow template stamps into every role body, and the
    ``process<Role>`` name itself. Read off the model rather than principals.json
    so it also works on a model supplied whole.
    """
    roles = set(re.findall(r"@ROLE\s+([A-Za-z_][A-Za-z0-9_']*)", pv))
    roles |= set(re.findall(r"\blet\s+process([A-Za-z0-9_']+)\s*\(", pv))
    return {r for r in roles if r}


def role_tagged_bindings(pv: str, name: str) -> list[str]:
    """The identifiers a model binds when it holds ``name`` once per role.

    A value the document names once is bound once per role body, tagged with the
    role so the same name never means two things: one ``K_2`` in the document
    becomes ``K_2_U`` in the initiator and ``K_2_V`` in the responder, while the
    declaration keeps the document's name. Matching is on the
    underscore-stripped, case-folded form, the same normalisation the claims gate
    uses, and the tag may sit on either end. Empty when there is no such binding.
    """
    key = name.replace("_", "").lower()
    tags = {r.replace("_", "").lower() for r in model_roles(pv)}
    if not tags:
        return []
    wanted = {key + t for t in tags} | {t + key for t in tags}
    out = {tok for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_']*", pv)
           if tok.replace("_", "").lower() in wanted}
    return sorted(out)


__all__ = ["model_roles", "role_tagged_bindings"]
