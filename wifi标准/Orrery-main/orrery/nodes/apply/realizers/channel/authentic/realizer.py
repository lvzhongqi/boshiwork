"""channel.authentic: the attacker can read this link but cannot forge its
sender. Extracted from wording like "authenticated / tamper-proof / trusted
out-of-band"; applies once the directed link exists.

ProVerif: the link's channel declaration becomes [private] and a public copy
on c follows every send on it, so the sender and receiver keep the channel
name and only role bodies change. Realized by an LLM session.
"""

from orrery.nodes.apply.realizers.base import Realizer


class Authentic(Realizer):
    axis = "channel"
    obj = "channel"
    subtype = "authentic"
    instance_key = "link"
    structural = False
    stronger_than = ("public",)
    params = {
        "link": {"kind": "entity_pair",
                   "note": ('the directed link (sender, receiver) modelled as '
                    'unforgeable in the sender direction')},
    }
    description = 'The attacker cannot forge the sender on this link, but can read it.'
