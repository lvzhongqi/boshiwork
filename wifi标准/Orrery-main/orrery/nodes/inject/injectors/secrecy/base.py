"""Type Secrecy: a data value stays secret from the Dolev-Yao attacker in an
honest session.

One definition, honest-session secrecy; the query shape follows the target's
binding under realization=exposure_driven. A top-level ``free X`` or a
main-process ``new X`` is queried directly as ``query attacker(...)``; a
role-body ``let``/pattern binding uses one witness per holder, and a role-body
``new X`` becomes a witness only when its observation needs a guard. A witness
is guarded when the role reads or selects peer identities or credentials
during its run, and every holder of one goal follows the same rule.

Direct queries carry a same-line ``(* <goal id> *)`` comment. ProVerif drops
it, so the framework records it before solving to attribute the RESULT line.
"""

from orrery.nodes.inject.injectors.base import Injector


class SecrecyType(Injector):
    gtype = "Secrecy"
    parties = "holders"
    realization = "exposure_driven"
