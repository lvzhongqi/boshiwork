"""key_reuse.separated: the key is confined to the purpose this protocol gives
it, which the flow model already is — a no-op realizer that writes and checks
nothing.
"""

from orrery.nodes.apply.realizers.base import NoopRealizer


class Separated(NoopRealizer):
    axis = "key_reuse"
    obj = "secret_value"
    subtype = "separated"
    instance_key = "of"
    structural = False
    stronger_than = ("observed",)
    params = {
        "of": {"kind": "value_name", "required": False,
               "note": "which key, when the dimension names one"},
    }
    description = ('The named key is confined to the purpose this protocol gives it: '
     'nothing else uses it (the flow state).')
