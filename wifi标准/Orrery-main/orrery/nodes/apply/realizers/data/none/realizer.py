"""data.none: no leak action — the attacker gets no access to the named value
beyond what the protocol itself gives away (the flow model state). Nothing to
write in ProVerif: the flow model already is this world, so the realizer is a
no-op and checks nothing.
"""

from orrery.nodes.apply.realizers.base import NoopRealizer


class NoAccess(NoopRealizer):
    axis = "data"
    obj = "value"
    subtype = "none"
    instance_key = "of"
    structural = False
    stronger_than = ("leaked_after_correct_session",
                     "leaked_in_other_instances")
    params = {
        "of": {"kind": "value_name", "required": False,
               "note": "which value, when the dimension names one"},
    }
    description = ('No leak action: the attacker gets no access to the named value '
     'beyond what the protocol itself gives away (the flow state).')
