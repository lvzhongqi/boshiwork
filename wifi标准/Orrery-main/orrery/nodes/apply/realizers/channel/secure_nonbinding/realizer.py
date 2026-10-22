"""channel.secure_nonbinding: the named direction is private while the reverse
direction stays public. Extracted where a document separates binding from
non-binding secure channels, or says replies are not bound to the request that
started them.

ProVerif: [private] goes on the named direction's channel declaration only;
the binding variant (subtype secure) does both directions.
"""

import re

from orrery.nodes.apply.realizers.base import Realizer
from orrery.modules.pvtext.channels import channel_name


def _private_channel(pv: str, name: str) -> str:
    """Mark the free declaration of directed channel ``name`` [private], and
    raise unless the model declares it exactly once. Shared with the secure
    subtype, which applies it to both directions."""
    pattern = re.compile(
        rf"(?m)^(?P<head>[ \t]*free[ \t]+{re.escape(name)}[ \t]*:[ \t]*channel)"
        rf"(?P<options>[ \t]*\[[^\]\r\n]*\])?(?P<tail>[ \t]*\.[^\r\n]*)$"
    )
    matches = list(pattern.finditer(pv))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one declaration of directed channel {name!r}; "
            f"found {len(matches)}"
        )
    match = matches[0]
    options = match.group("options")
    if options is None:
        replacement = match.group("head") + " [private]" + match.group("tail")
    else:
        values = [v.strip() for v in options.strip()[1:-1].split(",") if v.strip()]
        if "private" in values:
            return pv
        replacement = (
            match.group("head") + " [" + ", ".join([*values, "private"]) + "]"
            + match.group("tail")
        )
    return pv[:match.start()] + replacement + pv[match.end():]


class SecureNonbinding(Realizer):
    axis = "channel"
    obj = "channel"
    subtype = "secure_nonbinding"
    instance_key = "link"
    structural = False
    is_code = True
    stronger_than = ("authentic", "confidential")
    params = {
        "link": {"kind": "entity_pair",
                   "note": ('the directed link (sender, receiver) modelled as '
                    'unreadable and unforgeable but with replies not bound '
                    'to the initiating session')},
    }
    description = ('The target direction is private, so the attacker can neither read '
                   'nor forge on it, while the reverse direction remains public.')

    def apply_code(self, pv: str, target: dict | None) -> str:
        try:
            sender, receiver = target["link"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("target.link must name exactly two endpoints") from exc
        return _private_channel(pv, channel_name(sender, receiver))
