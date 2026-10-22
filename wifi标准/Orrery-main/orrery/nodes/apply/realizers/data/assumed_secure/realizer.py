"""data.assumed_secure: the attacker never obtains the named value, held as a
checked premise rather than a conclusion — the trust anchor of a deployment,
such as a root key in a secure element or a pre-shared key installed out of
band. The strongest rung of the axis.

ProVerif: a semantic ``restriction attacker(...) ==> false`` plus the query
that activates it, and no leak anywhere; a model that puts the value on a
public channel fails the premise instead of returning verdicts.

Extraction trigger: "assumed secure", "cannot be compromised", "held in
trusted hardware", "out of scope for this analysis".
"""

from orrery.nodes.apply.realizers.base import Realizer


class AssumedSecure(Realizer):
    axis = "data"
    obj = "value"
    subtype = "assumed_secure"
    instance_key = "of"
    structural = False
    stronger_than = ("none",)
    params = {
        "of": {"kind": "value_name",
               "note": "which value, named as the model spells it"},
    }
    description = ('The attacker never obtains the named value: no leak, and the '
     'analysis holds that as a checked premise — a model in which the attacker '
     'could obtain it fails loudly instead of returning verdicts.')
