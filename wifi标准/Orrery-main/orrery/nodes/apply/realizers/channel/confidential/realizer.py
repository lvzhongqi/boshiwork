"""channel.confidential: the attacker cannot read this link but can inject and
forge on it. The other half of the read x forge grid from authentic, and
incomparable with it; extracted from "confidential but not authenticated".

ProVerif: the link's channel declaration becomes private and one replicated
forwarder ``!in(c, x); out(link, x)`` joins the main parallel group, so honest
traffic is unreadable while anything the attacker composes on c still enters
the link. Endpoint processes keep the channel name. Realized by an LLM session.
"""

from orrery.nodes.apply.realizers.base import Realizer


class Confidential(Realizer):
    axis = "channel"
    obj = "channel"
    subtype = "confidential"
    instance_key = "link"
    structural = False
    stronger_than = ("public",)
    params = {
        "link": {"kind": "entity_pair",
                   "note": ('the directed link (sender, receiver) modelled as '
                    'unreadable but forgeable')},
    }
    description = ('The attacker cannot read this link but can inject/forge on it -- the '
     'rarest half-channel, completing the read x forge 2x2 alongside '
     'public / authentic / secure. Incomparable with authentic (different '
     'halves).')
