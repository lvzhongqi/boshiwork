"""data.leaked_after_correct_session: a long-lived value reaches the attacker
only after a session completed correctly — Basin-Cremers LKR_aftercorrect and
the weak-forward-secrecy compromise world.
"""

from orrery.nodes.apply.realizers.base import Realizer


class LeakedAfterCorrectSession(Realizer):
    axis = "data"
    obj = "value"
    subtype = "leaked_after_correct_session"
    instance_key = "of"
    structural = False
    stronger_than = ("leaked_after_session",)
    params = {
        "of": {"kind": "value_name",
               "note": "which value, named as the model spells it"},
        "phase": {"kind": "phase", "required": False,
                  "note": "the phase boundary the gated leak sits behind"},
    }
    description = (
        "The attacker reads the named long-lived value only in worlds where a "
        "session completed correctly — the weak-forward-secrecy premise: the "
        "leak waits behind the phase boundary and a recorded correct "
        "completion.")
