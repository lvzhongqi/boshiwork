"""key_reuse.oracle: the named key's second use is attacker-driven — the
attacker submits the inputs and receives the key's output on them, never the
key itself.

Cumulative over key_reuse.observed: the application's own fresh payload still
rides under the key, so goals about that payload keep their object. This rung
needs the document to give the attacker an interaction surface with the second
use; a document naming only the second use's own data is observed.
"""

from orrery.nodes.apply.realizers.base import Realizer


class Oracle(Realizer):
    axis = "key_reuse"
    obj = "secret_value"
    subtype = "oracle"
    instance_key = "of"
    structural = False
    stronger_than = ()
    params = {
        "of": {"kind": "value_name",
               "note": "which key, named as the model spells it"},
        "payload": {"kind": "value_name", "required": False,
                    "note": ("the name the document gives the second use's "
                             "fresh payload, where it gives one")},
    }
    description = ('The named key\'s second use is attacker-driven: an oracle applies '
     'the key\'s operation to input of the attacker\'s choice, and the '
     'application\'s own fresh payload still rides under the same key. The '
     'attacker gets outputs, never the key.')
