"""Type Authentication: when the asserter completes, the subject really did
take part and agrees on the key values.

Lowe's four-level hierarchy, written as begin/end events plus a correspondence
query. The injection layer collapses aliveness / weak_agreement /
non_injective_agreement into a non-injective ``event(...) ==> event(...)`` and
emits ``inj-event(...) ==> inj-event(...)`` for injective_agreement; the
extraction layer still keeps all four labels apart.
"""

from pathlib import Path

from orrery.nodes.inject.injectors.base import Injector


class AuthenticationType(Injector):
    gtype = "Authentication"
    parties = "asserter_subject"
    realization = "correspondence"

    @classmethod
    def rules_dir(cls) -> Path:
        """One rules file for the whole type, in the type directory rather than
        the leaves: the four tiers emit the same events and differ only in the
        event arguments and the query form, and one call can batch several of
        them into a single prompt."""
        return cls._dir().parent
