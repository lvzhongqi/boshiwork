"""Which files a run is handed, worked out from the protocol directory and the
config's ``inputs`` section.

Console, command line and batch host all ask here, so a protocol resolves its
claims, ground truth, flow model and principals the same way everywhere and
stops at the same node. ``run_protocol`` sits on top as the batch adaptation
target: one call is one run of one protocol, returning flat metrics.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from orrery.modules.document import resolve_subprotocol_name

from orrery.pipeline.config import load_config
from orrery.pipeline.main import run


#: What each switch hands over: one independent choice per artifact. The three
#: claim files are a single entry because claims.json references entries of the
#: other two, so they can only be supplied together.
LIB_SWITCHES = {"lib_principals": ("principals",),
                "lib_flow": ("flow",),
                "lib_claims": ("assumptions", "properties", "claims")}

#: The only dependency between switches: flow_fixed_parts checks a supplied
#: mother model's role signatures against the template rendered from
#: principals.json, so a supplied model over an extracted principals.json fails
#: that check by construction.
NEEDS = {"lib_flow": "lib_principals"}

#: Where a run stops, as the last node producing that artifact. ``scenarios``
#: is the end of the table, so it maps to None — run()'s way of saying no
#: ``to_node``, run to the end.
END_NODE = {"principals": "extract_principals",
            "flow": "extract_flow",
            "claims": "extract_claims",
            "scenarios": None}

#: Which switch each end stop makes pointless: stopping after the flow model
#: on a run that was handed the flow model does no work at all.
_END_SUPPLIES = {"principals": ("lib_principals",),
                 "flow": ("lib_principals", "lib_flow"),
                 "claims": ("lib_principals", "lib_flow", "lib_claims")}


def to_node_for(end_point: str) -> str | None:
    """Where a run ending at this stop stops: run()'s ``to_node``."""
    if end_point not in END_NODE:
        raise ValueError(f"inputs.end_point: {end_point!r} is not an end point; "
                         f"it is one of {', '.join(END_NODE)}")
    return END_NODE[end_point]


def check_inputs(end_point: str, **switches: bool) -> None:
    """Refuse an unworkable set of input choices before the run starts.

    Raises ValueError when a switch's dependency in NEEDS is off, when the end
    point is not one of END_NODE, or when every artifact up to the end point is
    supplied — that last case would walk the table doing nothing and report
    success, which looks like a result.
    """
    for switch, needed in NEEDS.items():
        if switches.get(switch) and not switches.get(needed):
            raise ValueError(
                f"inputs.{switch} needs inputs.{needed}: a mother model has to "
                f"come with the principals.json carrying its stable values and "
                f"dependency edges")
    if end_point not in END_NODE:
        raise ValueError(f"inputs.end_point: {end_point!r} is not an end point; "
                         f"it is one of {', '.join(END_NODE)}")
    # `scenarios` has no entry: build_world onward is always the run's own work,
    # and an empty tuple would make all() vacuously true.
    needed = _END_SUPPLIES.get(end_point, ())
    if needed and all(switches.get(k) for k in needed):
        raise ValueError(
            f"inputs.end_point={end_point} with every artifact up to it taken "
            f"from the corpus leaves the run nothing to do: it would walk the "
            f"table writing back the files it was handed and report success. "
            f"Extract one of them, or move the end point later")


def supplied_of(meta: dict) -> dict:
    """What a finished run was handed and where it stopped, read back off its
    run.json — ``{"lib": [...], "end": ...}``.

    The lib half is derived from the files the run actually recorded, not from
    a setting: a run started from the command line with explicit paths has no
    switches at all.
    """
    lib = [switch for switch, files in LIB_SWITCHES.items()
           if all(meta.get(f) for f in files)]
    end = next((k for k, v in END_NODE.items() if v == meta.get("to_node")),
               "scenarios")
    return {"lib": lib, "end": end}


def artifact_paths(root: Path) -> dict[str, Path]:
    """Where each supplied artifact lives under one protocol root.

    The single table both the resolver below and the launch panel read: one
    opens these paths, the other tests them for existence.
    """
    return {"assumptions": root / "claims" / "assumptions.json",
            "properties": root / "claims" / "properties.json",
            "claims": root / "claims" / "claims.json",
            "flow": root / "flow" / "flow.pv",
            "principals": root / "flow" / "principals.json"}


def supplies(root: Path) -> dict[str, bool]:
    """Which switches this directory can actually answer, keyed by switch name.

    ``resolve_lib_inputs`` refuses a switch whose files are missing, so the
    launch panel asks this first and greys out the ones with nothing to point
    at. Derived from LIB_SWITCHES, so a fourth switch needs no change here.
    """
    where = artifact_paths(root)
    return {switch: all(where[f].is_file() for f in files)
            for switch, files in LIB_SWITCHES.items()}


def resolve_lib_inputs(protocol: Path, subprotocol: str | None = None,
                       assumptions=None, properties=None, claims=None,
                       ground_truth=None, flow=None, principals=None,
                       *, lib_principals: bool = False,
                       lib_flow: bool = False, lib_claims: bool = True):
    """What the corpus layout can hand this run, keyed by run()'s parameter
    names: a protocol keeps its files in its own directory, a sub-protocol
    under subprotocols/<name>/. An off lib_* switch leaves its files None for
    the extraction nodes, and explicit arguments win over the layout.
    ground_truth needs results/; a missing lib file raises FileNotFoundError.
    """
    subprotocol = resolve_subprotocol_name(protocol, subprotocol)
    root = protocol / "subprotocols" / subprotocol if subprotocol else protocol
    on = {"lib_principals": lib_principals, "lib_flow": lib_flow,
          "lib_claims": lib_claims}
    want = {f for switch, files in LIB_SWITCHES.items()
            if on[switch] for f in files}
    have = {"assumptions": assumptions, "properties": properties,
            "claims": claims, "flow": flow, "principals": principals}
    where = artifact_paths(root)
    missing = []
    for name in sorted(want):
        if have[name] is not None:
            continue                          # named outright, and that wins
        if not where[name].is_file():
            missing.append(str(where[name]))
            continue
        have[name] = where[name]
    if missing:
        raise FileNotFoundError(
            "the inputs.lib_* switches ask for files this protocol does not "
            "carry: " + ", ".join(missing) + ". Write them there, or turn the "
            "switch off and let the extraction do its own work")
    assumptions, properties = have["assumptions"], have["properties"]
    claims, flow, principals = have["claims"], have["flow"], have["principals"]
    if ground_truth is None and (root / "results").exists():
        ground_truth = root
    return {"assumptions": assumptions, "properties": properties,
            "claims": claims, "ground_truth": ground_truth,
            "flow": flow, "principals": principals}


async def run_protocol_async(
    protocol_name: str,
    protocol: str | Path,
    *,
    version: str | None = None,
    subprotocol: str | None = None,
    ground_truth: str | Path | None = None,
    assumptions: str | Path | None = None,
    properties: str | Path | None = None,
    claims: str | Path | None = None,
    config: str | Path | dict | None = None,
    config_overrides: dict | None = None,
    run_name: str | None = None,
) -> dict:
    """One protocol, one run, flat metrics — awaited on the caller's own event
    loop, so a batch host can schedule several runs together. The batch host
    owns run concurrency and each run owns its scenario concurrency; LLM
    requests and ProVerif subprocesses have no process-wide limit. Claims and
    ground truth default to the corpus layout under the protocol directory.
    """
    protocol = Path(protocol)
    # require=False because this read only needs inputs.*; a config too
    # incomplete to run still says which files to hand over, and the real
    # completeness check happens when the run starts below.
    ins = load_config(config, config_overrides, require=False)["inputs"]
    lib = {k: ins[k] for k in ("lib_principals", "lib_flow", "lib_claims")}
    check_inputs(ins["end_point"], **lib)
    resolved = resolve_lib_inputs(
        protocol, subprotocol, assumptions, properties, claims, ground_truth,
        ins["flow"], ins["principals"], **lib)

    # Per-trial overrides are merged into one config here; run() only takes a
    # single config.
    cfg = load_config(config, config_overrides) if config_overrides else config
    r = await run(
        protocol_name, protocol, cfg,
        version=version, subprotocol=subprotocol,
        run_name=run_name, to_node=to_node_for(ins["end_point"]), **resolved,
    )
    return {
        "status": r.status,
        "acc": r.metrics.get("acc"),
        "match_count": r.metrics.get("match_count", 0),
        "total_count": r.metrics.get("total_count", 0),
    }


def run_protocol(protocol_name: str, protocol: str | Path, **kwargs) -> dict:
    """The synchronous entry point, callable by a batch runner as an ordinary
    function. It owns the event loop, so it runs one protocol per call; running
    several at once means awaiting run_protocol_async instead."""
    return asyncio.run(run_protocol_async(protocol_name, protocol, **kwargs))
