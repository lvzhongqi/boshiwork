"""key_reuse.observed: an application protects its own data under the named
key, and the attacker observes that second use's output — never the key,
never the choice of payload. The attacker-driven form is key_reuse.oracle.

The encoding mints a fresh application payload and re-runs the key's existing
protecting send over it at the tail of the role, giving resent-secrecy goals
an object to ask about.
"""

from orrery.nodes.apply.realizers.base import Realizer


class Observed(Realizer):
    axis = "key_reuse"
    obj = "secret_value"
    subtype = "observed"
    instance_key = "of"
    structural = False
    stronger_than = ("oracle",)
    params = {
        "of": {"kind": "value_name",
               "note": "which key, named as the model spells it"},
        "payload": {"kind": "value_name", "required": False,
                    "note": ("the name the document gives the second use's "
                             "fresh payload, where it gives one")},
    }
    description = ('The named key also serves a second legitimate use: the application '
     'protects its own fresh payload under it, and the attacker observes that '
     'output — never the key, never choosing the payload.')
