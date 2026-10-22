#!/usr/bin/env python3
"""Reproduce the paper's tables from the published corpus and run records.

VerdictBench supplies the denominators; Orrery run records supply the
numerators, read from ``<run>/eval/summary.json``; KB catalog sizes come from
the realizer registry in this checkout. A unit with no completed run is emitted
as ``\\ph`` rather than guessed. No LLM or ProVerif is called.

Writes into ``reproduced/``: results.md, results.tex, results.csv,
results.json, measured.tex (the macros the paper consumes) and
dataset_rows.tex, plus a coverage report on stdout.

Usage (from the paper repo root or anywhere):

    python -m experiments.reproduce
    python -m experiments.reproduce --agg mean --last 3
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from experiments.batches import PAPER_PROVERIF

ROOT = Path(__file__).resolve().parent.parent


def _default_lib() -> Path:
    """Find VerdictBench in the artifact first, then beside a source checkout."""
    candidates = (ROOT / "VerdictBench", ROOT.parent / "VerdictBench")
    return next((path for path in candidates if path.is_dir()), candidates[0])


LIB_DEFAULT = _default_lib()

#: The three paper batches. Only runs under these roots are counted;
#: auxiliary work roots beside them on the server are outside this manifest.
BATCHES = ("main", "baseline", "claims")
BATCH_ROOTS = {
    "main": ("main",),
    "baseline": ("baseline",),
    "claims": ("claims",),
}
RUNS_DEFAULT = tuple(
    ROOT / "runs" / name
    for batch in BATCHES
    for name in BATCH_ROOTS[batch]
)

# A path segment naming a document version or draft, used for the Vers. column:
# units differing only below one version segment count as one version.
VERSION_RE = re.compile(r"(?i)^(draft|rev|revision|v\d|ts\d|.*-v\d)")

# The family table. One row per family in the paper's tables, in table order.
# ``prefix`` matches the unit path relative to VerdictBench and the longest
# match wins, so nested families are unambiguous. ``stem`` is the LaTeX macro
# stem: "Edhoc" produces \scEdhocMatch and \scEdhocProps.
FAMILIES = [
    # prefix, stem, display name, source label, group
    ("academic/NSPK",                            "NspkPk",   "Needham--Schroeder PK", "academic", "academic"),
    ("academic/NSSK",                            "NsskSk",   "Needham--Schroeder SK", "academic", "academic"),
    ("academic/Denning-Sacco",                   "DenSac",   "Denning--Sacco",        "academic", "academic"),
    ("academic/Kao-Chow",                        "KaoChow",  "Kao--Chow",             "academic", "academic"),
    ("academic/Otway-Rees",                      "Otway",    "Otway--Rees",           "academic", "academic"),
    ("academic/Yahalom",                         "Yahalom",  "Yahalom",               "academic", "academic"),
    ("academic/wide-mouth-frog",                 "Wmf",      "Wide-Mouth Frog",       "academic", "academic"),
    ("academic/Neuman-Stubblebine",              "Neuman",   "Neuman--Stubblebine",   "academic", "academic"),

    # One row per curated unit, not per document: EDHOC's draft-08 methods and
    # its draft-12 exchange are separate analyses. Where the corpus curates a
    # single subprotocol of a larger standard, the row names that subprotocol.
    ("rfc/EDHOC/draft-08/subprotocols/symmetric",  "EdhocPsk", "EDHOC-08 (PSK)",       "IETF", "named"),
    ("rfc/EDHOC/draft-12/subprotocols/dh",         "EdhocDh",  "EDHOC-12 (static DH)", "IETF", "named"),
    ("rfc/IKEV2",                                "Ikev",     "IKEv2 (signature)",     "IETF",     "named"),
    ("rfc/TLS13/draft18",                        "TlsEight", "TLS 1.3 draft-18",      "IETF",     "named"),
    ("rfc/TLS13/draft20",                        "TlsTwenty","TLS 1.3 draft-20",      "IETF",     "named"),
    ("rfc/OAuth-2.0",                            "Oauth",    "OAuth 2.0 (MAC)",       "IETF",     "named"),

    ("3gpp/5G-AKA",                              "FiveG",    "5G AKA",                "3GPP",     "named"),

    ("informal/FIDO",                            "Fido",     "FIDO UAF (registration)", "industry", "named"),
    ("informal/Signal",                          "Pqxdh",    "Signal PQXDH",          "industry", "named"),

    # ISO last, matching the paper's tables, which close with the two
    # aggregated ISO rows.
    ("ISO/11770-2-symmetric-techniques",         "IsoKtwo",   "ISO/IEC 11770-2",      "ISO",      "iso"),
    ("ISO/11770-3-asymmetric-techniques",        "IsoKthree", "ISO/IEC 11770-3",      "ISO",      "iso"),
    ("ISO/11770-4-weak-secrets",                 "IsoKfour",  "ISO/IEC 11770-4",      "ISO",      "iso"),
    ("ISO/11770-7-cross-domain-key-exchange",    "IsoKseven", "ISO/IEC 11770-7",      "ISO",      "iso"),
    ("ISO/9798-2-symmetric-encipherment",        "IsoAtwo",   "ISO/IEC 9798-2",       "ISO",      "iso"),
    ("ISO/9798-3-digital-signature",             "IsoAthree", "ISO/IEC 9798-3",       "ISO",      "iso"),
    ("ISO/9798-4-cryptographic-check",           "IsoAfour",  "ISO/IEC 9798-4",       "ISO",      "iso"),
    ("ISO/9798-5-zero-knowledge",                "IsoAfive",  "ISO/IEC 9798-5",       "ISO",      "iso"),
    ("ISO/9798-6-manual-data-transfer",          "IsoAsix",   "ISO/IEC 9798-6",       "ISO",      "iso"),
]

#: Curated units VerdictBench holds that this paper does not report. They are
#: dropped from every table and from every \lib* total, so the totals stay the
#: sum of what the tables show. A unit here is a deliberate omission; anything
#: else missing from FAMILIES is reported as unmapped.
EXCLUDED = (
    "rfc/EAP-AKA-prime",     # dropped from the paper
    "informal/Bluetooth",    # dropped from the paper
    "3gpp/AKMA",             # dropped from the paper
    # Covered by the other two EDHOC analyses, and it exhausted the verifier
    # budget on every verdict it reached.
    "rfc/EDHOC/draft-08/subprotocols/asymmetric",
)

#: Document-only benchmark entries counted by the paper but not evaluated.
#: Scope metadata, like FAMILIES and EXCLUDED; no numerator comes from it. The
#: names stay here because an anonymous artifact may withhold the documents.
PAPER_DOCUMENT_ONLY = (
    "3gpp/QS-Hybrid-KEM",
    "3gpp/TETRA",
    "ISO/9798-1-general",
    "NIST/SP-800-56A",
    "NIST/SP-800-56B",
    "rfc/EDHOC/9528",
    "rfc/Kerberos-V5",
    "rfc/OAuth-2.0/6749",
    "rfc/PKINIT",
    "rfc/QUIC",
    "rfc/SSHv2",
    "rfc/TLS13/8446",
    "rfc/TLS13/draft21",
)

#: The families AutoSM's benchmark also covers (its Table IV), for the
#: head-to-head of tab:llmaided. AutoSM has no Wide-Mouth Frog and its
#: "Stubblebine" is our Neuman--Stubblebine; its EDHOC entry is an excerpt of a
#: draft-02 section, so the PSK method of draft-08 stands in for it.
AUTOSM_OVERLAP = ("NspkPk", "NsskSk", "DenSac", "KaoChow", "Otway", "Yahalom",
                  "Neuman", "EdhocPsk")

PLACEHOLDER = r"\ph{}"

#: Repeat count to fold over when data/setup.tex cannot be read. It is the
#: paper's \nRuns, and the fallback stays a fixed window rather than a unit's
#: whole run history.
DEFAULT_REPEATS = 3


def _load(path: Path):
    """Parse a JSON file, or return an empty mapping when it is not there."""
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _value_facts(doc: dict) -> set:
    """The initial-knowledge facts the corpus states, as Orrery scores them.

    A fact is a value name plus the set of values it derives from, matching
    Orrery's modules/scoring/rules.py::_value_facts. Both the source list and
    the inventory are sets, so duplicates count once and the denominator can be
    read off the corpus instead of off a run.
    """
    return {(v.get("name"), tuple(sorted(v.get("derived_from") or [])))
            for v in doc.get("values", [])}


class Unit:
    """One curated analysis unit: a directory carrying claims/ and results/."""

    def __init__(self, lib: Path, path: Path):
        self.path = path
        self.rel = str(path.relative_to(lib))

        props = _load(path / "claims" / "properties.json")["properties"]
        claims_doc = _load(path / "claims" / "claims.json")
        assums = _load(path / "claims" / "assumptions.json")
        results = _load(path / "results" / "results.json")["results"]

        # Every declaration the analysis states, which is what a
        # setup-extraction run is scored against: world tier, fixed facts, and
        # the dimensions it varies.
        self.n_decls = (len(assums.get("world", [])) + len(assums.get("fixed", []))
                        + len(assums.get("variable", [])))
        self.n_props = len(props)
        self.n_tmodels = len(claims_doc.get("scenarios", []))
        self.n_verdicts = sum(len(c.get("scenarios", [])) for c in claims_doc.get("claims", []))
        self.n_world = len(assums.get("world", []))
        self.n_fixed = len(assums.get("fixed", []))
        self.n_variable = len(assums.get("variable", []))

        # The initial-knowledge denominator, a property of the corpus rather
        # than of a run: the same number for every run of this unit, never
        # averaged.
        self.n_princ_items = len(_value_facts(_load(path / "flow" / "principals.json")))

        verdicts = [r.get("verdict") for r in results]
        self.n_false = sum(1 for v in verdicts if v == "false")
        self.n_unknown = sum(1 for v in verdicts if v == "unknown")
        self.n_true = sum(1 for v in verdicts if v == "true")

    def version_label(self, family_prefix: str) -> str:
        """The version segment of this unit's path, "" when the family has one."""
        rel = Path(self.rel).relative_to(family_prefix)
        segs = [s for s in rel.parts if s != "subprotocols"]
        hits = [s for s in segs if VERSION_RE.match(s)]
        return hits[0] if hits else ""


def _under(rel: str, prefix: str) -> bool:
    """Is this unit path inside that family prefix?"""
    return rel == prefix or rel.startswith(prefix + "/")


def scan_lib(lib: Path):
    r"""The corpus this paper reports, as units grouped by family.

    Returns (units, by_family, document-only entries, unmapped, excluded).
    FAMILIES is the single definition of the corpus: a unit it does not name is
    counted nowhere. EXCLUDED marks a deliberate omission; anything else left
    out comes back as unmapped and needs a decision.
    """
    units, unmapped, excluded = [], [], []
    for props in sorted(lib.rglob("claims/properties.json")):
        unit_dir = props.parent.parent
        rel = str(unit_dir.relative_to(lib))
        if any(_under(rel, p) for p in EXCLUDED):
            excluded.append(rel)
            continue
        if not (unit_dir / "results" / "results.json").is_file():
            unmapped.append((rel, "has claims/ but no results/results.json"))
            continue
        units.append(Unit(lib, unit_dir))

    by_family = defaultdict(list)
    prefixes = sorted((f[0] for f in FAMILIES), key=len, reverse=True)
    kept = []
    for u in units:
        hit = next((p for p in prefixes if _under(u.rel, p)), None)
        if hit is None:
            unmapped.append((u.rel, "no family prefix matches; add it to FAMILIES"))
        else:
            by_family[hit].append(u)
            kept.append(u)
    units = kept

    # Document-only entries: a normalized document with no curated analysis
    # anywhere beneath it. An excluded family is not one of these.
    observed_doc_only = []
    for main in lib.rglob("source/main"):
        d = main.parent.parent
        rel = str(d.relative_to(lib))
        if any(_under(rel, p) or _under(p, rel) for p in EXCLUDED):
            continue
        if not any(d.rglob("claims/properties.json")):
            observed_doc_only.append(rel)

    unexpected_doc_only = sorted(set(observed_doc_only) - set(PAPER_DOCUMENT_ONLY))
    unmapped += [(rel, "document-only entry is not in PAPER_DOCUMENT_ONLY")
                 for rel in unexpected_doc_only]
    # A review artifact may omit restricted document-only sources, so the
    # declared list is authoritative rather than what is on disk.
    doc_only = list(PAPER_DOCUMENT_ONLY)

    return units, by_family, sorted(set(doc_only)), unmapped, sorted(set(excluded))


def _first_start(run_dir: Path) -> dict | None:
    """The ``run_started`` event that opened a run, or None when it left none.

    A restart rewrites run.json in place, so its ``from_node`` describes the
    last restart and looks exactly like a stage experiment launched at that
    node. The event log is append-only, so its first ``run_started`` still says
    what the run set out to do.
    """
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("t") == "run_started":
                    return ev.get("data") or {}
    except OSError:
        return None
    return None


class RunScore:
    """One completed run, as the numbers its own scoring pass left on disk.

    The source is ``<run>/eval/summary.json``, which the orchestrator writes
    after every step it can score (Orrery, pipeline/main.py::_score_node).
    Every denominator here is the corpus's own, so a threat model the run never
    built still counts against it.
    """

    def __init__(self, run_dir: Path, summary: dict, meta: dict = None):
        meta = meta or {}
        self.run_dir = run_dir
        self.nodes = meta.get("nodes") or {}
        # A run naming a start node, a non-terminal stop node, or a parent is a
        # stage experiment or a fork, and its scores stay out of the tables.
        # Stopping at cross_check is still a full pass: cross_check is the
        # pipeline's terminal node and the batch runner records that endpoint.
        self.started = meta.get("started", "") or meta.get("finished_at", "")
        self.batch = "main"   # set by scan_all_runs from the work_root
        self.resumed = False
        if meta.get("experiment") == "oneshot":
            self._read_oneshot(run_dir, meta)
            return
        self.from_node = meta.get("from_node")
        self.to_node = meta.get("to_node")
        self.forked_from = meta.get("forked_from")
        # A restart after a crash keeps the run end to end, so the event log,
        # not run.json, decides whether an entry point was the run's own
        # beginning or a resume.
        start = _first_start(run_dir)
        self.resumed = bool(self.from_node and start is not None
                            and not start.get("from_node"))
        if self.resumed:
            self.from_node = None
        terminal_stop = self.to_node in (None, "cross_check")
        self.kind = "e2e" if (not self.from_node and terminal_stop
                              and not self.forked_from) else "stage"
        prod = summary.get("products") or {}

        def block(node, field="den"):
            """The node's scored block, and which of four states it is in.

            A node is scored when it left numbers, supplied when the run was
            handed its artifact, absent when it never ran, and failed when the
            scoring pass itself errored. Only "scored" carries numbers; the
            other three return None, which is an absence rather than a zero.
            """
            b = prod.get(node)
            if not isinstance(b, dict):
                return None, "absent"
            if b.get("supplied"):
                return None, "supplied"
            if b.get(field) is None:
                return None, "failed"
            return b, "scored"

        verdicts, self.agg_state = block("aggregate")
        verdicts = verdicts or {}
        cells = verdicts.get("cells") or {}
        # The property's own answer, a three-valued conjunction over the threat
        # models that claim it, plus the cells behind it.
        self.props_total = verdicts.get("den", 0)
        self.props_match = verdicts.get("num", 0)
        self.cases_total = cells.get("den", 0)
        self.cases_match = cells.get("num", 0)
        # Initial knowledge, the stage between the document and the flow model.
        princ, self.princ_state = block("extract_principals")
        princ = princ or {}
        self.princ_total = princ.get("den", 0)
        self.princ_match = princ.get("num", 0)
        # The two flow-model gates, booleans per run and pass rates over runs.
        # The node's status in run.json, not the presence of a scored block,
        # decides whether this run is in the gate's denominator: a failed
        # extract_flow leaves no block and no eval/summary.json, so the block
        # alone cannot tell a failure from a run stopped early on purpose.
        node = self.nodes.get("extract_flow")
        flow, block_state = block("extract_flow", "flow_typecheck")
        flow = flow or {}
        # A restart marks every node before its entry point skipped, including
        # stages this run had already run itself. Such a node counts as
        # supplied only when run.json records a handed-in flow model.
        own_flow = (self.resumed and block_state != "supplied"
                    and not meta.get("flow"))
        if node == "failed":
            self.flow_state, self.syn, self.reach = "scored", False, False
        elif node == "ok" or (node == "skipped" and own_flow):
            if block_state != "scored":
                # The node cleared but the run died before the scoring pass, so
                # there is no eval/summary.json. extract_flow runs both gates
                # itself and writes checks.json beside its model, which is what
                # the summary block would have copied.
                hit = next(iter(sorted(run_dir.glob("*extract_flow*/checks.json"))), None)
                flow = _load(hit) if hit else {}
                block_state = "scored" if "flow_typecheck" in flow else "absent"
            self.flow_state = block_state
            self.syn = bool(flow.get("flow_typecheck"))
            self.reach = bool(flow.get("flow_reachability"))
        elif node == "skipped":
            # The flow model was handed to the run; nothing of ours to gate.
            self.flow_state, self.syn, self.reach = "supplied", False, False
        elif meta.get("status") == "failed":
            # The key is missing because the run died earlier in the chain. It
            # produced no model that clears typechecking, so it is a miss
            # rather than an absence; only a hand-stopped run sits the gate out.
            self.flow_state, self.syn, self.reach = "scored", False, False
        else:
            self.flow_state, self.syn, self.reach = "absent", False, False
        # The setup stages. In the main batch these are handed to the run and
        # come back "supplied"; a setup-extraction run reads them off the
        # document instead and leaves a score here.
        self.setup = {}
        for key, node in (("assum", "extract_assumptions"),
                          ("props", "extract_properties"),
                          ("claims", "extract_claims")):
            b, state = block(node)
            if state == "scored":
                # hit, declared, over-produced. The third separates an
                # extractor that proposes freely from one that proposes only
                # what it can ground; recall alone scores them the same.
                self.setup[key] = (b.get("num"), b.get("den"), b.get("extra") or 0)

        self.budgets = set()
        self.timeouts = read_timeouts(run_dir, self.budgets)
        cells = read_cells(run_dir, self.timeouts)
        self.answered, self.cells_matched = cells if cells else (None, None)
        self.n_timeout = len(self.timeouts)

        cost = read_cost(run_dir)
        self.extract_sec = cost.get("extract_sec")
        self.marginal_sec = cost.get("marginal_sec")
        self.tokens = cost.get("tokens")
        # The repair loop, projected by Orrery from its own ledger
        # (pipeline/repair.py). A submission is a check_report, not a model
        # round. A run with no ledger contributes nothing to the repair rows.
        rep = self.repair = _load(run_dir / "repair.json")
        self.sessions = rep.get("sessions", 0)
        self.repairs = rep.get("repairs", 0)
        self.first_pass = rep.get("first_pass", 0)
        self.cleared = rep.get("passed", 0)

    def _read_oneshot(self, run_dir: Path, meta: dict) -> None:
        """Score a one-prompt baseline run from what that pipeline leaves behind.

        It has no node ledger and no eval/summary.json, only per-scenario
        records, so the gates come from there: a scenario that produced a model
        at all cleared syntax, ``reach`` is the per-role reachability the main
        pipeline checks, and ``outcome`` carries the solver's own timeout.
        """
        scen = meta.get("scenarios") or []
        self.kind = "e2e"
        self.from_node = self.to_node = self.forked_from = None
        self.nodes, self.setup, self.timeouts, self.budgets = {}, {}, set(), set()
        self.repair, self.sessions, self.repairs = {}, 0, 0
        self.first_pass = self.cleared = 0
        self.extract_sec = meta.get("duration_s")
        self.marginal_sec = (meta["duration_s"] / len(scen)
                             if meta.get("duration_s") and scen else None)
        u = meta.get("usage") or {}
        self.tokens = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) or None

        ok = [x for x in scen if x.get("status") == "ok"]
        self.flow_state = "scored" if scen else "absent"
        self.syn = bool(ok)
        self.reach = bool(ok) and all((x.get("reach") or {}).get("all") for x in ok)
        self.n_timeout = sum(1 for x in scen if x.get("outcome") == "timeout")

        xc = _load(run_dir / "crosscheck.json")
        rows = xc.get("results") or []
        cells = xc.get("cells") or []
        self.agg_state = "scored" if rows else "absent"
        self.props_match = sum(1 for r in rows if r.get("match"))
        self.props_total = len(rows)
        self.cases_match = xc.get("cases_matched", 0)
        self.cases_total = xc.get("cases_compared", 0)
        self.princ_state = "absent"
        self.princ_match = self.princ_total = 0
        # A cell the solver timed out on is not an answer, the same rule the
        # main batch is scored under.
        answered = [c for c in cells if c.get("ours") not in ("timeout", "solver_limit")]
        self.answered = len(answered) if cells else None
        self.cells_matched = sum(1 for c in answered if c.get("match")) if cells else None


#: The last node that turns a document into the frozen root model. Everything
#: after it is per-threat-model work, the marginal cost the paper quotes.
EXTRACT_LAST = "build_root"


def _stamp(ts: str) -> float:
    """Seconds since the epoch for one event timestamp, or None if unparseable."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return None


def read_timeouts(run_dir: Path, budgets: set | None = None):
    """The cells this run never got an answer for, as {(scenario_key, goal)}.

    Some runs write "unknown" for a timeout, which is also what ProVerif says
    when it terminates without proving the goal; the ``solve_finished`` event
    keeps the two apart, so both kinds of run score on one scale. Solver budgets
    seen along the way are added to ``budgets``. A scenario is keyed by its
    assignment rather than its name, which is how cross_check writes it.
    """
    path = run_dir / "events.jsonl"
    budgets = set() if budgets is None else budgets
    if not path.is_file():
        return set()
    keys, out = {}, set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if '"scenario_started"' not in line and '"solve_finished"' not in line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        data, name = ev.get("data") or {}, ev.get("scenario")
        if ev.get("t") == "scenario_started":
            keys[name] = frozenset((p["id"], p["subtype"])
                                   for p in (data.get("assignment") or []))
        elif ev.get("t") == "solve_finished" and data.get("kind") in ("timeout", "solver_limit"):
            key = keys.get(name)
            if key is not None:
                out |= {(key, goal) for goal in (data.get("verdicts") or {})}
            # A timeout ran the budget out, so its duration is the budget. It
            # is read back from the run rather than from this machine's config,
            # which the runs on the server never used.
            if data.get("kind") == "timeout" and data.get("seconds"):
                budgets.add(int(round(data["seconds"] / 10.0) * 10))
    return out


def read_cells(run_dir: Path, timeouts):
    """(answered, matched) over the cells this run was cross-checked on, or
    None when the run left no cross_check.json.

    A cell in ``timeouts`` is not a wrong answer: it is left out of both
    numbers, while staying in the denominator the paper reports against, which
    is the corpus's own verdict count.
    """
    hits = sorted(run_dir.glob("*cross_check*/cross_check.json"))
    if not hits:
        return None
    doc = _load(hits[-1])
    answered = matched = 0
    for c in doc.get("cells") or []:
        key = frozenset((p["id"], p["subtype"]) for p in c.get("scenario") or [])
        if (key, c.get("id")) in timeouts:
            continue
        answered += 1
        matched += bool(c.get("match"))
    return answered, matched


def read_cost(run_dir: Path):
    """Wall-clock and tokens for one run, from its own event log.

    Keys, any of which may be absent: ``extract_sec`` from run start to the
    frozen root model, ``marginal_sec`` the mean seconds one threat model costs
    on that root, and ``tokens`` input plus output (``cached`` is a subset of
    input, not a third term). A run with no event log returns {} and sits out
    of the cost rows rather than counting as zero.
    """
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return {}
    start = end = None
    scen, tokens = [], 0
    open_scen = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t, ts, data = ev.get("t"), _stamp(ev.get("ts")), ev.get("data") or {}
        if ts is None:
            continue
        if t == "run_started":
            start = ts
        elif t == "node_finished" and ev.get("node") == EXTRACT_LAST:
            end = ts
        elif t == "scenario_started":
            open_scen[ev.get("scenario")] = ts
        elif t == "scenario_finished":
            began = open_scen.pop(ev.get("scenario"), None)
            if began is not None:
                scen.append(ts - began)
        elif t == "session_usage":
            tokens += (data.get("input_tokens") or 0) + (data.get("output_tokens") or 0)
    out = {}
    if start is not None and end is not None and end >= start:
        out["extract_sec"] = end - start
    if scen:
        out["marginal_sec"] = sum(scen) / len(scen)
    if tokens:
        out["tokens"] = tokens
    return out


def _newest_with(scores, key):
    """The last run in ``scores`` that scored setup stage ``key``, or None."""
    hits = [s for s in scores if key in s.setup]
    return hits[-1] if hits else None


def _through_symlink(root: Path, path: Path) -> bool:
    """Whether reaching ``path`` from ``root`` passes through a symlink."""
    cur = root
    for part in path.relative_to(root).parts:
        cur = cur / part
        if cur.is_symlink():
            return True
    return False


def declared_repeats(paper_root: Path):
    """The repeat count the paper claims, read from \\nRuns in data/setup.tex.

    It is how many times each unit is run, and also the window this script
    folds over. Falls back to DEFAULT_REPEATS when the file or the macro is
    missing, so the window never widens to a unit's whole run history.
    """
    f = paper_root / "data" / "setup.tex"
    m = re.search(r"\\newcommand\{\\nRuns\}\{(\d+)\}",
                  f.read_text(encoding="utf-8")) if f.is_file() else None
    return int(m.group(1)) if m else DEFAULT_REPEATS


def resolve_runs(roots) -> tuple[list[Path], list[str]]:
    """The run roots that exist, and a note for each one that does not.

    There is no fallback: a missing root means the mirror of the experiment
    server is incomplete, and reading some other tree instead would republish
    another batch's numbers under the same macros.
    """
    roots = [Path(r) for r in (roots or ())]
    live = [r for r in roots if r.is_dir()]
    notes = [f"{r}: not present on this machine" for r in roots if not r.is_dir()]
    return live, notes


def local_gt(gt: str, lib: Path) -> str:
    """A run's ground_truth path, rebased onto this machine's corpus.

    Runs record the server's checkout path; the part after the repository name
    identifies the unit, so rebasing on it scores a run recorded there against
    the copy here. A path naming no recognisable corpus is returned unchanged
    and shows up as unmatched rather than attaching to the wrong unit.
    """
    m = re.search(r"(?:^|/)%s/(.+)$" % re.escape(lib.name), gt or "")
    return str(lib / m.group(1)) if m else (gt or "")


def _oneshot_ground_truth(meta: dict) -> str | None:
    """The analysis unit named by a one-shot baseline record, or None.

    ``protocol_dir`` may hold the complete unit path or just the parent
    protocol, in which case ``subprotocol`` is appended exactly once. Raises
    ValueError when the path already names a different subprotocol, since that
    input is contradictory and would otherwise map to the wrong unit.
    """
    gt = meta.get("protocol_dir")
    if not gt:
        return None
    gt = gt.rstrip("/")
    subprotocol = meta.get("subprotocol")
    if not subprotocol:
        return gt
    suffix = f"/subprotocols/{subprotocol}"
    if gt.endswith(suffix):
        return gt
    if gt.endswith("/subprotocols"):
        return f"{gt}/{subprotocol}"
    if "/subprotocols/" in gt:
        raise ValueError(
            f"one-shot protocol_dir {gt!r} conflicts with subprotocol "
            f"{subprotocol!r}"
        )
    return f"{gt}{suffix}"


_VERSIONED_RUN_RE = re.compile(r"^(?P<series>.+)-v(?P<number>[1-9]\d*)$")


def _sort_run_scores(scores):
    """Oldest to newest, using an explicit ``-vN`` sequence when present.

    Migrated batches can carry naive ``started`` timestamps written under
    different timezone conventions. When every run belongs to one numbered
    series, that series is the unambiguous order and ``v10`` follows ``v9``;
    mixed or unnumbered histories keep the timestamp order.
    """
    numbered = [(_VERSIONED_RUN_RE.fullmatch(s.run_dir.name), s) for s in scores]
    if numbered and all(match is not None for match, _ in numbered):
        series = {match.group("series") for match, _ in numbered}
        if len(series) == 1:
            return [s for match, s in sorted(
                numbered, key=lambda pair: int(pair[0].group("number")))]
    return sorted(scores, key=lambda s: (s.started, s.run_dir.name))


def scan_runs(runs_root: Path, lib: Path | None = None):
    """Map VerdictBench unit dir -> [RunScore], newest last.

    Returns (by_unit, skipped, partial), the last two carrying (path, reason)
    for runs that could not be scored and for runs counted in the flow gates
    only. ``_history`` copies of superseded node output are skipped so a
    re-entered run is not counted twice.
    """
    by_unit = defaultdict(list)
    skipped, partial = [], []
    if not runs_root.is_dir():
        return by_unit, [(str(runs_root), "run directory does not exist")], []

    for meta_path in sorted(runs_root.rglob("run.json")):
        if "_history" in meta_path.parts:
            continue
        run_dir = meta_path.parent
        # ``latest`` is a symlink to one of the runs beside it, so walking into
        # it would reach the same run twice. Orrery excludes symlinks the same
        # way in services/store/runs.py::run_dirs.
        if _through_symlink(runs_root, run_dir):
            continue
        meta = _load(meta_path)
        summary_path = run_dir / "eval" / "summary.json"
        nodes = meta.get("nodes") or {}
        gt = meta.get("ground_truth")
        if not gt and meta.get("protocol_dir"):
            gt = _oneshot_ground_truth(meta)
        if not gt:
            skipped.append((str(run_dir.relative_to(runs_root)), "run.json has no ground_truth path"))
            continue
        # A run with no summary is still a run: Orrery writes eval/summary.json
        # only after the scoring pass. It carries no numerators, but run.json
        # records which stages it attempted and how each ended, which is all the
        # two flow gates need, so it is kept as partial rather than skipped.
        if not summary_path.is_file() and not meta.get("experiment"):
            status = nodes.get("aggregate", "not reached")
            if nodes.get("extract_flow") not in ("ok", "failed"):
                skipped.append((str(run_dir.relative_to(runs_root)),
                                f"no eval/summary.json (aggregate: {status})"))
                continue
            partial.append((str(run_dir.relative_to(runs_root)),
                            f"no eval/summary.json, counted in the flow gates only "
                            f"(extract_flow: {nodes['extract_flow']})"))
        by_unit[local_gt(gt, lib) if lib else str(Path(gt))].append(
            (meta.get("started", ""), RunScore(run_dir, _load(summary_path), meta)))

    return ({k: _sort_run_scores([s for _, s in v])
             for k, v in by_unit.items()}, skipped, partial)


#: Every per-run number folded across repeats. The counts fold by the chosen
#: statistic; the two flow gates are booleans per run and fold into the pass
#: count behind the paper's Syn and Reach columns.
_COUNTS = ("props_match", "cases_match", "princ_match")
_RATES = ("syn", "reach")


def fold(scores, how: str, unit=None):
    """Fold repeated runs of one unit into one dict of numbers, or None.

    ``how`` is the statistic (latest, best, mean, median) and ``unit`` supplies
    the corpus's denominators; only numerators fold. Each stage folds over the
    runs that scored that stage alone, counted in ``*_runs``, and a run whose
    own denominator disagrees with the corpus goes to ``stale`` instead.
    Raises SystemExit on an unknown ``how``.
    """
    if not scores:
        return None

    def one(values):
        if how == "latest":
            return values[-1]
        if how == "best":
            return max(values)
        if how == "mean":
            return round(sum(values) / len(values), 1)
        if how == "median":
            return sorted(values)[len(values) // 2]
        raise SystemExit(f"unknown --agg {how!r}")

    def fold_over(subset, key):
        return one([getattr(s, key) for s in subset]) if subset else None

    agg = [s for s in scores if s.agg_state == "scored"]
    stale = [s for s in agg if unit is not None and s.props_total != unit.n_props]
    agg = [s for s in agg if s not in stale]
    princ = [s for s in scores if s.princ_state == "scored"]
    # A run scored against an older principals.json counted hits against facts
    # the corpus no longer states, so pairing it with today's denominator would
    # report a fraction nobody computed. Dropped and named in princ_drift.
    princ_stale = ([s for s in princ if s.princ_total != unit.n_princ_items]
                   if unit is not None else [])
    princ = [s for s in princ if s not in princ_stale]
    flow = [s for s in scores if s.flow_state == "scored"]

    # AutoSM scores a run all-or-nothing: the model counts only when every
    # property verifies (Definition 7 of that paper). The head-to-head folds
    # the same way, beside the per-property count the rest of the paper uses.
    allpass = [s for s in agg if s.props_total and s.props_match == s.props_total]
    # Cells the solver actually answered, and how many of those matched. A run
    # with no cross_check has neither and sits out of both.
    xchk = [s for s in agg if s.answered is not None]
    out = {
        "answered": fold_over(xchk, "answered"),
        "cells_matched": fold_over(xchk, "cells_matched"),
        "n_timeout": fold_over(xchk, "n_timeout"),
        "allpass": len(allpass) if agg else None,
        "props_match": fold_over(agg, "props_match"),
        "cases_match": fold_over(agg, "cases_match"),
        "princ_match": fold_over(princ, "princ_match"),
        # The corpus's own count, never folded: averaging it across runs would
        # invent a denominator. Runs on a different scale are already out of
        # ``princ``, and a unit handed its principals reports nothing here.
        "princ_total": (unit.n_princ_items
                        if princ and unit is not None else
                        fold_over(princ, "princ_total")),
        # Repair rounds: submissions beyond the first, averaged over the runs
        # that submitted anything. A run with no ledger sits this out.
        "rep_rounds": (sum(s.repairs for s in rep) / len(rep)) if (
            rep := [s for s in scores if s.sessions]) else None,
        "rep_runs": len(rep),
        "agg_runs": len(agg), "princ_runs": len(princ), "flow_runs": len(flow),
        "runs": len(scores), "stale": len(stale),
        # Why a run sat out a stage, so the report can say so instead of
        # printing a numerator that rests on fewer runs than the row claims.
        "states": Counter(f"{stage}:{st}"
                          for s in scores
                          for stage, st in (("verdicts", s.agg_state),
                                            ("principals", s.princ_state),
                                            ("flow", s.flow_state))
                          if st != "scored"),
    }
    # The runs scored against a different corpus than the one being reported,
    # so the report can say how many runs a Princ cell rests on.
    out["princ_stale"] = len(princ_stale)
    out["princ_drift"] = sorted({s.princ_total for s in princ_stale})
    # A gate is pass-or-fail per run, so it folds into the count that cleared
    # it over ``gate_runs`` attempts rather than by the chosen statistic. The
    # paper reports both halves, since at three runs a percentage hides them.
    out.update({k: (sum(bool(getattr(s, k)) for s in flow) if flow else None)
                for k in _RATES})
    out["gate_runs"] = len(flow) or None
    return out


DECISION_PROBE = r"""
import json
from orrery.nodes.apply.realizers import VOCAB, REALIZERS
from orrery.nodes.inject.injectors import INJECTORS
from orrery.modules.kbase.primitives.catalog import all_primitives
from orrery.modules.kbase.modeling_idioms.catalog import identity_idioms
from orrery.modules.kbase.modeling_idioms.structure import structure_idioms
from orrery.modules.kbase.modeling_idioms.time_variant import time_variant_idioms
axes = VOCAB.axes()
values = [(a, s) for a in axes for s in VOCAB.dimension_values(a)]
noop = [k for k in values if REALIZERS[k].is_noop]
stub = [k for k in values if VOCAB.is_stub(*k)]
forms = sum(len(REALIZERS[k].writings or ()) for k in values)
prims = all_primitives()
ident = identity_idioms()
struct = structure_idioms()
timev = time_variant_idioms()
# The Equivalence injectors are the unimplemented biprocess machinery behind
# privacy, not a property family the paper declares; the counts exclude them.
props = {k: v for k, v in INJECTORS.items() if k[0] != "Equivalence"}
print(json.dumps({
    "categories": len({VOCAB.obj_of(a) for a in axes}),
    "dimensions": len(axes),
    "values": len(values),
    "neutral": len(noop),
    "implemented": len(values) - len(stub),
    "rewriting": len(values) - len(noop) - len(stub),
    "declared_only": len(stub),
    "forms": forms,
    "prop_families": len({k[0] for k in props}),
    "prop_levels": len(props),
    "prop_refused": sum(1 for v in props.values()
                        if getattr(v, "unimplemented", False)),
    "prim_entries": len(prims),
    "prim_render": sum(1 for x in prims if x.delivery == "render"),
    "prim_lookup": sum(1 for x in prims if x.delivery == "lookup"),
    "identity_entries": len(ident),
    "machineries": len({i.machinery for i in ident}),
    "structure_entries": len(struct),
    "time_entries": len(timev),
    "lib_entries": len(prims) + len(ident) + len(struct) + len(timev),
}))
"""


def scan_decisions(aif_root: Path, python: str):
    try:
        out = subprocess.run(
            [python, "-c", DECISION_PROBE], cwd=str(aif_root), capture_output=True,
            text=True, timeout=120, env={"PYTHONPATH": str(aif_root), "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"could not run {python}: {e}"
    if out.returncode != 0:
        return None, (out.stderr.strip().splitlines() or ["unknown error"])[-1]
    return json.loads(out.stdout), None


def latex_int(n) -> str:
    if n is None:
        return PLACEHOLDER
    if isinstance(n, float):
        return f"{n:.1f}"
    s = str(n)
    return f"{s[:-3]}{{,}}{s[-3:]}" if len(s) > 3 else s


def frac(match, total) -> str:
    """``k/N`` for the report, with either half absent shown as the placeholder."""
    m = PLACEHOLDER if match is None else match
    n = PLACEHOLDER if total is None else total
    return f"{m}/{n}"


def scan_all_runs(roots, lib: Path | None = None):
    """scan_runs over several roots, merged.

    A unit's runs from two roots become one list ordered by start time, so the
    newest-wins rules hold across batches. Each run is also tagged with the
    batch its root names.
    """
    by_unit, skipped, partial = defaultdict(list), [], []
    # Two roots can name the same directory (a nested path, a symlinked mirror,
    # the same argument twice), and counting a run under both would double
    # every number it feeds.
    seen: set[Path] = set()
    for root in roots:
        b, s, p = scan_runs(root, lib)
        for k, v in b.items():
            fresh = [sc for sc in v if sc.run_dir.resolve() not in seen]
            seen.update(sc.run_dir.resolve() for sc in fresh)
            for sc in fresh:
                # A batch can span several explicitly named work roots. A
                # root outside BATCH_ROOTS counts as main, which keeps
                # ``--runs <ad-hoc mirror>`` usable.
                sc.batch = next(
                    (batch for batch, names in BATCH_ROOTS.items()
                     if root.name in names),
                    "main",
                )
            by_unit[k].extend(fresh)
        skipped += [(f"{root.name}/{rel}", why) for rel, why in s]
        partial += [(f"{root.name}/{rel}", why) for rel, why in p]
    return ({k: _sort_run_scores(v) for k, v in by_unit.items()},
            skipped, partial)


def build(lib: Path, runs_root, agg: str, kb, last: int | None = None):
    units, by_family, doc_only, unmapped, excluded = scan_lib(lib)
    roots, root_notes = resolve_runs(
        runs_root if isinstance(runs_root, (list, tuple)) else [runs_root])
    runs_by_unit, skipped_runs, partial_runs = scan_all_runs(roots, lib)
    skipped_runs = [(r, w) for r, w in skipped_runs]


    # A run whose ground_truth names no VerdictBench unit reaches no family,
    # and the lookups below cannot tell that miss from a unit nobody ran, so it
    # is reported here instead of vanishing.
    known = {str(u.path) for u in units}
    for gt in sorted(set(runs_by_unit) - known):
        rel = gt[len(str(lib)) + 1:] if gt.startswith(str(lib) + "/") else None
        if rel and any(_under(rel, p) for p in EXCLUDED):
            why = f"runs an EXCLUDED unit ({rel})"
        else:
            why = f"ground_truth names no VerdictBench unit ({gt or 'empty'})"
        for score in runs_by_unit[gt]:
            skipped_runs.append((
                f"{score.run_dir.parent.name}/{score.run_dir.name}", why))

    # The end-to-end runs each unit contributes, newest last, windowed by
    # ``last`` so an old configuration is not averaged with the current one.
    # Every consumer below reads this one mapping, so the window cannot drift
    # between the score, repair, and cost rows.
    e2e_by_unit = {}
    for gt, scores in runs_by_unit.items():
        runs = [s for s in scores if s.kind == "e2e" and s.batch == "main"]
        e2e_by_unit[gt] = runs[-last:] if last else runs

    # Repeat coverage is audited over the whole main batch, not the
    # reporting window, so ``--last 3`` cannot make a unit with four eligible
    # runs look as if it has three. Zero-run units stay in the list.
    repeat_target = declared_repeats(ROOT)
    main_repeats = []
    for unit in units:
        count = sum(
            1 for score in runs_by_unit.get(str(unit.path), [])
            if score.kind == "e2e" and score.batch == "main"
        )
        main_repeats.append({
            "unit": unit.rel,
            "runs": count,
            "missing": max(repeat_target - count, 0),
            "ready": count >= repeat_target,
        })

    stage_runs = []
    rows = []
    for prefix, stem, display, source, group in FAMILIES:
        fam = by_family.get(prefix, [])
        if not fam:
            # No unit under this prefix, so no row: the corpus does not hold
            # this protocol at all.
            continue
        versions = len({u.version_label(prefix) for u in fam}) if fam else 0
        def e2e(u):
            return e2e_by_unit.get(str(u.path), [])

        for u in fam:
            for score in runs_by_unit.get(str(u.path), []):
                if score.kind != "e2e":
                    stage_runs.append((display, score))

        # Setup extraction is its own experiment: a run that reads the
        # declarations, properties, and claims off the document instead of
        # being handed them. Runs are newest last, so the last one to score a
        # stage is the current configuration and earlier attempts are
        # superseded rather than averaged in.
        setup = {}
        for u in fam:
            # Setup extraction runs under the claims work_root only. A
            # main-batch setup score came from an inherited stage, not from
            # the document, and a baseline run never extracts one.
            claims_runs = [sc for sc in runs_by_unit.get(str(u.path), [])
                           if sc.batch == "claims"]
            for score in claims_runs:
                for key, pair in score.setup.items():
                    setup.setdefault(key, [0, 0, 0])
                    if score is _newest_with(claims_runs, key):
                        for i in range(3):
                            setup[key][i] += pair[i]

        scored = [(u, fold(e2e(u), agg, u)) for u in fam]
        covered = [(u, f) for u, f in scored if f]

        def whole(key, combine=sum):
            """One number for the family, combined over the units that scored
            this stage.

            A unit with no run for the stage contributes nothing, which pairs
            with a denominator the corpus fixes: it reads as zero recovered out
            of what that unit declares. A family where no unit scored the stage
            returns None, meaning not measured rather than measured as empty.
            """
            vals = [f[key] for _, f in covered if f[key] is not None]
            if not vals:
                return None
            out = combine(vals)
            return round(out, 1) if isinstance(out, float) else out

        def part(key):
            """Summed over the units that scored this stage, or None.

            These feed the \\scRun* totals, which are reported beside the
            scored units' own denominators, so a partial batch shows a
            smaller denominator rather than a partial whole-family sum.
            """
            vals = [f[key] for _, f in covered if f[key] is not None]
            if not vals:
                return None
            s = sum(vals)
            return round(s, 1) if isinstance(s, float) else s

        rows.append({
            "prefix": prefix, "stem": stem, "display": display,
            "source": source, "group": group,
            "units": len(fam),
            "versions": max(versions, 1) if fam else 0,
            "tmodels": sum(u.n_tmodels for u in fam),
            "props": sum(u.n_props for u in fam),
            "verdicts": sum(u.n_verdicts for u in fam),
            "world": sum(u.n_world for u in fam),
            "fixed": sum(u.n_fixed for u in fam),
            "variable": sum(u.n_variable for u in fam),
            "decls": sum(u.n_decls for u in fam),
            "covered_units": len(covered),
            # The units this family scored end to end, and what they declare,
            # so \scRun* can report reach directly instead of leaving it to be
            # inferred from which rows render as \ph{}.
            "scored_units": sum(1 for _, f in covered if f["props_match"] is not None),
            "scored_props": sum(u.n_props for u, f in covered
                                if f["props_match"] is not None),
            # The scored-subset numerators behind the \scRun* totals, against
            # the verdict denominator of the units that scored verdicts.
            "scored_verdicts": sum(u.n_verdicts for u, f in covered
                                   if f["cells_matched"] is not None),
            "part_match": part("props_match"),
            "part_verdicts_match": part("cells_matched"),
            "part_answered": part("answered"),
            "part_timeouts": part("n_timeout"),
            "part_syn": part("syn"),
            "part_reach": part("reach"),
            "part_gate_runs": part("gate_runs"),
            "part_rep": [f["rep_rounds"] for _, f in covered
                         if f["rep_rounds"] is not None],
            "props_match": whole("props_match"),
            "verdicts_match": whole("cases_match"),
            # The stage between the document and the flow model, and the two
            # gates on the flow model itself.
            "princ_match": whole("princ_match"),
            "princ_total": whole("princ_total"),
            # Summed over the family's units rather than averaged: the row asks
            # how often this family's flow generation cleared the gate, so a
            # unit with more runs weighs more.
            "syn": whole("syn"),
            "reach": whole("reach"),
            "gate_runs": whole("gate_runs"),
            "answered": whole("answered"),
            "cells_matched": whole("cells_matched"),
            "n_timeout": whole("n_timeout"),
            "allpass": whole("allpass"),
            "agg_runs": whole("agg_runs"),
            # Averaged over the family's units, each weighing the same: this
            # answers how many rounds one run of this protocol takes, not how
            # many the family consumed in total.
            "rep_rounds": whole("rep_rounds", lambda v: round(sum(v) / len(v), 1)),
            "runs": sum(len(e2e(u)) for u in fam),
            "runs_available": sum(1 for u in fam
                                  for s in runs_by_unit.get(str(u.path), [])
                                  if s.kind == "e2e" and s.batch == "main"),
            "stage_runs_n": sum(1 for u in fam
                                for s in runs_by_unit.get(str(u.path), [])
                                if s.kind != "e2e"),
            "stale_runs": sum(f["stale"] for _, f in covered),
            "princ_drift": sorted({d for _, f in covered for d in f["princ_drift"]}),
            "princ_stale_runs": sum(f["princ_stale"] for _, f in covered),
            "stage_counts": {k: sum(f[f"{k}_runs"] for _, f in covered)
                             for k in ("agg", "princ", "flow")},
            "stage_runs": {sum(f[f"{k}_runs"] for _, f in covered)
                           for k in ("agg", "princ", "flow")},
            "stage_states": dict(sum((f["states"] for _, f in covered), Counter())),
            "setup": setup,
        })

    # Two groups rather than per family: the claim is that first-submission
    # clearance falls with corpus size while post-repair clearance does not,
    # and a per-family split has too few runs to say that.
    repair = {}
    for name, groups in (("Small", ("academic",)), ("Large", ("named", "iso"))):
        runs = [s for r in rows if r["group"] in groups
                for u in by_family.get(r["prefix"], [])
                for s in e2e_by_unit.get(str(u.path), []) if s.sessions]
        repair[name] = None if not runs else {
            "first": round(100 * sum(s.first_pass for s in runs)
                           / sum(s.sessions for s in runs)),
            "final": round(100 * sum(s.cleared for s in runs)
                           / sum(s.sessions for s in runs)),
            "rounds": round(sum(s.repairs for s in runs) / len(runs), 1),
            "runs": len(runs),
        }

    # Cost splits the industrial side into three, unlike repair above. A
    # bundled ISO mechanism is a few pages of a shared document while a named
    # Specification is the whole corpus, and the ISO entries are far more
    # numerous, so one mean over both would report the ISO figure.
    cost = {}
    for name, groups in (("Small", ("academic",)), ("Large", ("named",)),
                         ("Iso", ("iso",))):
        # A run carries a cost only if it left an event log, which is not the
        # same as having a repair ledger, so each fold below takes the runs
        # that recorded the quantity it reports.
        cost_runs = [s for r in rows if r["group"] in groups
                     for u in by_family.get(r["prefix"], [])
                     for s in e2e_by_unit.get(str(u.path), [])]

        def mean_of(attr, scale=1.0, digits=1, _runs=cost_runs):
            vals = [getattr(s, attr) for s in _runs if getattr(s, attr) is not None]
            return round(sum(vals) / len(vals) * scale, digits) if vals else None

        # Timeouts are a total, not a mean: the question is how many cells the
        # budget swallowed across the batch.
        seen = [s for s in cost_runs if s.answered is not None]
        cost[name] = {
            "extract": mean_of("extract_sec", 1 / 60),
            "marginal": mean_of("marginal_sec", 1 / 60),
            "tokens": mean_of("tokens", 1 / 1e6, 2),
            "timeouts": sum(s.n_timeout for s in seen) if seen else None,
            "runs": sum(1 for s in cost_runs if s.extract_sec is not None),
        }

    def total(key):
        return sum(r[key] for r in rows)

    def total_match(key):
        """Summed over the families that scored the stage, against the corpus's
        own denominator, or None when no family scored it.

        A family with no run contributes nothing to the numerator, as ``whole``
        treats an unscored unit, so the result is a floor while coverage is
        incomplete; the \\scRun* totals beside it carry the scored subset's own
        denominator."""
        vals = [r[key] for r in rows if r[key] is not None]
        if not vals:
            return None
        s = sum(vals)
        return round(s, 1) if isinstance(s, float) else s

    def total_part(key):
        """Summed over the families that scored the stage at all, or None. The
        paired denominator comes from that same subset."""
        vals = [r[key] for r in rows if r[key] is not None]
        if not vals:
            return None
        s = sum(vals)
        return round(s, 1) if isinstance(s, float) else s

    # \lib* describes what the benchmark holds, counted from the corpus rather
    # than summed over the rows: a row is a presentation choice, since the ISO
    # parts collapse into two rows.
    lib_totals = {
        "units": len(units), "protocols": len(rows),
        "sources": len(
            {u.rel.split("/", 1)[0] for u in units}
            | {p.split("/", 1)[0] for p in doc_only}
        ),
        "versions": total("versions"),
        "tmodels": sum(u.n_tmodels for u in units),
        "props": sum(u.n_props for u in units),
        "verdicts": sum(u.n_verdicts for u in units),
        "fixed": sum(u.n_fixed for u in units),
        "variable": sum(u.n_variable for u in units),
        "varying_units": sum(1 for u in units if u.n_variable),
        "doc_only": len(doc_only),
        "neg_false": sum(u.n_false for u in units),
        "neg_unknown": sum(u.n_unknown for u in units),
        "all_match": total_match("props_match"),
        "all_verdicts_match": total_match("cells_matched"),
        "all_answered": total_match("answered"),
        "all_timeouts": total_match("n_timeout"),
        "all_princ": total_match("princ_match"),
        "all_princ_items": total_match("princ_total"),
        # Reach: the units and families a scored end-to-end run exists for,
        # counted directly rather than derived from the k/N totals, whose
        # denominators stay the corpus's own.
        "run_units": total("scored_units"),
        "run_families": sum(1 for r in rows if r["scored_units"]),
        "run_props": total("scored_props"),
        # The scored-subset totals the running text quotes while coverage is
        # incomplete: summed over the units that scored each stage, against
        # those units' denominators. They meet \scAll* once every unit has run.
        "run_verdicts": total("scored_verdicts"),
        "run_match": total_part("part_match"),
        "run_verdicts_match": total_part("part_verdicts_match"),
        "run_answered": total_part("part_answered"),
        "run_timeouts": total_part("part_timeouts"),
        "run_syn": total_part("part_syn"),
        "run_reach": total_part("part_reach"),
        "run_gate_runs": total_part("part_gate_runs"),
        "run_rep": (round(sum(v for r in rows for v in r["part_rep"])
                          / len([v for r in rows for v in r["part_rep"]]), 1)
                    if any(r["part_rep"] for r in rows) else None),
        "all_syn": total_match("syn"),
        "all_reach": total_match("reach"),
        "all_gate_runs": total_match("gate_runs"),
    }
    lib_totals["neg_total"] = lib_totals["neg_false"] + lib_totals["neg_unknown"]

    # The one-prompt ablation runs under its own work_root: same units, same
    # corpus denominators, a different pipeline. Reported by corpus scale, the
    # split its claim is about.
    ablation = {}
    for name, groups in (("Small", ("academic",)), ("Large", ("named", "iso"))):
        # Windowed like the main batch, and the match averaged over a unit's
        # runs rather than summed: summing would multiply both halves of k/N by
        # the repeat count.
        per_unit = []
        baseline_units = []
        for r in rows:
            if r["group"] not in groups:
                continue
            for u in by_family.get(r["prefix"], []):
                got = [s for s in runs_by_unit.get(str(u.path), [])
                       if s.batch == "baseline" and s.kind == "e2e"]
                if got:
                    per_unit.append(got[-last:] if last else got)
                    baseline_units.append(u)
        runs = [s for group_runs in per_unit for s in group_runs]
        gates = [s for s in runs if s.flow_state == "scored"]

        def unit_mean(pairs):
            """One number per unit, meaned over that unit's scored runs, then
            summed. A run scored against another property count (a corpus
            entry that has changed since) is left out, the rule ``fold`` and
            ``_scored`` below apply; ``pairs`` is (unit, its runs)."""
            vals = [[s.props_match for s in group
                     if s.agg_state == "scored" and s.props_total == u.n_props]
                    for u, group in pairs]
            vals = [v for v in vals if v]
            return round(sum(sum(v) / len(v) for v in vals), 1) if vals else None

        # Orrery's side is restricted to exactly the units the baseline ran. If
        # one of them has no current main-batch verdict score the comparison
        # reports None, rather than changing the subset in Orrery's favour.
        orr_groups = [e2e_by_unit.get(str(u.path), []) for u in baseline_units]
        orr_complete = bool(orr_groups) and all(
            any(s.agg_state == "scored" and s.props_total == u.n_props for s in group)
            for u, group in zip(baseline_units, orr_groups)
        )

        # Orrery's gates are counted over the same restricted unit set, so the
        # two sides of every row share a denominator that means the same thing.
        orr_gates = [s for group in orr_groups for s in group
                     if s.flow_state == "scored"]

        # Beside the strict all-units comparison, a symmetric one over the units
        # both batches scored: each side is re-folded over that subset, whose
        # size and denominator are emitted with it.
        def _scored(u, group):
            return [s.props_match for s in group
                    if s.agg_state == "scored" and s.props_total == u.n_props]
        paired = [(u, _scored(u, bg), _scored(u, og))
                  for u, bg, og in zip(baseline_units, per_unit, orr_groups)]
        paired = [(u, b, o) for u, b, o in paired if b and o]

        ablation[name] = None if not runs else {
            "syn": sum(1 for s in gates if s.syn),
            "reach": sum(1 for s in gates if s.reach),
            "gate_runs": len(gates),
            "orr_syn": sum(1 for s in orr_gates if s.syn) if orr_gates else None,
            "orr_reach": sum(1 for s in orr_gates if s.reach) if orr_gates else None,
            "orr_gate_runs": len(orr_gates) or None,
            "match": unit_mean(zip(baseline_units, per_unit)),
            "props": sum(u.n_props for u in baseline_units),
            "orr_match": (unit_mean(zip(baseline_units, orr_groups))
                          if orr_complete else None),
            "orr_props": sum(u.n_props for u in baseline_units),
            "pair_units": len(paired) or None,
            "pair_props": sum(u.n_props for u, _, _ in paired) or None,
            "pair_match": (round(sum(sum(b) / len(b) for _, b, _ in paired), 1)
                           if paired else None),
            "pair_orr_match": (round(sum(sum(o) / len(o) for _, _, o in paired), 1)
                               if paired else None),
            "runs": len(runs),
            "units": len(per_unit),
        }
    lib_totals["ablation"] = ablation
    lib_totals["repair"] = repair
    lib_totals["cost"] = cost
    # The per-query solver ceilings the reported cells ran under, read back from
    # the runs themselves. Only cross-checked runs count: a run contributing no
    # cell to any table says nothing about the numbers being quoted.
    seen = sorted({b for scores in e2e_by_unit.values() for s in scores
                   if s.answered is not None for b in s.budgets})
    lib_totals["pv_budgets"] = seen
    lib_totals["window"] = last
    lib_totals["run_roots"] = [str(r) for r in roots]
    lib_totals["root_notes"] = root_notes
    lib_totals["pv_budget"] = seen[0] if len(seen) == 1 else None
    lib_totals["stage_runs"] = stage_runs
    lib_totals["main_repeat_target"] = repeat_target
    lib_totals["main_repeats"] = main_repeats
    lib_totals["excluded"] = excluded
    return rows, lib_totals, doc_only, unmapped, skipped_runs, partial_runs, runs_by_unit


def _unit_mean(rows, key):
    """A pass rate over families, weighted by units, or None while any family
    is still unscored: a partial mean would read as a whole-corpus result."""
    scored = [(r["units"], r[key]) for r in rows if r["units"]]
    if any(v is None for _, v in scored) or not scored:
        return None
    return round(sum(n * v for n, v in scored) / sum(n for n, _ in scored))


def render_measured(rows, t, kb, agg, lib, runs_root, last=None) -> str:
    L = []
    add = L.append
    add("% " + "=" * 75)
    add("% measured.tex --- GENERATED by python -m experiments.reproduce. Do not hand-edit.")
    add("%")
    add(f"%   VerdictBench : {lib}")
    for i, root in enumerate(runs_root if isinstance(runs_root, (list, tuple)) else [runs_root]):
        add(f"%   {'runs        :' if i == 0 else '              '} {root}")
    add(f"%   repeated runs folded with --agg {agg}"
          + ("" if last is None else f", over each unit's {last} most recent"))
    add("%")
    add(r"% Any macro whose value is \ph{} has no completed run behind it yet.")
    add("% " + "=" * 75)
    add("")
    add("% --- library shape (counted from VerdictBench) ------------------------------")
    for name, val in (
        ("libSources", t["sources"]), ("libUnits", t["units"]),
        ("libProtocols", t["protocols"]),
        ("libVersions", t["versions"]), ("libTModels", t["tmodels"]),
        ("libProperties", t["props"]), ("libVerdicts", t["verdicts"]),
        ("libFixed", t["fixed"]), ("libVariable", t["variable"]),
        ("libVaryingUnits", t["varying_units"]), ("libDocOnly", t["doc_only"]),
    ):
        add(rf"\newcommand{{\{name}}}{{{latex_int(val)}}}")
    add("")

    if kb:
        add("% --- threat vocabulary (read from the realizer registry) -------------------")
        words = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
                 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
                 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
                 19: "nineteen", 20: "twenty", 21: "twenty-one", 22: "twenty-two"}
        add(rf"\newcommand{{\decCategories}}{{{words.get(kb['categories'], kb['categories'])}}}")
        add(rf"\newcommand{{\decDimensions}}{{{words.get(kb['dimensions'], kb['dimensions'])}}}")
        for name, key in (("decValues", "values"), ("decNeutralValues", "neutral"),
                          ("decImplemented", "implemented"), ("decRewriting", "rewriting"),
                          ("decDeclaredOnly", "declared_only"), ("decForms", "forms")):
            add(rf"\newcommand{{\{name}}}{{{kb[key]}}}")
        add("")
        add("% --- property vocabulary (read from the injector registry) -----------------")
        add(rf"\newcommand{{\decPropFamilies}}{{{words.get(kb['prop_families'], kb['prop_families'])}}}")
        for name, key in (("decPropLevels", "prop_levels"),
                          ("decPropRefused", "prop_refused")):
            add(rf"\newcommand{{\{name}}}{{{kb[key]}}}")
        add("")
        add("% --- modeling idioms (read from the idiom catalogs) ------------------------")
        for name, key in (("decIdiomEntries", "lib_entries"),
                          ("decPrimEntries", "prim_entries"),
                          ("decPrimRender", "prim_render"),
                          ("decPrimLookup", "prim_lookup"),
                          ("decIdentityEntries", "identity_entries"),
                          ("decMachineries", "machineries"),
                          ("decStructureEntries", "structure_entries"),
                          ("decTimeEntries", "time_entries")):
            add(rf"\newcommand{{\{name}}}{{{kb[key]}}}")
        add("")

    add("% --- per-family scores -----------------------------------------------------")
    add("% numerator from <run>/eval/summary.json; denominator from VerdictBench.")
    add("% Match is the property's own answer; Princ is initial-knowledge items;")
    add("% Syn and Reach are the runs clearing each flow-model gate, out of the")
    add("% GateRuns runs that attempted flow generation at all.")
    for r in rows:
        add(rf"\newcommand{{\sc{r['stem']}Match}}{{{latex_int(r['props_match'])}}}"
            rf"   \newcommand{{\sc{r['stem']}Props}}{{{r['props']}}}"
            f"   % {r['display']}")
        add(rf"\newcommand{{\sc{r['stem']}VerdictsMatch}}{{{latex_int(r['cells_matched'])}}}"
            rf"   \newcommand{{\sc{r['stem']}Verdicts}}{{{latex_int(r['verdicts'])}}}")
        for name, key in (("Answered", "answered"), ("Timeouts", "n_timeout")):
            add(rf"\newcommand{{\sc{r['stem']}{name}}}"
                rf"{{{latex_int(r[key])}}}")
        add(rf"\newcommand{{\sc{r['stem']}TModels}}{{{r['tmodels']}}}")
        add(rf"\newcommand{{\sc{r['stem']}Units}}{{{r['units']}}}"
            rf"   \newcommand{{\sc{r['stem']}Versions}}{{{r['versions']}}}"
            rf"   \newcommand{{\sc{r['stem']}World}}{{{r['world']}}}"
            rf"   \newcommand{{\sc{r['stem']}Fixed}}{{{r['fixed']}}}")
        add(rf"\newcommand{{\sc{r['stem']}Variable}}{{{r['variable']}}}"
            rf"   \newcommand{{\sc{r['stem']}Decls}}{{{r['decls']}}}")
        for name, key in (("Princ", "princ_match"), ("PrincItems", "princ_total"),
                          ("Syn", "syn"), ("Reach", "reach"),
                          ("GateRuns", "gate_runs"), ("Rep", "rep_rounds"),
                          ("AllPass", "allpass"), ("AggRuns", "agg_runs")):
            v = r[key]
            add(rf"\newcommand{{\sc{r['stem']}{name}}}"
                rf"{{{PLACEHOLDER if v is None else v}}}")
    add("")

    add("% --- aggregates ------------------------------------------------------------")
    def groups_sum(groups, key):
        vals = [r[key] for r in rows if r["group"] in groups]
        return None if any(v is None for v in vals) else sum(vals)

    def props_of(groups):
        return sum(r["props"] for r in rows if r["group"] in groups)

    # The corpus keeps the ISO bundles part by part while the table shows one
    # row each, so the parts are aggregated here: 9798 is entity authentication
    # (stems IsoA*) and 11770 is key management (IsoK*).
    for name, prefix in (("scIsoAuth", "IsoA"), ("scIsoKey", "IsoK")):
        part = [r for r in rows if r["stem"].startswith(prefix)]
        m = None if any(r["props_match"] is None for r in part) else sum(
            r["props_match"] for r in part)
        pk = None if any(r["princ_match"] is None for r in part) else sum(
            r["princ_match"] for r in part)
        pi = None if any(r["princ_total"] is None for r in part) else sum(
            r["princ_total"] for r in part)
        add(rf"\newcommand{{\{name}Match}}{{{latex_int(m)}}}"
            rf"   \newcommand{{\{name}Props}}{{{sum(r['props'] for r in part)}}}")
        add(rf"\newcommand{{\{name}Princ}}{{{latex_int(pk)}}}"
            rf"   \newcommand{{\{name}PrincItems}}{{{latex_int(pi)}}}")
        for col, key in (("Answered", "answered"), ("Timeouts", "n_timeout")):
            v = None if any(r[key] is None for r in part) else sum(r[key] for r in part)
            add(rf"\newcommand{{\{name}{col}}}{{{latex_int(v)}}}")
        vm = None if any(r["cells_matched"] is None for r in part) else sum(
            r["cells_matched"] for r in part)
        add(rf"\newcommand{{\{name}VerdictsMatch}}{{{PLACEHOLDER if vm is None else latex_int(vm)}}}"
            rf"   \newcommand{{\{name}Verdicts}}{{{latex_int(sum(r['verdicts'] for r in part))}}}")
        # The bundle's scored-subset verdicts, like the \scRun* totals: summed
        # over the units with completed runs, against those units' own
        # denominator, so the text keeps a number under partial coverage.
        rvm = [r["part_verdicts_match"] for r in part
               if r["part_verdicts_match"] is not None]
        rvd = sum(r["scored_verdicts"] for r in part)
        rv = round(sum(rvm), 1) if rvm else None
        add(rf"\newcommand{{\{name}RunVerdictsMatch}}{{{latex_int(rv)}}}"
            rf"   \newcommand{{\{name}RunVerdicts}}{{{latex_int(rvd) if rvd else PLACEHOLDER}}}")
        for col, key in (("Syn", "syn"), ("Reach", "reach"), ("GateRuns", "gate_runs")):
            v = None if any(r[key] is None for r in part) else sum(r[key] for r in part)
            add(rf"\newcommand{{\{name}{col}}}{{{PLACEHOLDER if v is None else v}}}")
        rr = [r["rep_rounds"] for r in part]
        rv = None if any(v is None for v in rr) else round(sum(rr) / len(rr), 1)
        add(rf"\newcommand{{\{name}Rep}}{{{PLACEHOLDER if rv is None else rv}}}")
        add(rf"\newcommand{{\{name}TModels}}{{{sum(r['tmodels'] for r in part)}}}")
    add(rf"\newcommand{{\scIsoUnits}}{{{sum(r['units'] for r in rows if r['group'] == 'iso')}}}")
    add(rf"\newcommand{{\scIsoParts}}{{{sum(1 for r in rows if r['group'] == 'iso')}}}")
    add(rf"\newcommand{{\scIsoTModels}}{{{sum(r['tmodels'] for r in rows if r['group'] == 'iso')}}}")
    # \scNamed is everything outside the ISO bundles (academic + the named
    # industrial families); \scIndustrial is the named families alone.
    def units_of(groups):
        return [r for r in rows if r["group"] in groups]

    for name, groups in (("scIso", ("iso",)),
                         ("scNamed", ("academic", "named")),
                         ("scAcademic", ("academic",)),
                         ("scIndustrial", ("named",))):
        m = groups_sum(groups, "props_match")
        add(rf"\newcommand{{\{name}Match}}{{{latex_int(m)}}}"
            rf"   \newcommand{{\{name}Props}}{{{props_of(groups)}}}")
        # The same columns the per-family block emits, for the rows the table
        # aggregates: the academic tier is one row, and so is each total.
        pk, pi = groups_sum(groups, "princ_match"), groups_sum(groups, "princ_total")
        add(rf"\newcommand{{\{name}Princ}}{{{latex_int(pk)}}}"
            rf"   \newcommand{{\{name}PrincItems}}{{{latex_int(pi)}}}")
        for col, key in (("Answered", "answered"), ("Timeouts", "n_timeout")):
            v = groups_sum(groups, key)
            add(rf"\newcommand{{\{name}{col}}}{{{latex_int(v)}}}")
        vm = groups_sum(groups, "cells_matched")
        add(rf"\newcommand{{\{name}VerdictsMatch}}{{{PLACEHOLDER if vm is None else latex_int(vm)}}}"
            rf"   \newcommand{{\{name}Verdicts}}{{{latex_int(sum(r['verdicts'] for r in units_of(groups)))}}}")
        for col, key in (("Syn", "syn"), ("Reach", "reach"), ("GateRuns", "gate_runs")):
            v = groups_sum(groups, key)
            add(rf"\newcommand{{\{name}{col}}}{{{PLACEHOLDER if v is None else v}}}")
        rr = [r["rep_rounds"] for r in units_of(groups)]
        rv = None if any(v is None for v in rr) else round(sum(rr) / len(rr), 1)
        add(rf"\newcommand{{\{name}Rep}}{{{PLACEHOLDER if rv is None else rv}}}")
    add("% \\scRun*: totals over the units with a completed run at each stage,")
    add("% against those units' own denominators. They equal \\scAll* once every")
    add("% unit has a run; until then \\scAll* stays \\ph{} and these carry the text.")
    add(rf"\newcommand{{\scRunFamilies}}{{{latex_int(t['run_families'])}}}"
        rf"   \newcommand{{\scRunUnits}}{{{latex_int(t['run_units'])}}}"
        rf"   \newcommand{{\scRunProps}}{{{latex_int(t['run_props'])}}}")
    add(rf"\newcommand{{\scRunMatch}}{{{latex_int(t['run_match'])}}}"
        rf"   \newcommand{{\scRunVerdictsMatch}}{{{latex_int(t['run_verdicts_match'])}}}"
        rf"   \newcommand{{\scRunVerdicts}}{{{latex_int(t['run_verdicts'])}}}")
    add(rf"\newcommand{{\scRunAnswered}}{{{latex_int(t['run_answered'])}}}"
        rf"   \newcommand{{\scRunTimeouts}}{{{latex_int(t['run_timeouts'])}}}")
    add(rf"\newcommand{{\scRunSyn}}{{{latex_int(t['run_syn'])}}}"
        rf"   \newcommand{{\scRunReach}}{{{latex_int(t['run_reach'])}}}"
        rf"   \newcommand{{\scRunGateRuns}}{{{latex_int(t['run_gate_runs'])}}}")
    add(rf"\newcommand{{\scRunRep}}{{{latex_int(t['run_rep'])}}}")
    add(rf"\newcommand{{\scAllMatch}}{{{latex_int(t['all_match'])}}}"
        rf"   \newcommand{{\scAllProps}}{{{latex_int(t['props'])}}}")
    add(rf"\newcommand{{\scAllPrinc}}{{{latex_int(t['all_princ'])}}}"
        rf"   \newcommand{{\scAllPrincItems}}{{{latex_int(t['all_princ_items'])}}}")
    add(rf"\newcommand{{\scAllSyn}}{{{latex_int(t['all_syn'])}}}"
        rf"   \newcommand{{\scAllReach}}{{{latex_int(t['all_reach'])}}}"
        rf"   \newcommand{{\scAllGateRuns}}{{{latex_int(t['all_gate_runs'])}}}")
    add(rf"\newcommand{{\scAllVerdictsMatch}}{{{latex_int(t['all_verdicts_match'])}}}"
        rf"   \newcommand{{\scAllAnswered}}{{{latex_int(t['all_answered'])}}}"
        rf"   \newcommand{{\scAllTimeouts}}{{{latex_int(t['all_timeouts'])}}}")
    _rr = [r["rep_rounds"] for r in rows]
    _rv = None if any(v is None for v in _rr) else round(sum(_rr) / len(_rr), 1)
    add(rf"\newcommand{{\scAllRep}}{{{PLACEHOLDER if _rv is None else _rv}}}")
    add("")
    add("% --- the repair loop (from <run>/repair.json) -------------------------------")
    add("% A submission is a check_report; repairs are submissions beyond the first.")
    for name in ("Small", "Large"):
        r = t["repair"].get(name)
        for macro, key in (("First", "first"), ("Final", "final"), ("Rounds", "rounds")):
            v = PLACEHOLDER if r is None else r[key]
            add(rf"\newcommand{{\rp{name}{macro}}}{{{v}}}")
    add("")
    add("% --- setup extraction (tab:extraction) --------------------------------------")
    add("% A separate experiment: the framework reads the declarations, the properties,")
    add("% and the claims off the document instead of being handed them. Scored against")
    add("% the curated setup. Each stage takes the newest run that scored it, since a")
    add("% superseded configuration is not a repeat of the current one.")
    for r in rows:
        for macro, key in (("Assum", "assum"), ("Props", "props"), ("Claims", "claims")):
            pair = r["setup"].get(key)
            k = PLACEHOLDER if pair is None else pair[0]
            n = PLACEHOLDER if pair is None else pair[1]
            e = PLACEHOLDER if pair is None else pair[2]
            add(rf"\newcommand{{\se{r['stem']}{macro}}}{{{k}}}"
                rf"   \newcommand{{\se{r['stem']}{macro}N}}{{{n}}}"
                rf"   \newcommand{{\se{r['stem']}{macro}X}}{{{e}}}")
    # Industrial is named plus iso, the same split the ablation uses for its
    # large corpus, so the word means one thing across RQ3 and RQ4.
    for groups, label in ((("academic",), "Academic"), (("named", "iso"), "Industrial")):
        part = [r for r in rows if r["group"] in groups]
        for macro, key in (("Assum", "assum"), ("Props", "props"), ("Claims", "claims")):
            got = [r["setup"][key] for r in part if key in r["setup"]]
            k, n, e = (sum(x[i] for x in got) if got else None for i in range(3))
            add(rf"\newcommand{{\se{label}{macro}}}{{{PLACEHOLDER if k is None else k}}}"
                rf"   \newcommand{{\se{label}{macro}N}}{{{PLACEHOLDER if n is None else n}}}"
                rf"   \newcommand{{\se{label}{macro}X}}{{{PLACEHOLDER if e is None else e}}}")
        add(rf"\newcommand{{\se{label}Units}}"
            rf"{{{sum(1 for r in part if r['setup'])}}}")
    # Per-source subtotals for the body table, which shows that the fall along
    # the three stages holds inside every family rather than being driven by
    # one of them. The per-protocol detail lives in the appendix.
    for source, label in (("IETF", "Ietf"), ("3GPP", "Tgpp"),
                          ("industry", "Industry"), ("ISO", "Iso")):
        part = [r for r in rows if r["source"] == source]
        for macro, key in (("Assum", "assum"), ("Props", "props"), ("Claims", "claims")):
            got = [r["setup"][key] for r in part if key in r["setup"]]
            k, n, e = (sum(x[i] for x in got) if got else None for i in range(3))
            add(rf"\newcommand{{\seSrc{label}{macro}}}{{{PLACEHOLDER if k is None else k}}}"
                rf"   \newcommand{{\seSrc{label}{macro}N}}{{{PLACEHOLDER if n is None else n}}}"
                rf"   \newcommand{{\seSrc{label}{macro}X}}{{{PLACEHOLDER if e is None else e}}}")
        add(rf"\newcommand{{\seSrc{label}Units}}"
            rf"{{{sum(1 for r in part if r['setup'])}}}")
    add("")
    add("% --- the AutoSM overlap (tab:llmaided) --------------------------------------")
    add("% AutoSM scores a protocol all-or-nothing, so the head-to-head folds our runs")
    add("% the same way. AllPass counts runs where every property matched; Families is")
    add("% the overlap families that cleared it at least once, over those with a run.")
    part = [r for r in rows if r["stem"] in AUTOSM_OVERLAP]
    scored_part = [r for r in part if r["allpass"] is not None]
    for macro, val in (
        ("scOverlapAllPass", sum(r["allpass"] for r in scored_part) or None),
        ("scOverlapAggRuns", sum(r["agg_runs"] for r in scored_part) or None),
        ("scOverlapFamilies", sum(1 for r in scored_part if r["allpass"]) or None),
        ("scOverlapScored", len(scored_part) or None),
        ("scOverlapTotal", len(part)),
    ):
        add(rf"\newcommand{{\{macro}}}{{{PLACEHOLDER if val is None else val}}}")
    add("")
    add("% --- the one-prompt ablation (RQ3) ------------------------------------------")
    add("% Read from the baseline work_root. A scale with no mapped run is emitted as")
    add("% \\ph{} rather than left undefined, so the table keeps its shape and missing")
    add("% coverage remains visible. Counts and their one-decimal rates are both")
    add("% generated here. Absent until the corresponding run root is present.")
    ab = t.get("ablation") or {}
    def rate(num, den):
        return (PLACEHOLDER if num is None or den in (None, 0)
                else f"{100 * num / den:.1f}")

    for scale in ("Small", "Large"):
        a = ab.get(scale) or {}
        for macro, key in (("Syn", "syn"), ("Reach", "reach"),
                           ("GateRuns", "gate_runs"), ("Match", "match"),
                           ("Props", "props"), ("MatchOrr", "orr_match"),
                           ("PropsOrr", "orr_props"), ("SynOrr", "orr_syn"),
                           ("ReachOrr", "orr_reach"),
                           ("GateRunsOrr", "orr_gate_runs"),
                           ("PairUnits", "pair_units"),
                           ("PairProps", "pair_props"),
                           ("MatchPair", "pair_match"),
                           ("MatchOrrPair", "pair_orr_match")):
            v = a.get(key)
            add(rf"\newcommand{{\ab{scale}{macro}}}{{{PLACEHOLDER if v is None else v}}}")
        add(rf"\newcommand{{\ab{scale}SynRate}}{{{rate(a.get('syn'), a.get('gate_runs'))}}}"
            rf"   \newcommand{{\ab{scale}ReachRate}}{{{rate(a.get('reach'), a.get('gate_runs'))}}}")
        add(rf"\newcommand{{\ab{scale}SynOrrRate}}{{{rate(a.get('orr_syn'), a.get('orr_gate_runs'))}}}"
            rf"   \newcommand{{\ab{scale}ReachOrrRate}}{{{rate(a.get('orr_reach'), a.get('orr_gate_runs'))}}}")
        add(rf"\newcommand{{\ab{scale}MatchRate}}{{{rate(a.get('match'), a.get('props'))}}}"
            rf"   \newcommand{{\ab{scale}MatchOrrRate}}{{{rate(a.get('orr_match'), a.get('orr_props'))}}}")
        add(rf"\newcommand{{\ab{scale}MatchPairRate}}{{{rate(a.get('pair_match'), a.get('pair_props'))}}}"
            rf"   \newcommand{{\ab{scale}MatchOrrPairRate}}{{{rate(a.get('pair_orr_match'), a.get('pair_props'))}}}")
    units = sum((ab.get(s) or {}).get("units", 0) for s in ("Small", "Large"))
    add(rf"\newcommand{{\nAblationUnits}}{{{units or PLACEHOLDER}}}")
    add(rf"\newcommand{{\abSilent}}{{{PLACEHOLDER}}}"
        r"   % needs a per-verdict pass over the baseline runs")
    add("")
    add("% --- cost (from <run>/events.jsonl: node timestamps and session_usage) ----")
    add("% Extract is run start to the frozen root model; Marginal is one threat")
    add("% model on that root, realizer pass plus verifier run; Tokens is input")
    add("% plus output, cached being a subset of input rather than a third term.")
    add("% Large is the named Specifications and Iso the bundled ISO mechanisms,")
    add("% split because one mean over both reports the ISO figure (see build()).")
    # The solver ceiling and the cells it cut off get no macro: the paper shows
    # a cut-off cell as the gap between Answered and Matched. The report still
    # checks the ceiling was uniform across the runs the tables draw on, since
    # a mixed one makes those two columns incomparable.
    for name in ("Small", "Large", "Iso"):
        c = t["cost"].get(name) or {}
        for macro, key in (("Extract", "extract"), ("Marginal", "marginal"),
                           ("Tokens", "tokens")):
            v = c.get(key)
            add(rf"\newcommand{{\ct{name}{macro}}}{{{PLACEHOLDER if v is None else v}}}")
    add("")
    if t["all_match"] is not None and t["props"]:
        add(rf"\newcommand{{\scAllRate}}{{{round(100 * t['all_match'] / t['props'])}\%}}")
    else:
        add(rf"\newcommand{{\scAllRate}}{{{PLACEHOLDER}}}")
    # \scAllRate is property level; \scAllVerdictRate is the property and
    # threat-model level the abstract and introduction quote.
    if t["all_verdicts_match"] is not None and t["verdicts"]:
        add(rf"\newcommand{{\scAllVerdictRate}}"
            rf"{{{round(100 * t['all_verdicts_match'] / t['verdicts'])}\%}}")
    else:
        add(rf"\newcommand{{\scAllVerdictRate}}{{{PLACEHOLDER}}}")
    # The same two rates over the scored subset, quoted while \scAll* is still
    # \ph{}; they converge on the \scAll* rates at full coverage.
    if t["run_match"] is not None and t["run_props"]:
        add(rf"\newcommand{{\scRunMatchRate}}{{{round(100 * t['run_match'] / t['run_props'])}\%}}")
    else:
        add(rf"\newcommand{{\scRunMatchRate}}{{{PLACEHOLDER}}}")
    if t["run_verdicts_match"] is not None and t["run_verdicts"]:
        add(rf"\newcommand{{\scRunVerdictRate}}"
            rf"{{{round(100 * t['run_verdicts_match'] / t['run_verdicts'])}\%}}")
    else:
        add(rf"\newcommand{{\scRunVerdictRate}}{{{PLACEHOLDER}}}")
    add("")

    add("% --- negative side (denominators counted from the expert models) -----------")
    add(rf"\newcommand{{\scNegTotal}}{{{t['neg_total']}}}")
    add(rf"\newcommand{{\scNegFalse}}{{{t['neg_false']}}}")
    add(rf"\newcommand{{\scNegUnknown}}{{{t['neg_unknown']}}}")
    add(rf"\newcommand{{\scNegRepro}}{{{PLACEHOLDER}}}   % needs a per-verdict pass over the runs")
    add("")
    return "\n".join(L) + "\n"


def check_totals(rows, t) -> None:
    """Check that the table body and the \\lib* totals count the same corpus.

    Every quoted total must sum its own rows, so dropping a family from
    FAMILIES is the whole edit. Raises SystemExit when a total disagrees with
    the rows below it, rather than letting the mismatch reach the paper.
    """
    for key, macro in (("units", "libUnits"), ("tmodels", "libTModels"),
                       ("props", "libProperties"), ("verdicts", "libVerdicts")):
        rowsum = sum(r[key] for r in rows)
        if rowsum != t[key]:
            raise SystemExit(
                f"data-scope mismatch: \\{macro} is {t[key]} but the table rows "
                f"sum to {rowsum}. The \\lib* totals and the tables must count "
                f"the same corpus; check FAMILIES and EXCLUDED.")
    if len(rows) != t["protocols"]:
        raise SystemExit(f"data-scope mismatch: \\libProtocols is {t['protocols']} "
                         f"but there are {len(rows)} table rows.")


def render_rows(rows) -> str:
    """Body rows of the appendix benchmark table, for \\input inside a tabular.

    The table is single-column, so the source is a group heading rather than a
    column and the document-version count lives in the caption.
    """
    out = ["% GENERATED by python -m experiments.reproduce --- body rows of Table~\\ref{tab:dataset}.",
           "% Do not hand-edit; \\input this inside the tabular.", ""]
    last = None
    for r in rows:
        if r["source"] != last:
            if last is not None:
                out.append(r"\midrule")
            # A plain row, not \multicolumn: an \input'ed file starts inside
            # the first cell of a row, where \multicolumn is "Misplaced \omit".
            out.append(r"\emph{%s} & & & & & \\" % r["source"])
            last = r["source"]
        match = (rf"\sc{r['stem']}Match{{}}/\sc{r['stem']}Props{{}}")
        out.append(
            f"{r['display']:<26} & {r['units']} & "
            f"{r['tmodels']} & {r['props']} & {r['verdicts']} & {match} \\\\")
    out.append(r"\midrule")
    # The Match total sums the units with completed runs against those units'
    # own denominator (\scRun*), so an incomplete batch shows a smaller
    # denominator rather than a placeholder total.
    out.append(r"\textbf{All \libProtocols{} families} & \textbf{\libUnits{}} & "
               r"\textbf{\libTModels{}} & \textbf{\libProperties{}} & \textbf{\libVerdicts{}} & "
               r"\textbf{\scRunMatch{}/\scRunProps{}} \\")
    # The file ends with a comment character: \input inside a tabular emits
    # tokens at end of file, and after a bare \\ they land between rows and
    # break the next \noalign.
    out.append(r"\bottomrule%")
    return "\n".join(out)


def _shown(value) -> str:
    """Plain-text rendering used by reviewer-facing tables."""
    return "--" if value is None else str(value)


def _ratio(num, den) -> str:
    return f"{_shown(num)}/{_shown(den)}"


def _setup_cell(row, key, extra=False) -> str:
    value = row["setup"].get(key)
    if value is None:
        return "--"
    return str(value[2]) if extra else f"{value[0]}/{value[1]}"


def _markdown_table(headers, body) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(str(cell) for cell in row) + " |" for row in body),
    ]


def render_markdown(rows, totals, agg: str, last: int | None) -> str:
    """Reviewer-facing rendering of every quantitative paper experiment."""
    out = [
        "# Reproduced paper results",
        "",
        (f"Generated only from `VerdictBench/` and `runs/`. Repeated runs use "
         f"`{agg}` aggregation over "
         f"{'all available runs' if last is None else f'the latest {last} runs per unit'}."),
        "",
        "## Main experiment",
        "",
        "`Props` is agreement at property level; `Matched` is agreement at the "
        "property × threat-model level. `Syn` and `Reach` are pass counts over "
        "runs that attempted flow generation.",
        "",
    ]
    out += _markdown_table(
        ["Family", "Units", "Runs", "TMs", "Princ", "Repair", "Syn", "Reach",
         "Props", "Answered", "Matched"],
        [[r["display"], r["units"], r["runs"], r["tmodels"],
          _ratio(r["princ_match"], r["princ_total"]), _shown(r["rep_rounds"]),
          _ratio(r["syn"], r["gate_runs"]), _ratio(r["reach"], r["gate_runs"]),
          _ratio(r["props_match"], r["props"]),
          _ratio(r["answered"], r["verdicts"]),
          _ratio(r["cells_matched"], r["verdicts"])] for r in rows]
        + [["TOTAL", totals["units"], sum(r["runs"] for r in rows), totals["tmodels"],
            _ratio(totals["all_princ"], totals["all_princ_items"]),
            _shown(totals["run_rep"]),
            _ratio(totals["all_syn"], totals["all_gate_runs"]),
            _ratio(totals["all_reach"], totals["all_gate_runs"]),
            _ratio(totals["all_match"], totals["props"]),
            _ratio(totals["all_answered"], totals["verdicts"]),
            _ratio(totals["all_verdicts_match"], totals["verdicts"])]],
    )

    out += ["", "## Setup extraction", ""]
    out += _markdown_table(
        ["Family", "Assum", "Props", "Claims", "Extra assum", "Extra props",
         "Extra claims"],
        [[r["display"], _setup_cell(r, "assum"), _setup_cell(r, "props"),
          _setup_cell(r, "claims"), _setup_cell(r, "assum", True),
          _setup_cell(r, "props", True), _setup_cell(r, "claims", True)]
         for r in rows if r["setup"]],
    )

    out += ["", "## One-prompt baseline", ""]
    ablation = totals.get("ablation") or {}
    out += _markdown_table(
        ["Scale", "Units", "Runs", "Syn", "Reach", "Baseline props",
         "Orrery props", "Paired units", "Paired baseline", "Paired Orrery"],
        [[scale, _shown(a.get("units")), _shown(a.get("runs")),
          _ratio(a.get("syn"), a.get("gate_runs")),
          _ratio(a.get("reach"), a.get("gate_runs")),
          _ratio(a.get("match"), a.get("props")),
          _ratio(a.get("orr_match"), a.get("orr_props")),
          _shown(a.get("pair_units")),
          _ratio(a.get("pair_match"), a.get("pair_props")),
          _ratio(a.get("pair_orr_match"), a.get("pair_props"))]
         for scale in ("Small", "Large") for a in [ablation.get(scale) or {}]],
    )

    out += ["", "## Repair and cost", ""]
    repair, cost = totals.get("repair") or {}, totals.get("cost") or {}
    out += _markdown_table(
        ["Scale", "First clearance (%)", "Final clearance (%)", "Repair rounds"],
        [[scale, _shown((repair.get(scale) or {}).get("first")),
          _shown((repair.get(scale) or {}).get("final")),
          _shown((repair.get(scale) or {}).get("rounds"))]
         for scale in ("Small", "Large")],
    )
    out += [""]
    out += _markdown_table(
        ["Scale", "Extraction (min)", "Per threat model (min)", "Tokens (M)"],
        [[scale, _shown((cost.get(scale) or {}).get("extract")),
          _shown((cost.get(scale) or {}).get("marginal")),
          _shown((cost.get(scale) or {}).get("tokens"))]
         for scale in ("Small", "Large", "Iso")],
    )

    out += ["", "## Corpus", ""]
    out += _markdown_table(
        ["Family", "Units", "TMs", "Properties", "Verdicts"],
        [[r["display"], r["units"], r["tmodels"], r["props"], r["verdicts"]]
         for r in rows]
        + [["TOTAL", totals["units"], totals["tmodels"], totals["props"],
            totals["verdicts"]]],
    )
    return "\n".join(out) + "\n"


def _tex_text(value: str) -> str:
    """Escape labels while preserving the paper's ``--`` TeX punctuation."""
    return (value.replace("&", r"\&").replace("%", r"\%")
            .replace("_", r"\_").replace("#", r"\#"))


def render_tables_tex(rows, totals) -> str:
    """LaTeX table fragments corresponding to the Markdown report."""
    ph = PLACEHOLDER

    def tex_ratio(num, den):
        return f"{ph if num is None else num}/{ph if den is None else den}"

    out = [
        "% GENERATED by python -m experiments.reproduce. Do not hand-edit.",
        "% Requires booktabs.", "",
        r"\providecommand{\ph}{\textemdash}", "",
        r"\begin{table*}[t]", r"\centering", r"\footnotesize",
        r"\begin{tabular}{lrrrrrrrrrr}", r"\toprule",
        "Family & Units & Runs & TMs & Princ & Rep. & Syn & Reach & Props & Answered & Matched \\\\",
        r"\midrule",
    ]
    for r in rows:
        out.append(
            f"{_tex_text(r['display'])} & {r['units']} & {r['runs']} & {r['tmodels']} & "
            f"{tex_ratio(r['princ_match'], r['princ_total'])} & "
            f"{ph if r['rep_rounds'] is None else r['rep_rounds']} & "
            f"{tex_ratio(r['syn'], r['gate_runs'])} & "
            f"{tex_ratio(r['reach'], r['gate_runs'])} & "
            f"{tex_ratio(r['props_match'], r['props'])} & "
            f"{tex_ratio(r['answered'], r['verdicts'])} & "
            f"{tex_ratio(r['cells_matched'], r['verdicts'])} \\\\")
    out.append(
        r"\midrule "
        f"TOTAL & {totals['units']} & {sum(r['runs'] for r in rows)} & "
        f"{totals['tmodels']} & {tex_ratio(totals['all_princ'], totals['all_princ_items'])} & "
        f"{ph if totals['run_rep'] is None else totals['run_rep']} & "
        f"{tex_ratio(totals['all_syn'], totals['all_gate_runs'])} & "
        f"{tex_ratio(totals['all_reach'], totals['all_gate_runs'])} & "
        f"{tex_ratio(totals['all_match'], totals['props'])} & "
        f"{tex_ratio(totals['all_answered'], totals['verdicts'])} & "
        f"{tex_ratio(totals['all_verdicts_match'], totals['verdicts'])} \\\\")
    out += [r"\bottomrule", r"\end{tabular}",
            r"\caption{Reproduction of the main experiment from published runs.}",
            r"\label{tab:reproduced-main}", r"\end{table*}", "",
            r"\begin{table*}[t]", r"\centering", r"\footnotesize",
            r"\begin{tabular}{lrrrrrr}", r"\toprule",
            "Family & Assum & Props & Claims & Extra assum & Extra props & Extra claims \\\\",
            r"\midrule"]
    for r in rows:
        if not r["setup"]:
            continue
        out.append(
            f"{_tex_text(r['display'])} & {_setup_cell(r, 'assum')} & "
            f"{_setup_cell(r, 'props')} & {_setup_cell(r, 'claims')} & "
            f"{_setup_cell(r, 'assum', True)} & {_setup_cell(r, 'props', True)} & "
            f"{_setup_cell(r, 'claims', True)} \\\\")
    out += [r"\bottomrule", r"\end{tabular}",
            r"\caption{Reproduction of setup extraction from published runs.}",
            r"\label{tab:reproduced-setup}", r"\end{table*}", ""]

    ablation = totals.get("ablation") or {}
    out += [r"\begin{table}[t]", r"\centering", r"\footnotesize",
            r"\begin{tabular}{lrrrrr}", r"\toprule",
            "Scale & Syn & Reach & Baseline props & Orrery props & Paired props \\\\",
            r"\midrule"]
    for scale in ("Small", "Large"):
        a = ablation.get(scale) or {}
        out.append(
            f"{scale} & {tex_ratio(a.get('syn'), a.get('gate_runs'))} & "
            f"{tex_ratio(a.get('reach'), a.get('gate_runs'))} & "
            f"{tex_ratio(a.get('match'), a.get('props'))} & "
            f"{tex_ratio(a.get('orr_match'), a.get('orr_props'))} & "
            f"{tex_ratio(a.get('pair_match'), a.get('pair_props'))} \\\\ ")
    out += [r"\bottomrule", r"\end{tabular}",
            r"\caption{Reproduction of the one-prompt baseline experiment.}",
            r"\label{tab:reproduced-baseline}", r"\end{table}", ""]

    repair, cost = totals.get("repair") or {}, totals.get("cost") or {}
    out += [r"\begin{table}[t]", r"\centering", r"\footnotesize",
            r"\begin{tabular}{lrrr}", r"\toprule",
            "Metric & Academic & Specification & ISO mechanism \\\\", r"\midrule"]
    small_r, large_r = repair.get("Small") or {}, repair.get("Large") or {}
    out += [
        f"First clearance (\\%) & {_shown(small_r.get('first'))} & "
        f"{_shown(large_r.get('first'))} & {_shown(large_r.get('first'))} \\\\ ",
        f"Final clearance (\\%) & {_shown(small_r.get('final'))} & "
        f"{_shown(large_r.get('final'))} & {_shown(large_r.get('final'))} \\\\ ",
        f"Repair rounds & {_shown(small_r.get('rounds'))} & "
        f"{_shown(large_r.get('rounds'))} & {_shown(large_r.get('rounds'))} \\\\ ",
        r"\midrule",
    ]
    for label, key in (("Extraction (min)", "extract"),
                       ("Per threat model (min)", "marginal"),
                       ("Backbone tokens (M)", "tokens")):
        out.append(f"{label} & {_shown((cost.get('Small') or {}).get(key))} & "
                   f"{_shown((cost.get('Large') or {}).get(key))} & "
                   f"{_shown((cost.get('Iso') or {}).get(key))} \\\\ ")
    out += [r"\bottomrule", r"\end{tabular}",
            r"\caption{Reproduction of repair and cost measurements.}",
            r"\label{tab:reproduced-cost}", r"\end{table}", ""]
    return "\n".join(out)


CSV_FIELDS = (
    "source", "group", "family", "units", "runs", "threat_models",
    "principals_match", "principals_total", "repair_rounds", "syntax_pass",
    "reachability_pass", "gate_runs", "properties_match", "properties_total",
    "answered", "verdicts_match", "verdicts_total",
)


def write_csv(path: Path, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "source": r["source"], "group": r["group"],
                "family": r["display"], "units": r["units"], "runs": r["runs"],
                "threat_models": r["tmodels"],
                "principals_match": r["princ_match"],
                "principals_total": r["princ_total"],
                "repair_rounds": r["rep_rounds"], "syntax_pass": r["syn"],
                "reachability_pass": r["reach"], "gate_runs": r["gate_runs"],
                "properties_match": r["props_match"],
                "properties_total": r["props"], "answered": r["answered"],
                "verdicts_match": r["cells_matched"],
                "verdicts_total": r["verdicts"],
            })


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, RunScore):
        return str(value.run_dir)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, set):
        return [_jsonable(v) for v in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def report(rows, t, doc_only, unmapped, skipped_runs, partial_runs, kb, kb_err, agg):
    print(f"\n{'family':<26} {'units':>5} {'runs':>5} {'props':>6} {'verd.':>6}  "
          f"{'match':>9} {'princ':>9} {'syn':>7} {'reach':>7}")
    print("-" * 92)
    for r in rows:
        print(f"{r['display']:<26} {r['units']:>5} {r['runs']:>5} {r['props']:>6} "
              f"{r['verdicts']:>6}  {frac(r['props_match'], r['props']):>9} "
              f"{frac(r['princ_match'], r['princ_total']):>9} "
              f"{frac(r['syn'], r['gate_runs']) if r['gate_runs'] else '--':>7} "
              f"{frac(r['reach'], r['gate_runs']) if r['gate_runs'] else '--':>7}"
              + ("" if r["covered_units"] in (0, r["units"])
                 else f"   [partial: {r['covered_units']}/{r['units']} units scored]"))
    print("-" * 92)
    print(f"{'TOTAL':<26} {t['units']:>5} {sum(r['runs'] for r in rows):>5} "
          f"{t['props']:>6} {t['verdicts']:>6}  {frac(t['all_match'], t['props']):>9} "
          f"{frac(t['all_princ'], t['all_princ_items']):>9} "
          f"{frac(t['all_syn'], t['all_gate_runs']) if t['all_gate_runs'] else '--':>7} "
          f"{frac(t['all_reach'], t['all_gate_runs']) if t['all_gate_runs'] else '--':>7}")

    # A stage folds over the runs that scored it, so the report names which
    # runs those were and which were left out.
    partials = [r for r in rows if r["runs"] and r["stage_runs"] != {r["runs"]}]
    if partials:
        print("\nruns per stage (a stage folds only over the runs that scored it):")
        for r in partials:
            s = r["stage_states"]
            print(f"  {r['display']:<24} {r['runs']} runs -> "
                  f"verdicts {r['stage_counts']['agg']}, principals {r['stage_counts']['princ']}, "
                  f"flow {r['stage_counts']['flow']}"
                  + (f"   [{', '.join(f'{k}: {v}' for k, v in sorted(s.items()))}]" if s else ""))
    win = t.get("window")
    dropped = [(r["display"], r["runs_available"], r["runs"])
               for r in rows if r["runs_available"] > r["runs"]]
    if win:
        declared = declared_repeats(ROOT)
        src = ("the paper declares \\nRuns = %d" % declared if declared == win
               else "overridden with --last %d; the paper declares \\nRuns = %d"
                    % (win, declared))
        print(f"\nfolding each unit's {win} most recent end-to-end runs ({src})")
        if dropped:
            print("  older runs left out of the window:")
            for name, have, used in dropped:
                print(f"    {name:<26} {have} available, {used} folded")
    else:
        print("\nfolding every end-to-end run each unit has (--last 0)")

    target = t["main_repeat_target"]
    repeat_rows = t["main_repeats"]

    def natural_unit_key(row):
        return [int(part) if part.isdigit() else part.lower()
                for part in re.split(r"(\d+)", row["unit"])]

    print(f"\nmain batch repeat coverage "
          f"(target: {target} end-to-end runs per analysis unit)")
    for ready, heading in ((False, f"NEED MORE (<{target})"),
                           (True, f"READY (>={target})")):
        part = sorted((row for row in repeat_rows if row["ready"] is ready),
                      key=natural_unit_key)
        print(f"\n  {heading}: {len(part)} unit(s)")
        print(f"  {'analysis unit':<88} {'runs':>4} {'missing':>7}")
        print("  " + "-" * 101)
        for row in part:
            print(f"  {row['unit']:<88} {row['runs']:>4} {row['missing']:>7}")
    ready_n = sum(1 for row in repeat_rows if row["ready"])
    print(f"\n  repeat summary: {ready_n}/{len(repeat_rows)} units ready, "
          f"{len(repeat_rows) - ready_n} still below {target}")

    print("\nrun roots read:")
    for r in t.get("run_roots") or []:
        print(f"  {r}")
    for note in t.get("root_notes") or []:
        print(f"  ! {note}")

    budgets = t.get("pv_budgets") or []
    if len(budgets) > 1:
        print(f"\nthe per-query solver ceiling is NOT uniform across the runs the "
              f"tables report: {budgets} seconds. A timeout means a different thing "
              f"under each, so \\ctBudget is left unset; re-run under one ceiling "
              f"or report them apart.")
    stale = [r for r in rows if r["stale_runs"]]
    if stale:
        print("\nruns dropped for reporting on a superseded scale "
              "(aggregate den != the corpus's property count):")
        for r in stale:
            print(f"  {r['display']}: {r['stale_runs']}")

    stage = t["stage_runs"]
    if stage:
        print(f"\nstage and forked runs ({len(stage)}), excluded from the tables "
              f"above and reported here instead:")
        print(f"  {'run':<44} {'entry':<34} scores")
        for display, sc in stage:
            entry = []
            if sc.from_node:
                entry.append(f"from={sc.from_node}")
            if sc.to_node:
                entry.append(f"to={sc.to_node}")
            if sc.forked_from:
                entry.append("forked")
            got = []
            if sc.princ_state == "scored":
                got.append(f"princ {sc.princ_match}/{sc.princ_total}")
            if sc.flow_state == "scored":
                got.append(f"syn {'ok' if sc.syn else 'MISS'}")
                got.append(f"reach {'ok' if sc.reach else 'MISS'}")
            if sc.agg_state == "scored":
                got.append(f"props {sc.props_match}/{sc.props_total}")
            print(f"  {display + '/' + sc.run_dir.name:<44} {', '.join(entry):<34} "
                  f"{', '.join(got) or '(nothing scored)'}")

    scored = sum(1 for r in rows if r["props_match"] is not None)
    print(f"\ncoverage: {scored}/{len(rows)} families fully scored, "
          f"{sum(r['runs'] for r in rows)} end-to-end runs found "
          f"(folded with --agg {agg}), {len(stage)} stage or forked runs set aside")
    print(f"negative side: {t['neg_false']} false + {t['neg_unknown']} unknown "
          f"= {t['neg_total']} properties not established by the expert models")
    drifted = [r for r in rows if r["princ_drift"]]
    if drifted:
        n = sum(r["princ_stale_runs"] for r in drifted)
        print(f"\ninitial knowledge: {n} run(s) in {len(drifted)} families scored "
              f"against an older flow/principals.json and were left out of the "
              f"Princ column. The denominator is the corpus's own count, so a run "
              f"that answered a different one cannot be averaged with the rest.")
        for r in drifted:
            print(f"  {r['display']:<26} {r['princ_stale_runs']} run(s) dropped, "
                  f"their denominators {r['princ_drift']}")

    print(f"declarations: {t['fixed']} fixed / {t['variable']} variable across "
          f"{t['varying_units']} units carrying at least one variable dimension")
    print(f"document-only entries: {t['doc_only']}")

    if kb:
        print(f"threat vocabulary: {kb['categories']} categories, {kb['dimensions']} dimensions, "
              f"{kb['values']} values ({kb['neutral']} neutral, {kb['rewriting']} rewriting, "
              f"{kb['declared_only']} declared-only), {kb['forms']} writing forms")
    else:
        print(f"threat vocabulary: NOT READ ({kb_err}) -- \\dec* macros omitted, "
              f"keep the hand-written ones")

    if t.get("excluded"):
        print("\ndeliberately excluded from the paper (EXCLUDED, counted nowhere):")
        for rel in t["excluded"]:
            print(f"  {rel}")

    if unmapped:
        print("\nunmapped VerdictBench entries (NOT counted anywhere):")
        for rel, why in unmapped:
            print(f"  {rel}: {why}")
    if partial_runs:
        print(f"\nruns with no scoring pass, counted in the flow gates only "
              f"({len(partial_runs)}):")
        for rel, why in partial_runs:
            print(f"  {rel}: {why}")
    if skipped_runs:
        print(f"\nruns found but not scored ({len(skipped_runs)}):")
        for rel, why in skipped_runs[:20]:
            print(f"  {rel}: {why}")
        if len(skipped_runs) > 20:
            print(f"  ... and {len(skipped_runs) - 20} more")
    if doc_only:
        print("\ndocument-only entries:")
        print("  " + ", ".join(doc_only))


def report_summary(rows, totals, unmapped, skipped, partial, agg) -> None:
    """Print the short default report; ``--verbose`` runs the full audit."""
    print("Reproducing the paper from published records (no API calls).")
    print(f"  corpus: {totals['units']} units, {totals['protocols']} families, "
          f"{totals['props']} properties, {totals['verdicts']} verdict cells")
    print(f"  main:   {sum(r['runs'] for r in rows)} runs, "
          f"{_ratio(totals['all_match'], totals['props'])} property matches, "
          f"{_ratio(totals['all_verdicts_match'], totals['verdicts'])} cell matches")
    baseline = totals.get("ablation") or {}
    print("  other:  "
          f"{sum((baseline.get(s) or {}).get('runs', 0) for s in ('Small', 'Large'))} "
          f"baseline runs, {sum(1 for r in rows if r['setup'])} setup rows")
    window = (f"latest {totals['window']} runs per unit"
              if totals["window"] else "all available runs per unit")
    print(f"  fold:   {agg}, {window}")
    # Declared rather than read back: ProVerif prints no banner during a solve,
    # so no run records the version that answered it.
    print(f"  solver: the runs below were produced with ProVerif {PAPER_PROVERIF}")
    warnings = len(unmapped) + len(skipped) + len(partial)
    if warnings:
        print(f"  audit:  {warnings} warning(s); rerun with --verbose for details")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", type=Path, default=LIB_DEFAULT,
                    help="VerdictBench root (default: ./VerdictBench, then ../VerdictBench)")
    ap.add_argument("--runs", type=Path, nargs="+", default=list(RUNS_DEFAULT),
                    help="batch roots (default: ./runs/main ./runs/baseline ./runs/claims)")
    ap.add_argument("--agg", default="mean", choices=["latest", "mean", "median", "best"],
                    help="how to fold repeated runs of the same unit (default: mean)")
    ap.add_argument("--last", type=int, default=DEFAULT_REPEATS, metavar="N",
                    help="fold only each unit's N most recent end-to-end runs. "
                         "Defaults to the paper's three repeats; pass 0 for every run.")
    ap.add_argument("--out", type=Path, default=ROOT / "reproduced",
                    help="output directory (default: ./reproduced)")
    ap.add_argument("--verbose", action="store_true",
                    help="print the per-family coverage and input audit")
    args = ap.parse_args()

    if args.last < 0:
        raise SystemExit("--last must be zero or a positive integer")
    if not args.lib.is_dir():
        raise SystemExit(f"VerdictBench not found: {args.lib}")
    missing_roots = [path for path in args.runs if not path.is_dir()]
    if missing_roots:
        raise SystemExit("run root(s) not found: " + ", ".join(map(str, missing_roots)))

    kb, kb_err = scan_decisions(ROOT, sys.executable)
    if kb is None:
        raise SystemExit(f"could not read Orrery's decision catalogs: {kb_err}")
    rows, totals, doc_only, unmapped, skipped, partial, _ = build(
        args.lib, args.runs, args.agg, kb, args.last)
    if unmapped:
        detail = "; ".join(f"{rel}: {why}" for rel, why in unmapped[:5])
        raise SystemExit(f"unmapped VerdictBench input(s): {detail}")
    roots, _notes = resolve_runs(args.runs)

    check_totals(rows, totals)
    if args.verbose:
        report(rows, totals, doc_only, unmapped, skipped, partial, kb, kb_err, args.agg)
    else:
        report_summary(rows, totals, unmapped, skipped, partial, args.agg)

    args.out.mkdir(parents=True, exist_ok=True)
    outputs = {
        "measured.tex": render_measured(
            rows, totals, kb, args.agg, args.lib, roots, args.last),
        "dataset_rows.tex": render_rows(rows),
        "results.tex": render_tables_tex(rows, totals),
        "results.md": render_markdown(rows, totals, args.agg, args.last),
    }
    for name, content in outputs.items():
        (args.out / name).write_text(content, encoding="utf-8")
    write_csv(args.out / "results.csv", rows)
    payload = {
        "schema_version": 1,
        "aggregation": {"method": args.agg, "latest_runs_per_unit": args.last or None},
        "inputs": {"verdictbench": str(args.lib),
                   "runs": [str(path) for path in roots]},
        "rows": rows,
        "totals": totals,
        "audit": {"document_only": doc_only, "unmapped_corpus": unmapped,
                  "skipped_runs": skipped, "partial_runs": partial},
    }
    (args.out / "results.json").write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote six files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
