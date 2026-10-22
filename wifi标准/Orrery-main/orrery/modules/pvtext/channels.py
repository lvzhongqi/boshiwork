"""The naming convention for directed named channels. Pure functions, with no
dependency on the model layer.

Every ``(sender, recipient)`` pair gets one public
``free channel_<sender>_<recipient>: channel``, plus one public channel ``c``
for publishing public values and for the attacker. Sending uses
``channel_<self>_<peer>`` and receiving reads ``channel_<peer>_<self>``. The
reachability check temporarily turns the named channels ``[private]`` while
leaving ``c`` public.
"""
from __future__ import annotations

PUBLIC_CHANNEL = "c"


def channel_name(sender: str, recipient: str) -> str:
    return f"channel_{sender}_{recipient}"


def parse_channel_name(name: str, roles) -> tuple[str, str] | None:
    """``channel_<X>_<Y>`` → ``(X, Y)``, where X and Y must both be known role
    names, which disambiguates names containing underscores. Returns None when
    this is not a named channel.
    """
    prefix = "channel_"
    if not name.startswith(prefix):
        return None
    rest = name[len(prefix):]
    for r in roles:
        if rest.startswith(r + "_"):
            peer = rest[len(r) + 1:]
            if peer in roles:
                return r, peer
    return None


def directed_channel_names(roles: list[str]) -> list[str]:
    """One channel name per ordered pair of distinct roles, in ``roles`` order,
    with the public channel ``c`` first.

    The full topology is emitted: an unused channel is only an unused public
    free name, while a missing one breaks any link-control assumption that
    looks the link up by its endpoints. The names derive from the roles that
    get a process, so channels and role processes cannot disagree.
    """
    return [PUBLIC_CHANNEL] + [channel_name(a, b)
                               for a in roles for b in roles if a != b]
