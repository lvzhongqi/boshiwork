"""channel.public: the link is a public channel, fully read/write controlled by
the Dolev-Yao attacker. This is the axis's flow state -- every link starts
here, so nothing is applied.

ProVerif: sends and receives go on free public channels (c, or a directed named
free channel) and no channel is private.
"""

from orrery.nodes.apply.realizers.base import NoopRealizer


class Public(NoopRealizer):
    axis = "channel"
    obj = "channel"
    subtype = "public"
    instance_key = "link"
    structural = False
    # Optional, like every flow state's target: it rides through to whichever
    # subtype a scenario picks, and the instance key reads the link off it to
    # tell one link's answer from another's.
    params = {
        "link": {"kind": "entity_pair", "required": False,
                 "note": "the directed link (sender, receiver), when the "
                         "dimension names one"},
    }
    description = ('The link is a public channel, fully read/write controlled by the '
     'Dolev-Yao attacker (the flow state -- every link starts here).')
