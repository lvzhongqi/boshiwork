"""In-memory data model for the LIB JSON files: pure data, each class carrying
its own ``from_json`` / ``to_json``. io.py opens files and gates the version,
validate.py does the KB and cross-file checks.

claims.json references assumptions by ``id``, so an :class:`AssumptionsDoc`
must be parsed before it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from orrery.modules.libschema.version import LibParseError
from orrery.version import VOCAB_VERSION

# "unknown" is ProVerif's cannot-be-proved, still a result about the model;
# "timeout", "solver_limit" and "resource_limit" (the solver hit its memory
# cap, infra/proverif/outcome.OutcomeKind) mean the solver never finished, so
# nothing was decided; "vacuous" means the goal's observation point is
# unreachable, so it was proved over an empty set of traces. A curated corpus
# entry only ever carries the first three.
VERDICTS = ("true", "false", "unknown", "timeout", "solver_limit",
            "resource_limit", "vacuous")
#: Verdicts that mean the solver never reached an answer. Every OutcomeKind
#: solve/node.py writes as a verdict is here, or aggregate would read it as
#: "unknown" — an undecided model — instead of a solver that never finished.
NO_ANSWER = ("timeout", "solver_limit", "resource_limit")
#: The verdict for a goal the model never actually posed.
VACUOUS = "vacuous"


def _canon_target(target) -> str:
    """Canonical string form of a target: stable, hashable, sortable. dicts are
    sorted by key so key ordering cannot create ambiguity."""
    return json.dumps(target, sort_keys=True, ensure_ascii=False)


def _require(d, key, where):
    if not isinstance(d, dict):
        raise LibParseError(f"{where}: must be an object, got {type(d).__name__}")
    if key not in d:
        raise LibParseError(f"{where}: missing field {key!r}; keys present: {sorted(d)}")
    return d[key]


def _as_list(v, where):
    if not isinstance(v, list):
        raise LibParseError(f"{where}: must be an array, got {type(v).__name__}")
    return v


@dataclass(eq=False)
class Point:
    """One coordinate in the assumption space: a subtype chosen for one
    assumption's target.

    ``ref_id`` records which entry of assumptions.json it came from, matching
    the ``{id, subtype}`` reference form. It takes no part in equality or
    hashing.
    """
    axis: str
    subtype: str
    target: Any = None
    ref_id: str | None = field(default=None, compare=False)

    def _key(self):
        return (self.axis, self.subtype, _canon_target(self.target))

    def __eq__(self, other):
        return isinstance(other, Point) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __repr__(self):
        t = "" if self.target is None else f", target={self.target!r}"
        r = f", ref_id={self.ref_id!r}" if self.ref_id else ""
        return f"Point({self.axis!r}, {self.subtype!r}{t}{r})"

    @classmethod
    def from_ref(cls, d, assumptions, *, where="point"):
        """Reference form ``{id, subtype}`` → Point, resolving axis and target
        through assumptions. Raises LibParseError if the id is unknown, or names
        a world assumption, which cannot be a scenario condition."""
        gid = str(_require(d, "id", where))
        sub = str(_require(d, "subtype", where))
        a = assumptions.by_id(gid)
        if a is None:
            if assumptions.is_world_id(gid):
                raise LibParseError(
                    f"{where}: {gid!r} is a world assumption, which cannot be a "
                    f"scenario condition. A world assumption constrains the whole "
                    f"analysis and is applied once before any scenario; asking "
                    f"the same goal under two world assumptions is two runs, not two "
                    f"scenarios of one"
                )
            raise LibParseError(
                f"{where}: dangling reference id={gid!r}; assumptions.json declares "
                f"{assumptions.ids()}"
            )
        return cls(axis=a.axis, subtype=sub, target=a.target, ref_id=gid)

    def to_json(self):
        """Reference form ``{id, subtype}``. A point with no ``ref_id``
        (constructed inside the engine) degrades to {axis, subtype, target}."""
        if self.ref_id is not None:
            return {"id": self.ref_id, "subtype": self.subtype}
        out = {"axis": self.axis, "subtype": self.subtype}
        if self.target is not None:
            out["target"] = self.target
        return out


@dataclass(eq=False)
class Scenario:
    """A complete assignment: one subtype chosen for every optional assumption.

    Never empty — even the flow state is written out explicitly. Points are
    sorted by ``_key`` on construction, so the form is deterministic.
    """
    points: tuple = ()

    def __post_init__(self):
        self.points = tuple(sorted(self.points, key=lambda p: p._key()))

    def _key(self):
        return frozenset(p._key() for p in self.points)

    def __eq__(self, other):
        return isinstance(other, Scenario) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __iter__(self):
        return iter(self.points)

    def __len__(self):
        return len(self.points)

    @classmethod
    def from_json(cls, arr, assumptions, *, where="scenario"):
        return cls(tuple(
            Point.from_ref(p, assumptions, where=f"{where}[{i}]")
            for i, p in enumerate(_as_list(arr, where))
        ))

    def to_json(self):
        return [p.to_json() for p in self.points]


@dataclass
class Goal:
    """One security goal — a vocabulary entry carrying no conclusion and no
    assumption reference.

    Which scenarios it is verified under is stated in claims.json; whether it
    holds lives on the results side. There is no field able to hold an
    assumption reference, so the two vocabularies stay separate structurally.
    """
    id: str
    type: str
    values: tuple
    parties: dict
    subtype: str | None = None

    @classmethod
    def from_json(cls, d, *, where="property"):
        gid = str(_require(d, "id", where))
        w = f"{where}[{gid}]"
        if "requires" in d:
            raise LibParseError(
                f"{w}: the 'requires' field is the old shape; the claims now live in "
                f"claims.json as {{property, scenarios}}, and properties.json is the "
                f"goal vocabulary only"
            )
        return cls(
            id=gid,
            type=str(_require(d, "type", w)),
            values=tuple(_as_list(_require(d, "values", w), f"{w}.values")),
            parties=dict(_require(d, "parties", w)),
            subtype=d.get("subtype"),
        )

    def to_json(self):
        out = {"id": self.id, "type": self.type}
        if self.subtype is not None:
            out["subtype"] = self.subtype
        out["values"] = list(self.values)
        out["parties"] = dict(self.parties)
        return out


@dataclass
class Result:
    """``{id, verdict, description?}``, where verdict is the conjunction of that
    goal's per-scenario verdicts.

    There is no boundary field: the boundary is derived from cases_results.
    """
    id: str
    verdict: str
    description: str | None = None

    @classmethod
    def from_json(cls, d, *, where="result"):
        gid = str(_require(d, "id", where))
        w = f"{where}[{gid}]"
        verdict = str(_require(d, "verdict", w))
        if verdict not in VERDICTS:
            raise LibParseError(f"{w}.verdict: must be one of {VERDICTS}, got {verdict!r}")
        return cls(gid, verdict, d.get("description"))

    def to_json(self):
        out = {"id": self.id, "verdict": self.verdict}
        if self.description is not None:
            out["description"] = self.description
        return out


@dataclass
class ScenarioVerdict:
    scenario: Scenario
    verdict: str

    @classmethod
    def from_json(cls, d, assumptions, *, where="scenario_verdict"):
        sc = Scenario.from_json(
            _require(d, "scenario", where), assumptions, where=f"{where}.scenario")
        v = str(_require(d, "verdict", where))
        if v not in VERDICTS:
            raise LibParseError(f"{where}.verdict: must be one of {VERDICTS}, got {v!r}")
        return cls(sc, v)

    def to_json(self):
        return {"scenario": self.scenario.to_json(), "verdict": self.verdict}


@dataclass
class GoalCases:
    """One goal's outcome per scenario. The LIB side keeps every scenario,
    including those no claim covers, for the benefit of user 2."""
    id: str
    by_scenario: tuple = ()   # tuple[ScenarioVerdict, ...]

    @classmethod
    def from_json(cls, d, assumptions, *, where="case"):
        gid = str(_require(d, "id", where))
        w = f"{where}[{gid}]"
        arr = _as_list(_require(d, "by_scenario", w), f"{w}.by_scenario")
        return cls(gid, tuple(
            ScenarioVerdict.from_json(x, assumptions, where=f"{w}.by_scenario[{i}]")
            for i, x in enumerate(arr)
        ))

    def to_json(self):
        return {"id": self.id, "by_scenario": [sv.to_json() for sv in self.by_scenario]}

    def verdict_of(self, scenario):
        """This scenario's verdict, or None if it was never run."""
        for sv in self.by_scenario:
            if sv.scenario == scenario:
                return sv.verdict
        return None


@dataclass
class CaseMatrix:
    """cases_results.json in memory: the per-scenario verdict matrix, keyed by
    goal id."""
    cases: tuple = ()   # tuple[GoalCases, ...]

    @classmethod
    def from_json(cls, data, assumptions, *, where="cases_results"):
        arr = _as_list(_require(data, "cases", where), f"{where}.cases")
        return cls(tuple(
            GoalCases.from_json(x, assumptions, where=f"{where}.cases[{i}]")
            for i, x in enumerate(arr)
        ))

    def to_json(self):
        return {"vocab_version": VOCAB_VERSION, "cases": [gc.to_json() for gc in self.cases]}

    def by_id(self, gid):
        for gc in self.cases:
            if gc.id == gid:
                return gc
        return None

    def ids(self):
        return [gc.id for gc in self.cases]


@dataclass
class WorldEntry:
    """One world assumption: ``{id, axis, target?, subtype}``, constraining the
    analysis as a whole — which principals exist, which seats each may occupy,
    how sessions are laid out.

    Exactly one value per (axis, target), never a scenario condition, and
    build_world applies it before any object-level point.
    """
    id: str
    axis: str
    subtype: str
    target: Any = None

    @property
    def is_global(self):
        return self.target is None

    @classmethod
    def from_json(cls, d, *, where="world entry"):
        gid = str(_require(d, "id", where))
        w = f"{where}[{gid}]"
        if "subtypes" in d:
            raise LibParseError(
                f"{w}: a world entry holds one 'subtype'; 'subtypes' is the "
                f"variable shape, and the world has no variable section — a run "
                f"analyses one world")
        return cls(id=gid, axis=str(_require(d, "axis", w)),
                   subtype=str(_require(d, "subtype", w)),
                   target=d.get("target"))

    def to_json(self):
        out = {"id": self.id, "axis": self.axis}
        if self.target is not None:
            out["target"] = self.target
        out["subtype"] = self.subtype
        return out


@dataclass
class FixedAssumption:
    """One fixed assumption: ``{id, axis, target?, subtype}``, a fact the
    document pins down and the engine applies unconditionally.

    The subtype is singular and may equal the flow state: its contribution to
    the world is then zero, but the entry still records that the document said
    so, which is distinguishable from the extractor having missed it.
    """
    id: str
    axis: str
    subtype: str
    target: Any = None

    @property
    def subtypes(self):
        """The one-element domain, so fixed and variable entries resolve through
        the same code path (resolve_point checks membership here)."""
        return (self.subtype,)

    @property
    def is_global(self):
        return self.target is None

    @classmethod
    def from_json(cls, d, *, where="assumption"):
        gid = str(_require(d, "id", where))
        w = f"{where}[{gid}]"
        if "subtypes" in d:
            raise LibParseError(
                f"{w}: a fixed entry carries a single 'subtype'; 'subtypes' (plural) "
                f"is the variable shape — a dimension belongs in the 'variable' section"
            )
        return cls(id=gid, axis=str(_require(d, "axis", w)),
                   subtype=str(_require(d, "subtype", w)), target=d.get("target"))

    def to_json(self):
        out = {"id": self.id, "axis": self.axis}
        if self.target is not None:
            out["target"] = self.target
        out["subtype"] = self.subtype
        return out


@dataclass
class Assumption:
    """One variable assumption: ``{id, axis, target?, subtypes}``, a dimension of
    the assumption space listing at least two values.

    ``id`` is the primary key, and everything else references only it. A
    ``target`` of None means a global axis, such as population, where the whole
    axis is a single assumption.
    """
    id: str
    axis: str
    target: Any = None
    subtypes: tuple = ()      # tuple[str, ...], length ≥ 2

    @property
    def is_global(self):
        return self.target is None

    @classmethod
    def from_json(cls, d, *, where="assumption"):
        gid = str(_require(d, "id", where))
        w = f"{where}[{gid}]"
        if "subtype" in d and "subtypes" not in d:
            raise LibParseError(
                f"{w}: a variable entry lists 'subtypes' (≥2 values); a single "
                f"'subtype' is the fixed shape — a fact belongs in the 'fixed' section"
            )
        subs = tuple(str(s) for s in _as_list(_require(d, "subtypes", w), f"{w}.subtypes"))
        if len(subs) < 2:
            raise LibParseError(
                f"{w}.subtypes: a dimension needs at least two values, got {list(subs)}; "
                f"a single-valued entry is a fact and belongs in the 'fixed' section"
            )
        if len(set(subs)) != len(subs):
            raise LibParseError(f"{w}.subtypes: duplicate value in {list(subs)}")
        return cls(id=gid, axis=str(_require(d, "axis", w)), target=d.get("target"), subtypes=subs)

    def to_json(self):
        out = {"id": self.id, "axis": self.axis}
        if self.target is not None:
            out["target"] = self.target
        out["subtypes"] = list(self.subtypes)
        return out


@dataclass
class AssumptionsDoc:
    """assumptions.json: ``world`` (applied once by build_world), ``fixed``
    (facts, one subtype each, applied unconditionally) and ``variable``
    (dimensions, ≥2 subtypes each, picked per scenario). Anything not written
    down is left at its flow state."""
    world: tuple = ()             # tuple[WorldEntry, ...]
    fixed: tuple = ()             # tuple[FixedAssumption, ...]
    variable: tuple = ()          # tuple[Assumption, ...]

    @classmethod
    def from_json(cls, data, *, where="assumptions"):
        for old in ("assumptions", "replication", "axes"):
            if old in data:
                raise LibParseError(
                    f"{where}: the top-level key {old!r} is the v8 shape; v9 splits the "
                    f"entries into 'fixed' (facts, single subtype) and 'variable' "
                    f"(dimensions, ≥2 subtypes), and 'replication' is gone (the flow model "
                    f"always replicates)"
                )
        world = tuple(
            WorldEntry.from_json(a, where=f"{where}.world[{i}]")
            for i, a in enumerate(_as_list(_require(data, "world", where), f"{where}.world")))
        wseen = set()
        for a in world:
            k = (a.axis, _canon_target(a.target))
            if k in wseen:
                raise LibParseError(
                    f"{where}.world: (axis, target) must be unique, but "
                    f"{a.axis!r} is answered twice for target {a.target!r}; a "
                    f"run analyses one world")
            wseen.add(k)
        fixed = tuple(
            FixedAssumption.from_json(a, where=f"{where}.fixed[{i}]")
            for i, a in enumerate(_as_list(_require(data, "fixed", where), f"{where}.fixed")))
        variable = tuple(
            Assumption.from_json(a, where=f"{where}.variable[{i}]")
            for i, a in enumerate(_as_list(_require(data, "variable", where), f"{where}.variable")))
        items = fixed + variable
        seen = set()
        for a in world:
            if a.id in seen:
                raise LibParseError(f"{where}: duplicate id {a.id!r}")
            seen.add(a.id)
        for a in items:
            if a.id in seen:
                raise LibParseError(f"{where}: duplicate assumption id {a.id!r}")
            seen.add(a.id)
            k = (a.axis, _canon_target(a.target))
            for other in items:
                if other is not a and (other.axis, _canon_target(other.target)) == k:
                    raise LibParseError(
                        f"{where}: (axis, target) must be unique across both sections, but "
                        f"{a.id!r} collides with {other.id!r}: axis={a.axis!r} target={a.target!r}"
                    )
        return cls(world=world, fixed=fixed, variable=variable)

    def to_json(self):
        return {
            "vocab_version": VOCAB_VERSION,
            "world": [a.to_json() for a in self.world],
            "fixed": [a.to_json() for a in self.fixed],
            "variable": [a.to_json() for a in self.variable],
        }

    def entries(self):
        """Both sections in declaration order, fixed first."""
        return self.fixed + self.variable

    def by_id(self, gid):
        for a in self.entries():
            if a.id == gid:
                return a
        return None

    def ids(self):
        return [a.id for a in self.entries()]

    def is_fixed_id(self, gid) -> bool:
        return any(a.id == gid for a in self.fixed)

    def is_world_id(self, gid) -> bool:
        return any(a.id == gid for a in self.world)


@dataclass
class PropertiesDoc:
    properties: tuple = ()   # tuple[Goal, ...]

    @classmethod
    def from_json(cls, data, *, where="properties"):
        arr = _as_list(_require(data, "properties", where), f"{where}.properties")
        return cls(tuple(
            Goal.from_json(g, where=f"{where}.properties[{i}]")
            for i, g in enumerate(arr)
        ))

    def to_json(self):
        return {"vocab_version": VOCAB_VERSION,
                "properties": [g.to_json() for g in self.properties]}

    def by_id(self, gid):
        for g in self.properties:
            if g.id == gid:
                return g
        return None

    def ids(self):
        return [g.id for g in self.properties]


# A scenario name doubles as the artifact directory name, so it is gated to
# path-safe characters at parse time rather than failing inside the store.
_SCENARIO_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


@dataclass
class NamedScenario:
    """One row of the scenario table: ``{name, conditions}``.

    Conditions are stated relative to the flow state and may only assign
    variable dimensions; a fixed fact is already applied unconditionally. A
    dimension the conditions do not mention takes its flow-state value, and an
    empty list is legal and means the base world itself.
    """
    name: str
    conditions: tuple = ()   # tuple[Point, ...], sorted by _key

    def __post_init__(self):
        self.conditions = tuple(sorted(self.conditions, key=lambda p: p._key()))

    def condition_key(self):
        """Two scenarios with the same condition set are the same world."""
        return frozenset(p._key() for p in self.conditions)

    @classmethod
    def from_json(cls, d, assumptions, *, where="scenario"):
        name = str(_require(d, "name", where))
        w = f"{where}[{name}]"
        if not _SCENARIO_NAME.match(name):
            raise LibParseError(
                f"{w}: scenario name must match [A-Za-z][A-Za-z0-9_-]* — it doubles "
                f"as the artifact directory name"
            )
        if name in ("base", "root"):
            raise LibParseError(
                f"{w}: the name {name!r} is reserved for the run's fixed layer "
                f"(flow + fixed). Its artifacts are the build_root step's own "
                f"now, so they no longer share this namespace — but its apply "
                f"sessions still report under the identity 'root', and a "
                f"scenario by that name would be read as the same thing"
            )
        raw = _as_list(_require(d, "conditions", w), f"{w}.conditions")
        points = tuple(
            Point.from_ref(p, assumptions, where=f"{w}.conditions[{i}]")
            for i, p in enumerate(raw))
        seen = set()
        for p in points:
            if p.ref_id in seen:
                raise LibParseError(f"{w}: assumption {p.ref_id!r} is assigned twice")
            seen.add(p.ref_id)
            if assumptions.is_fixed_id(p.ref_id):
                raise LibParseError(
                    f"{w}: condition on {p.ref_id!r}, which is a fixed fact; conditions "
                    f"may only assign variable dimensions — the engine applies every "
                    f"fixed entry unconditionally"
                )
            a = assumptions.by_id(p.ref_id)
            if p.subtype not in a.subtypes:
                raise LibParseError(
                    f"{w}: condition assigns {p.ref_id!r} = {p.subtype!r}, which is not "
                    f"in its declared domain {list(a.subtypes)}"
                )
        return cls(name=name, conditions=points)

    def to_json(self):
        return {"name": self.name,
                "conditions": [p.to_json() for p in self.conditions]}


@dataclass
class Claim:
    """One claim: ``{property, scenarios}`` — the names of the scenarios this
    goal is asserted under, one run per scenario, aggregated by conjunction.
    Several names mean the document offers several alternative lines of
    defence, which reads as an "or" on the premise side.
    """
    property: str
    scenarios: tuple = ()   # tuple[str, ...] — scenario names

    @classmethod
    def from_json(cls, d, *, where="claim"):
        pid = str(_require(d, "property", where))
        w = f"{where}[{pid}]"
        raw = _as_list(_require(d, "scenarios", w), f"{w}.scenarios")
        if not raw:
            raise LibParseError(f"{w}.scenarios: at least one scenario name is required; "
                                f"drop the claim instead")
        names = []
        for i, n in enumerate(raw):
            if not isinstance(n, str):
                raise LibParseError(
                    f"{w}.scenarios[{i}]: must be a scenario name (a string); an inline "
                    f"scenario array is the v8 shape — v9 declares scenarios once in the "
                    f"top-level 'scenarios' table and references them by name"
                )
            if n in names:
                raise LibParseError(f"{w}.scenarios[{i}]: duplicate scenario name {n!r}")
            names.append(n)
        return cls(property=pid, scenarios=tuple(names))

    def to_json(self):
        return {"property": self.property, "scenarios": list(self.scenarios)}


@dataclass
class ClaimsDoc:
    """claims.json: the scenario table plus the list of claims. ``property``
    references properties.json, conditions reference assumptions.json, and
    claims reference the scenario table by name. A scenario the table declares
    but no claim names is rejected."""
    scenarios: tuple = ()    # tuple[NamedScenario, ...]
    claims: tuple = ()       # tuple[Claim, ...]

    @classmethod
    def from_json(cls, data, assumptions, *, where="claims"):
        if "claims" not in data and "properties" in data:
            raise LibParseError(
                f"{where}: the top-level key is 'properties', so this looks like a "
                f"properties.json; claims.json uses 'scenarios' and 'claims'"
            )
        if "scenarios" not in data:
            raise LibParseError(
                f"{where}: missing the top-level 'scenarios' table; v9 declares each "
                f"named scenario once ({{name, conditions}}) and claims reference the "
                f"names — inline scenario arrays are the v8 shape"
            )
        table = tuple(
            NamedScenario.from_json(s, assumptions, where=f"{where}.scenarios[{i}]")
            for i, s in enumerate(_as_list(data["scenarios"], f"{where}.scenarios")))
        seen_names = set()
        for s in table:
            if s.name in seen_names:
                raise LibParseError(f"{where}: duplicate scenario name {s.name!r}")
            seen_names.add(s.name)
        arr = _as_list(_require(data, "claims", where), f"{where}.claims")
        items = tuple(
            Claim.from_json(c, where=f"{where}.claims[{i}]") for i, c in enumerate(arr))
        seen = set()
        referenced = set()
        for c in items:
            if c.property in seen:
                raise LibParseError(f"{where}: property {c.property!r} has more than one claim")
            seen.add(c.property)
            for n in c.scenarios:
                if n not in seen_names:
                    raise LibParseError(
                        f"{where}.claims[{c.property}]: dangling scenario name {n!r}; "
                        f"the table declares {sorted(seen_names)}")
                referenced.add(n)
        dead = [s.name for s in table if s.name not in referenced]
        if dead:
            raise LibParseError(
                f"{where}: dead scenarios {dead} — declared in the table but referenced "
                f"by no claim; drop them or name them in a claim")
        return cls(scenarios=table, claims=items)

    def to_json(self):
        return {"vocab_version": VOCAB_VERSION,
                "scenarios": [s.to_json() for s in self.scenarios],
                "claims": [c.to_json() for c in self.claims]}

    def scenario_by_name(self, name):
        for s in self.scenarios:
            if s.name == name:
                return s
        return None

    def by_property(self, pid):
        for c in self.claims:
            if c.property == pid:
                return c
        return None

    def property_ids(self):
        return [c.property for c in self.claims]


@dataclass
class ResultsDoc:
    """results.json: one verdict per property, the answer for user 1."""
    results: tuple = ()      # tuple[Result, ...]
    protocol_id: str | None = None

    @classmethod
    def from_json(cls, data, *, where="results"):
        arr = _as_list(_require(data, "results", where), f"{where}.results")
        return cls(
            results=tuple(
                Result.from_json(r, where=f"{where}.results[{i}]") for i, r in enumerate(arr)),
            protocol_id=data.get("protocol_id"),
        )

    def to_json(self):
        out = {"vocab_version": VOCAB_VERSION}
        if self.protocol_id is not None:
            out["protocol_id"] = self.protocol_id
        out["results"] = [r.to_json() for r in self.results]
        return out

    def by_id(self, gid):
        for r in self.results:
            if r.id == gid:
                return r
        return None

    def ids(self):
        return [r.id for r in self.results]
