"""data.leaked_in_other_instances: copies of the named per-session value from
finished sessions reach the attacker — value plus the credential the protocol
wraps it in — while every running session's own copy must still meet its
goals; the known-key / state-reveal world. A replicated leftovers process
joins the main group; the session group's replication is untouched.
"""

from orrery.nodes.apply.realizers.base import Realizer


class LeakedInOtherInstances(Realizer):
    axis = "data"
    obj = "value"
    subtype = "leaked_in_other_instances"
    instance_key = "of"
    structural = True
    stronger_than = ("disclosed",)
    params = {
        "of": {"kind": "value_name",
               "note": "which per-session value, named as the model spells it"},
    }
    description = (
        "The attacker reads copies of the named per-session value from other "
        "sessions only — the known-key / state-reveal world.")
