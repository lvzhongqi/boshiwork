"""data.leaked_after_session: a long-lived value reaches the attacker only
after the protocol sessions have run — Basin-Cremers LKR_after and the usual
forward-secrecy compromise world. A per-session value has no single shared
instance that can leak after all sessions; that world is
data.leaked_in_other_instances.
"""

from orrery.nodes.apply.realizers.base import Realizer


class LeakedAfterSession(Realizer):
    axis = "data"
    obj = "value"
    subtype = "leaked_after_session"
    instance_key = "of"
    structural = True
    stronger_than = ("disclosed",)
    params = {
        "of": {"kind": "value_name",
               "note": "which value, named as the model spells it"},
        "phase": {"kind": "phase", "required": False,
                  "note": ("the phase boundary the leak sits behind; "
                           "omitted means phase 1")},
    }
    description = (
        "The attacker reads the named long-lived value only after the "
        "protocol sessions have run — the forward-secrecy compromise world.")
