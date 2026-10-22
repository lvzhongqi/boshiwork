"""A value's lifetime, read off the model text: ``long_lived`` or
``per_session``.

A ``new <name>`` inside a role definition (``let <role>(...) = ...``) is
per-session, because role bodies run under replication; everything else — a
parameter, a ``free``/``const``, a main-process ``new`` — is long-lived. The
apply engine and the claims gate both read this rather than deciding it
themselves, since the data axis's writings differ by lifetime: a long-lived
value leaks as a branch of the main parallel group, a per-session one at its
draw or through an other-instances process.

A name the model binds once per role (one ``K_2`` in the document, bound as
``K_2_U`` and ``K_2_V``) resolves through :mod:`.roles` to those bindings, whose
lifetimes have to agree. A name with no binding at all is an error.
"""

from __future__ import annotations

import re

from orrery.modules.pvtext.roles import role_tagged_bindings

LONG_LIVED = "long_lived"
PER_SESSION = "per_session"


def _role_spans(pv: str) -> list[tuple[int, int]]:
    """The (start, end) offsets of every ``let <name>(...) =`` definition body.
    The span runs to the next ``let``/``process`` keyword at line start, which
    coincides with the definition's terminating ``.`` in well-formed models and
    needs no parser."""
    starts = [m.start() for m in re.finditer(r"(?m)^let\s+\w+", pv)]
    bounds: list[tuple[int, int]] = []
    for i, s in enumerate(starts):
        nxt = re.search(r"(?m)^(let\s+\w+|process\b)", pv[s + 1:])
        end = s + 1 + nxt.start() if nxt else len(pv)
        bounds.append((s, end))
    return bounds


def _lifetime_of(pv: str, name: str) -> str:
    """The rule itself, for a name the model binds under exactly this spelling."""
    news = [m.start() for m in
            re.finditer(rf"\bnew\s+{re.escape(name)}\s*[:;]", pv)]
    if not news:
        return LONG_LIVED
    spans = _role_spans(pv)
    if any(s <= pos < e for pos in news for s, e in spans):
        return PER_SESSION
    return LONG_LIVED


def value_lifetime(pv: str, name: str) -> str:
    """``long_lived`` or ``per_session`` for the named value in this model.

    Raises when the model binds the name neither directly nor once per role.
    """
    if re.search(rf"\b{re.escape(name)}\b", pv):
        return _lifetime_of(pv, name)
    # A declaration keeps the document's name for a value the model tags per
    # role: there are as many bindings as roles and none of them is the value,
    # so the lifetime is defined only when they agree.
    tagged = role_tagged_bindings(pv, name)
    if not tagged:
        raise ValueError(
            f"[pvtext] value {name!r} does not occur in the model, under its "
            f"own name or tagged with any role; lifetime is only defined for "
            f"names the model binds")
    kinds = {_lifetime_of(pv, n) for n in tagged}
    if len(kinds) != 1:
        raise ValueError(
            f"[pvtext] the role-tagged bindings of {name!r} ({tagged}) do not "
            f"agree on a lifetime ({sorted(kinds)}); the same value cannot be "
            f"long-lived in one role and per-session in another")
    return next(iter(kinds))
