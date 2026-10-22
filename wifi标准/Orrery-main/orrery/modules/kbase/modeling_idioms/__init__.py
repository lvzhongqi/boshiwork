"""The three modelling-idiom material libraries: identity, role-body structure
and time-variant parameters. Re-exports each library's entry type, its lookups
and its lead sentence.
"""
from orrery.modules.kbase.modeling_idioms.catalog import (
    IdentityIdiom, identity_idiom, identity_idioms, identity_lead,
    search_identity_idioms,
)
from orrery.modules.kbase.modeling_idioms.structure import (
    StructureIdiom, select_structure_idiom, structure_idiom, structure_idioms,
    structure_lead,
)
from orrery.modules.kbase.modeling_idioms.time_variant import (
    TimeVariantIdiom, select_time_variant_idiom, time_variant_idiom,
    time_variant_idioms, time_variant_lead,
)

__all__ = [
    "IdentityIdiom", "identity_idiom", "identity_idioms",
    "identity_lead", "search_identity_idioms",
    "StructureIdiom", "select_structure_idiom", "structure_idiom",
    "structure_idioms", "structure_lead",
    "TimeVariantIdiom", "select_time_variant_idiom", "time_variant_idiom",
    "time_variant_lead",
    "time_variant_idioms",
]
