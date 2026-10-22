"""channel.secure: both directions between the target endpoints are private.
Covers a "secure channel / TLS tunnel / out-of-band channel", and the local
human interface too (a device's display and keypad reach its user off the
radio), which needs that user declared as a principal in entities.json.

ProVerif: [private] goes on both directed channel declarations between the
endpoints. A reference model may realise the same unreadable-unforgeable
coupling as shared private state (OAuth's AS/RS tables) or as a per-connection
channel, and line-by-line reading counts those as this same assumption.
"""

from orrery.nodes.apply.realizers.base import Realizer
from orrery.modules.pvtext.channels import channel_name
from orrery.nodes.apply.realizers.channel.secure_nonbinding.realizer import (
    _private_channel,
)


class Secure(Realizer):
    axis = "channel"
    obj = "channel"
    subtype = "secure"
    instance_key = "link"
    structural = False
    is_code = True
    stronger_than = ("secure_nonbinding",)
    params = {
        "link": {"kind": "entity_pair",
                   "note": ('the directed link (sender, receiver) modelled as '
                    'authenticated and confidential')},
    }
    description = ('Both directions between the target endpoints are private, so the '
                   'attacker can neither read nor forge requests or replies.')

    def apply_code(self, pv: str, target: dict | None) -> str:
        try:
            sender, receiver = target["link"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("target.link must name exactly two endpoints") from exc
        pv = _private_channel(pv, channel_name(sender, receiver))
        return _private_channel(pv, channel_name(receiver, sender))
