"""admission.closed: only the closed flow's honest identities hold credentials
recognised in the named identity scope. This is the axis's flow state, so the
realizer is a noop: the model already writes its credential store (role
parameters, a register) from the main process alone.

Extracted when the analysis fixes the set of legitimate parties, or says
nothing about outsiders obtaining credentials. Any world can take it.
"""

from orrery.nodes.apply.realizers.base import NoopRealizer


class AdmissionClosed(NoopRealizer):
    axis = "admission"
    obj = "identity_scope"
    subtype = "closed"
    instance_key = "scope"
    structural = False
    stronger_than = ("open",)
    params = {
        "scope": {"kind": "identity_scope",
                  "note": ("the lower_snake_case scope in the flow model's "
                           "@orrery-idiom marker")},
    }
    description = ('Only the closed flow\'s honest identities hold a credential '
     'recognised in the named identity scope (the flow state).')
