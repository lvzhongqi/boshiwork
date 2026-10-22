"""Public facade for the LIB schema: version gating, data classes, file I/O,
point resolution and semantic validation for the five kinds of LIB JSON.
Submodules layer bottom-up and acyclically: version, model, io, resolve,
validate. Each ``validate_*`` raises on a mismatch in its own file; folding
per-scenario verdicts into a goal's answer is the aggregate node's rule
(nodes/aggregate), not a schema check.
"""
from orrery.modules.libschema.version import (
    LIB_JSON_KINDS,
    VOCAB_VERSION,
    LibParseError,
    LibResolveError,
    LibSchemaError,
    LibSchemaVersionError,
    LibValidationError,
    require_vocab_version,
)
from orrery.modules.libschema.model import (
    VERDICTS,
    AssumptionsDoc,
    WorldEntry,
    Assumption,
    CaseMatrix,
    Claim,
    ClaimsDoc,
    FixedAssumption,
    Goal,
    GoalCases,
    NamedScenario,
    Point,
    PropertiesDoc,
    Result,
    ResultsDoc,
    Scenario,
    ScenarioVerdict,
)
from orrery.modules.libschema.io import (
    dump_assumptions,
    dump_cases_results,
    dump_claims,
    dump_properties,
    dump_results,
    load_assumptions,
    load_cases_results,
    load_claims,
    load_properties,
    load_results,
)
from orrery.modules.libschema.resolve import (
    applicable,
    expand_assignments,
    noop_default,
    required_params,
    resolve_point,
    scenario_coordinates,
    world_of,
)
from orrery.modules.libschema.validate import (
    validate_assumptions,
    validate_cases_results,
    validate_claims,
    validate_properties,
    validate_results,
    validate_world,
)

__all__ = [
    # version
    "LIB_JSON_KINDS", "VOCAB_VERSION", "require_vocab_version",
    "LibSchemaError", "LibSchemaVersionError", "LibParseError",
    "LibResolveError", "LibValidationError",
    # model
    "Point", "Scenario", "NamedScenario", "Assumption", "FixedAssumption",
    "Goal", "Claim", "Result",
    "ScenarioVerdict", "GoalCases", "CaseMatrix",
    "AssumptionsDoc", "WorldEntry", "PropertiesDoc", "ClaimsDoc", "ResultsDoc",
    "VERDICTS",
    # io
    "load_assumptions", "load_properties", "load_claims",
    "load_results", "load_cases_results",
    "dump_assumptions", "dump_properties", "dump_claims",
    "dump_results", "dump_cases_results",
    # resolve
    "resolve_point", "scenario_coordinates", "world_of", "expand_assignments",
    "noop_default", "required_params", "applicable",
    # validate
    "validate_assumptions", "validate_properties", "validate_claims",
    "validate_results", "validate_cases_results",
    "validate_world",
]
