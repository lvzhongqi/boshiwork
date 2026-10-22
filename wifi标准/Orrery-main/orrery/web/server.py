"""HTTP surface of the web console: a reader of the run directory plus the SSE
event stream the page folds into a view.

A route is a path rule plus a read; nothing here interprets a verdict or a node.
Every run this server holds runs on uvicorn's own loop, held by api/registry.py.
The ledger's ``seq`` is the SSE ``id:``, so a reconnect replays from a line
number; fragments carry no ``id:`` and must not move a reader's resume point.
"""

from __future__ import annotations

import asyncio
import json
import os
import traceback
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from orrery.api import (
    KNOWN, ExpertAsked, ExpertReplied, Host, ReviewClosed,
)
from orrery.api import attacks as api_attacks
from orrery.api import browse as api_browse
from orrery.api import playback as api_playback
from orrery.api import runs as api_runs
from orrery.api import settings as api_settings
from orrery.api import vocabulary as api_vocab
from orrery.api.corpus_inputs import (
    check_inputs, resolve_lib_inputs, supplies, to_node_for,
)
from orrery.api.host import asked_of
from orrery.api.playback import claims_shape
from orrery.api.reading_order import HEADLINE
from orrery.api.registry import RunRegistry
from orrery.api.settings import MissingConfigError

STATIC = Path(__file__).parent / "static"

#: How long a re-entry waits for the run it is replacing to unwind. Past it the
#: request answers with a 409 rather than going silent.
STOP_TIMEOUT_S = 30.0


def _configured_work_root() -> Path:
    """Where the runs are, according to the config file.

    Loaded with ``require=False`` so a config still missing its api_key does not
    keep the console shut; reading a run needs no model and no solver. The path
    comes back anchored to the project root, so it means the same directory
    whichever one uvicorn was started in.
    """
    return api_settings.work_root(app.state.config_path)


def _work_root() -> Path:
    """The tree the run routes read: the recorded runs in playback mode, the
    configured work root otherwise. That is the only difference — `_run_dir`,
    the run list and the file routes are directory readers and do not learn
    which tree they were pointed at.

    Both sides are config values (paths.playback_root, paths.work_root), so
    every route that writes one of them re-reads this — cached rather than
    resolved per request, because every run route goes through it.
    """
    return (app.state.playback.root if app.state.playback.on
            else _configured_work_root())


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Nothing on the way up; on the way down, stop what is running.

    An interrupted run unwinds — it finishes the file it is writing and seals
    what it has. Killed instead, it leaves a directory that is neither a
    complete run nor a resumable one.
    """
    yield
    for queue in list(app.state.reproductions.values()):
        await queue.stop()
    await app.state.registry.stop_all()


app = FastAPI(title="Orrery console", lifespan=_lifespan)
app.state.registry = RunRegistry()
# The attack reproductions asked for after a run, one queue per run
# (api/attacks.Reproductions), created on the first request.
app.state.reproductions = {}


@app.middleware("http")
async def _same_origin_writes(request: Request, call_next):
    """A request that changes something has to come from this console's own
    page. The console has no login, so any page open in the same browser could
    otherwise post an interrupt, a release or a stop at it: the three routes
    without a body are simple requests, sent without a preflight. A browser
    puts the page's origin on every such request, and one that names another
    site is refused. Requests with no Origin (curl, the test client) are not a
    browser's and pass.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin is not None and urlsplit(origin).netloc != request.headers.get("host", ""):
            return JSONResponse(
                status_code=403,
                content={"detail": f"refused: the request came from {origin}, "
                                   f"not from this console's own page"})
    return await call_next(request)
# The config file this process serves: config.yaml at the project root, made
# from config.example.yaml on first start, or ORRERY_CONFIG for two configs side
# by side. Read once, so every route serves the same answer.
app.state.config_path = (os.environ.get("ORRERY_CONFIG")
                         or api_settings.default_config_path())
# Playback is the default and a runtime switch rather than a launch flag: the
# published artifact has no API key and still has to show a run, and the same
# build has to be the real thing once a key is pasted in. Everything it implies
# belongs to api/playback.py, including which tree it reads
# (paths.playback_root), which it takes from this same config file.
app.state.playback = api_playback.Mode(app.state.config_path)
app.state.work_root = _work_root()


@app.exception_handler(PermissionError)
async def _refused(request: Request, exc: PermissionError) -> JSONResponse:
    """What a write asked of a console in playback mode gets back: 409 rather
    than 403, because nothing is wrong with the request — the console is in a
    state that cannot serve it, and the page says so next to the switch.
    """
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """An endpoint that crashed, answered in the shape the page already reads.

    FastAPI's default plain-text "Internal Server Error" reaches the console as
    a JSON parse failure naming neither the request nor the fault. This is a
    console served on localhost to the person running it, so the request line
    and the exception text go out with the 500; the traceback still goes to the
    log.
    """
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"{request.method} {request.url.path} failed: "
                           f"{type(exc).__name__}: {exc}"})


def _run_dir(name: str) -> Path:
    """A run name → its directory. Names are unique inside one work root, so the
    protocol layer is searched rather than asked for."""
    if not app.state.work_root.is_dir():
        # Named rather than left to raise from iterdir: "the work root is not
        # there" and "that run is not in it" send a reader to different places.
        raise HTTPException(
            404, f"the work root does not exist: {app.state.work_root} "
                 f"(paths.work_root)")
    # One path segment naming a run, and nothing that walks: ``..`` joins to
    # the work root and ``.`` to a protocol directory, and either one lets the
    # per-run routes read past the run they name.
    if (name in (".", "..") or "/" in name or "\\" in name
            or name in api_runs.RESERVED):
        raise HTTPException(404, f"{name!r} is not a run name")
    for proto in sorted(app.state.work_root.iterdir()):
        if proto.is_dir() and (d := proto / name).is_dir():
            return d
    raise HTTPException(404, f"no run called {name!r} under {app.state.work_root}")


class _WebHost(Host):
    """The host a browser speaks through: printing events and asking about a
    fix both happen on the event stream, so the abstract methods are answered by
    the bus. ``confirm`` sends its question out as an event and awaits a future
    that a POST resolves; that future is what holds the fix loop still.
    """

    def __init__(self, cfg_path: str | None, overrides: dict | None = None) -> None:
        # Overrides are config.py's third level: what the settings panel changes
        # applies to the run being started and leaves the file on disk alone.
        super().__init__(config=cfg_path, overrides=overrides)
        self.pending: asyncio.Future | None = None
        self.plan = None
        # The turn in flight, so it can be stopped. A question runs with no
        # ceiling on rounds or readings (config.expert), so the reader is the
        # only thing that ends a turn that will not end itself.
        self.turn: asyncio.Task | None = None

    def on_event(self, event) -> None:
        pass                    # the page reads the stream; nothing to do here

    async def confirm(self, plan, cost) -> bool:
        # ``step`` is the plan's address: a directory path that may be a node
        # name or something far narrower (one apply point, one inject family).
        # The card shows it verbatim, next to the cost of that step.
        self.plan = {"step": plan.step, "kind": cost.from_node,
                     "mode": plan.mode,
                     "message": plan.message, "rationale": plan.rationale,
                     "reruns": cost.reruns, "superseded": cost.superseded}
        self.pending = asyncio.get_running_loop().create_future()
        try:
            return await self.pending
        finally:
            self.pending = self.plan = None


def _host(name: str) -> Host:
    """The host holding this run, attaching one on first use. A run this process
    is executing already has one and the registry hands that back, so an expert
    session joins the run's own bus instead of opening a second writer on its
    ledger.
    """
    entry = app.state.registry.get(name)
    if entry is not None and entry.host._session is not None:
        return entry.host
    host = entry.host if entry is not None else _WebHost(app.state.config_path)
    app.state.registry.attach(name, host, _run_dir(name))
    return app.state.registry.get(name).host


def _bus_of(name: str):
    """This run's event stream, whoever is holding it."""
    entry = app.state.registry.get(name)
    if entry is None:
        return None
    if entry.run is not None:
        return entry.run.bus
    return entry.host.bus


# ── the run list ─────────────────────────────────────────────────────────────

@app.get("/api/runs")
def runs() -> list[dict]:
    """Every run under the current work root, as the list panel renders it."""
    # Whether a run is really in flight is a fact about processes, not the tree:
    # a killed run leaves `running` in its run.json for ever. Only the recorded
    # tree lets this process answer it, since nothing else executes there; a live
    # work root is shared with `orrery run`, so run_list is told to say nothing.
    live = app.state.registry.running() if app.state.playback.on else None
    return api_runs.run_list(app.state.work_root, live)


@app.get("/api/config")
def config() -> dict:
    """The effective config as a flat list of knobs, ready to render.

    A declaration, not a dump: each entry says its path, its current value, its
    type, the values it may take and whether it can be edited here, so the
    console draws what this says and works nothing out for itself. Credentials
    never make it out — api/settings.py owns that rule.
    """
    return api_settings.describe(app.state.config_path, app.state.work_root)


@app.post("/api/config")
def save_config(body: dict) -> dict:
    """Set one config value and keep it — write it into config.yaml.

    Persisting rather than overriding, for the audience that pastes a key on the
    page and never opens the file. The write, the validation and every refusal
    belong to api/settings.py; here a refusal becomes a 400 and the page is
    redrawn from what was actually stored.
    """
    try:
        api_settings.store(app.state.config_path,
                           body.get("path"), body.get("value"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    # The work root is cached because every run route resolves through it, and
    # this write may have been the one that moved it — either root can be the
    # value that just landed.
    app.state.work_root = _work_root()
    return config()


@app.get("/api/playback")
def playback_mode() -> dict:
    """Which mode the console is in, and what it found to play back."""
    return app.state.playback.describe()


@app.post("/api/playback")
async def set_playback_mode(body: dict) -> dict:
    """Switch between playing back the record and running for real. The work
    root moves with it: playback reads paths.playback_root, live reads whatever
    paths.work_root says.
    """
    out = await app.state.playback.set(bool(body.get("on")))
    app.state.work_root = _work_root()
    return out


@app.get("/api/meta/vocabulary")
def vocabulary() -> dict:
    """What each assumption subtype, each goal subtype and each pipeline step
    means, one sentence apiece.

    Not per-run and not on the ledger: it is the same for every run this build
    serves, so the page asks once and uses it for the tooltips on a dimension's
    value, on a goal's kind and on a step. Answered by api/vocabulary.py, off
    the registries that own it.
    """
    return {
        **api_vocab.vocabulary(),
        # This console's own ceiling on attachments, not the engine's, enforced
        # by the chat POST below. A page holding its own copy of the number
        # would offer an attach that the POST then refuses.
        "max_attached": MAX_ATTACHED,
    }


@app.get("/api/meta/event-types")
def event_types() -> list[str]:
    """Every event type the backend can send. The page compares this against
    what it handles and says on screen when it does not handle one."""
    return sorted(KNOWN)


@app.get("/api/browse")
def browse(path: str | None = None) -> dict:
    """One directory of this machine, for the launch panel's browser.

    Opens on the reader's home when nothing is asked for. A path that is not
    there is a 400 rather than an empty listing: it is something the reader
    typed or a link that went stale, and both want saying.
    """
    try:
        return api_browse.listing(Path(path) if path else Path.home())
    except (NotADirectoryError, FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None


@app.get("/api/target")
def target(path: str) -> dict:
    """What the reader pointed at, resolved into what a run would be given:
    which directory, which document, what the switches can be answered with.
    /api/protocols sweeps a corpus for candidates; this resolves one choice that
    has already been made.
    """
    try:
        return api_browse.resolve(Path(path))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None


@app.get("/api/protocols")
def protocols(root: str | None = None) -> dict:
    """What is runnable under a corpus root: every directory that declares
    claims, with its sub-protocols and whether it brings ground truth.

    A suggestion, not a resolution. The ``protocol_id`` in results/results.json
    cannot be trusted as a name — some entries have no results file and some
    fill the field with their own relative path — so a name that fails those
    tests comes back empty and the launch form asks. The version is never
    guessed either: the last path segment is the protocol for academic/NSSK and
    the version for rfc/EDHOC/draft-08, and nothing in the layout says which.
    One corpus at a time: paths.lib_root, or whatever root the panel asks for.
    """
    if app.state.playback.on:
        try:
            return app.state.playback.protocols(root)
        except FileNotFoundError as e:
            raise HTTPException(400, str(e)) from None
    corpus = api_settings.corpus(app.state.config_path)
    # No root given means the configured one (paths.lib_root), so the panel opens
    # on a corpus rather than on an empty box. The default points at a checkout
    # beside this one, the layout the published artifact ships in.
    base = Path(root).expanduser() if root else corpus["lib"]
    if root and not base.is_dir():
        # Typed by hand, so say so. A configured root that is simply not there
        # is the ordinary state of a checkout without a corpus beside it, and is
        # passed over below instead.
        raise HTTPException(400, f"not a directory: {base}")
    found: dict[str, dict] = {}
    for claims in sorted(c for c in (base.rglob("claims/claims.json")
                                     if base.is_dir() else ())
                         # A leading underscore means not part of the tree's own
                         # subject. A work root typed into this box holds a
                         # stowed copy of the answers under every protocol, in
                         # the corpus's own layout, and a copy is not a second
                         # protocol to run.
                         if not any(seg.startswith("_")
                                    for seg in c.relative_to(base).parts)):
        home = claims.parent.parent
        sub = None
        if home.parent.name == "subprotocols":
            home, sub = home.parent.parent, home.name
        rel = str(home.relative_to(base))
        # Keyed by the absolute directory, not by the corpus-relative path: two
        # roots can hold the same relative path, and rows colliding on it would
        # fold into one showing one directory's numbers over another's files.
        entry = found.setdefault(str(home),
                                      {"dir": rel, "abs": str(home), "name": None,
                                       "version": None, "subprotocols": [],
                                       "ground_truth": False, "goals": 0,
                                       "scenarios": 0, "cells": 0, "doc": 0})
        if sub is not None and sub not in entry["subprotocols"]:
            entry["subprotocols"].append(sub)
        if (claims.parent.parent / "results").is_dir():
            entry["ground_truth"] = True
        goals, scenarios, cells = claims_shape(claims)
        entry["goals"] += goals
        entry["scenarios"] += scenarios
        entry["cells"] += cells
    for entry in found.values():
        # The corpus-relative path, off the entry rather than the key, which is
        # absolute: the two calls below read a path like "rfc/EDHOC/draft-08" to
        # tell a protocol from a version.
        rel = entry["dir"]
        # What each switch can be answered with, per sub-protocol, because that
        # is the directory resolve_lib_inputs actually opens. Keyed by name with
        # "" for a protocol that has none, so the panel looks up whichever the
        # form selected instead of working the layout out again.
        home = Path(entry["abs"])
        entry["supplies"] = {
            (sub or ""): supplies(home / "subprotocols" / sub if sub else home)
            for sub in (entry["subprotocols"] or [""])}
        entry["doc"] = _doc_size(Path(entry["abs"]))
        entry["name"], entry["version"] = _declared_name(
            Path(entry["abs"]), rel, entry["subprotocols"])
        entry["name_from"] = "declared"
        if entry["name"] is None:
            entry["name"], entry["version"] = _name_from_path(rel)
            entry["name_from"] = "path"
    # Ordered for a reader opening this list for the first time. HEADLINE names
    # the ones that come first, as prefixes rather than exact paths, so a
    # protocol with several drafts takes one position and orders its drafts by
    # the fallback. Everything else follows in two bands split on
    # inline_max_chars — a document that fits is given to the extraction steps
    # whole, one that does not has to be excerpted — then by the cells the claims
    # ask for, which is the work a run actually does.
    cap = api_settings.inline_max_chars()

    def rank(e: dict) -> tuple:
        at = next((i for i, pre in enumerate(HEADLINE)
                   if e["dir"] == pre or e["dir"].startswith(pre + "/")),
                  len(HEADLINE))
        # One corpus is listed at a time, so every row came from the same root
        # and the reading order is the whole answer.
        return (at, e["doc"] > cap, e["cells"], e["dir"])

    return {"root": str(base), "protocols": sorted(found.values(), key=rank)}



def _doc_size(home: Path) -> int:
    """The protocol's source text, in bytes — a stand-in for how much document
    the extraction steps have to read. It is compared against inline_max_chars,
    which counts characters; the comparison is a band, not a threshold anything
    depends on."""
    src = home / "source"
    return sum(f.stat().st_size for f in src.rglob("*") if f.is_file()) \
        if src.is_dir() else 0


def _name_from_path(rel: str) -> tuple:
    """A name and version read off the directory path, for a corpus entry that
    declares none usable.

    A suggestion, and the form marks it as one. The convention it assumes:
    below the top-level category, the last segment is the version when there is
    more than one segment. A wrong guess is harmless — the name only titles the
    run directory, and the ground truth is passed by path.
    """
    parts = [p for p in rel.split("/") if p][1:]     # drop the category
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return "-".join(parts[:-1]), parts[-1]


def _declared_name(home: Path, rel: str, subs: list[str]) -> tuple:
    """The corpus's own protocol_id, taken apart into (name, version).

    ``protocol_id`` joins name, version and sub-protocol with hyphens
    (services/store/runs.py), so ``EDHOC-draft-08-asymmetric`` comes apart by
    stripping the sub-protocol this file belongs to and then the path's last
    segment, which is what makes that segment the version. Anything that does
    not come apart cleanly yields (None, None) and the launch form asks: a name
    taken on trust would build the run directory under the wrong identity.
    """
    for probe in [home] + [home / "subprotocols" / s for s in subs]:
        try:
            pid = json.loads((probe / "results" / "results.json")
                             .read_text(encoding="utf-8")).get("protocol_id")
        except (OSError, ValueError):
            continue
        if not pid or "/" in str(pid):
            continue                       # a path in the id field, not a name
        pid = str(pid)
        if probe is not home:
            # A sub-protocol's id ends with its own segment, so a suffix that
            # will not come off means this file was not built the way the join
            # builds them and what is left is not a name. Matched
            # case-insensitively: `ISO-9798-2-Mechanism-1` sits in a directory
            # called `mechanism-1`.
            if not pid.lower().endswith(f"-{probe.name.lower()}"):
                continue
            pid = pid[: -len(probe.name) - 1]
        tail = home.name
        if pid != tail and pid.endswith(f"-{tail}"):
            return pid[: -len(tail) - 1], tail
        return pid, None
    return None, None


@app.post("/api/runs")
async def start_run(body: dict) -> dict:
    """Start a run on this process's loop, and answer with the name it took.

    The name matters in the reply because the ordinary case is not to give one:
    the engine allocates the next free ``<protocol id><NN>`` and the page has
    nowhere to navigate until it knows what that was. The config is loaded here
    in full, llm and proverif included — the stream route tolerates a config too
    incomplete to run anything so a run can always be read, and a launch must
    not inherit that tolerance.
    """
    if app.state.playback.on:
        try:
            return await app.state.playback.start(body)
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(400, str(e)) from None
    name = (body.get("protocol_name") or "").strip()
    directory = (body.get("protocol_dir") or "").strip()
    if not name or not directory:
        raise HTTPException(
            400, "protocol_name and protocol_dir are both required: the "
                 "directory cannot supply the name (its last segment is the "
                 "protocol for academic/NSSK and the version for "
                 "rfc/EDHOC/draft-08)")
    sub = body.get("subprotocol") or None
    # The documents, when the page names them — a reader analysing their own file
    # rather than a corpus entry; absent, load_document discovers them under the
    # directory. Not a setting: which document to read is what a launch is, not
    # how the console is configured.
    main_doc = (body.get("main_doc") or "").strip()
    documents = ({"main": main_doc,
                  "refs": [r for r in (body.get("ref_docs") or []) if r]}
                 if main_doc else None)
    # No overrides from the page: every setting it can change it has already
    # written to config.yaml, so the file is the whole answer.
    try:
        host = _WebHost(app.state.config_path)
    except MissingConfigError as e:
        raise HTTPException(400, f"cannot start a run: {e}") from None
    # Which bands the corpus hands over is read off inputs.*, not off the body:
    # the panel's two switches are knobs the page saves before starting anything,
    # so a command-line run with the same config resolves the same files.
    ins = host.cfg["inputs"]
    lib = {k: ins[k] for k in ("lib_principals", "lib_flow", "lib_claims")}
    try:
        check_inputs(ins["end_point"], **lib)
        resolved = resolve_lib_inputs(
            Path(directory), sub, flow=ins["flow"],
            principals=ins["principals"], **lib)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None
    try:
        entry = app.state.registry.start(
            body.get("run_name") or None, host, name, directory,
            version=body.get("version") or None, subprotocol=sub,
            from_node=body.get("from_node") or None,
            # Where the run ends comes off the range setting the page saved. A
            # body may still name a node outright, which is what a re-entry from
            # the strip does.
            to_node=(body.get("to_node")
                     or to_node_for(ins["end_point"])),
            documents=documents, **resolved)
    except (ValueError, FileNotFoundError, FileExistsError, RuntimeError) as e:
        raise HTTPException(400, str(e)) from None
    return {"name": entry.run.layout.run_name}


@app.post("/api/runs/{name}/rerun")
async def rerun(name: str, body: dict) -> dict:
    """Re-enter a run that stopped, at one of its own nodes, in place.

    ``from_step`` is a step's identity path and a node name is its shortest
    form: ``scenarios`` redoes the stage and everything under it,
    ``scenarios/baseline`` one scenario, ``scenarios/baseline/inject/Secrecy``
    one goal family. The deeper the aim, the less is re-bought. What is aimed at
    runs into a new directory and the earlier one stops being current;
    everything else is reused as it stands and nothing is deleted. A run still
    in flight is stopped first and the reply says so (``interrupted``). What the
    run was asked comes back out of its own run.json, never from the request, so
    attempts stay comparable.
    """
    app.state.playback.refuse("re-entering a run")
    step = (body.get("from_step") or "").strip()
    if not step:
        raise HTTPException(
            400, "from_step is required: the re-entry point is what decides "
                 "which work is kept and which is done again. One address "
                 "space, at every depth — a node ('scenarios'), one scenario "
                 "('scenarios/baseline'), one apply point or one goal family "
                 "('scenarios/baseline/inject/Secrecy')")
    run_dir = _run_dir(name)
    meta = api_runs.run_meta(run_dir)
    # Everything that can refuse the request is asked before anything is
    # stopped: a mistyped address must not cost the run in flight.
    try:
        api_runs.rerun_target(run_dir, meta, step)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    # The host that already holds this run, not a new one: the page's stream and
    # any expert session are attached to it, and a second host would bind a
    # second bus to one ledger (api/host.py::make_run).
    try:
        host = _host(name)
    except MissingConfigError as e:
        raise HTTPException(400, f"cannot re-enter {name}: {e}") from None
    # A run in flight is stopped first, not refused: re-entering is how a person
    # says "not like that, do it again from here", and it is worth most while the
    # wrong thing is still being bought. The run unwinds rather than being
    # killed, so everything already on disk stays where it is.
    # Reproductions asked for on the old attempt stop too: the re-entry is
    # about to redo what they are built on.
    queue = app.state.reproductions.get(name)
    if queue is not None:
        await queue.stop(timeout=STOP_TIMEOUT_S)
    try:
        stopped = await app.state.registry.stop(name, timeout=STOP_TIMEOUT_S)
    except TimeoutError as e:
        raise HTTPException(
            409, f"{e}. It stops at the first point it can — usually the end of "
                 f"the model call or solver run in flight. Ask again in a "
                 f"moment.") from None
    # Resolved again once the run has unwound: it wrote to the index while it
    # stopped, and the answer is one file read. Refusals were dealt with above.
    ref = api_runs.rerun_target(run_dir, meta, step)
    directory = Path(meta["protocol_dir"])
    # work_root is pinned to where this run actually lives, whatever the
    # config says now.
    overrides = {"paths": {"work_root": str(run_dir.parent.parent)}}
    try:
        cfg = api_settings.merge(host.cfg, overrides)
        app.state.registry.start(
            name, host, meta["protocol"], directory, config=cfg,
            # Everything the run was asked, restated from its own record in one
            # move (api/host.py::asked_of). Listed there and not here, because
            # the expert's fix re-runs the same way and a list kept in two
            # places is a list that loses an entry.
            **asked_of(meta),
            from_node=ref.node, from_step=ref.path)
    except (MissingConfigError, ValueError, FileNotFoundError,
            RuntimeError) as e:
        raise HTTPException(400, str(e)) from None
    return {"name": name, "from_node": ref.node, "from_step": ref.path,
            "interrupted": stopped}


# ── one run ──────────────────────────────────────────────────────────────────

@app.delete("/api/runs/{name}")
def remove_run(name: str) -> dict:
    """Delete one run, whole.

    Irreversible, and the only thing in this console that destroys anything.
    A run this process is executing is refused, since deleting the directory
    under a live writer leaves it writing into nothing; the run's registry entry
    goes with it, so no later request reaches a host bound to a gone directory.
    """
    app.state.playback.refuse("deleting a run")
    entry = app.state.registry.get(name)
    if entry is not None and entry.running:
        raise HTTPException(
            409, f"run {name!r} is still in flight; interrupt it before "
                 f"deleting it")
    # An expert turn writes to the directory too (its transcript, the ledger),
    # and every writer re-creates the path it writes under: deleted from under
    # one, the run comes back as a directory with no run.json in it.
    turn = getattr(entry.host, "turn", None) if entry is not None else None
    if turn is not None and not turn.done():
        raise HTTPException(
            409, f"the expert is still answering on {name!r}; stop the "
                 f"question before deleting the run")
    queue = app.state.reproductions.get(name)
    if queue is not None and queue.busy:
        raise HTTPException(
            409, f"attacks are still being reproduced on {name!r}; stop them "
                 f"before deleting the run")
    run_dir = _run_dir(name)
    try:
        removed = api_runs.remove(app.state.work_root, run_dir.parent.name,
                                  name)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e)) from None
    app.state.registry.forget(name)
    app.state.reproductions.pop(name, None)
    return {"removed": removed}


@app.get("/api/runs/{name}/stream")
async def stream(name: str, request: Request, since: int = 0):
    """The ledger as Server-Sent Events, from ``since`` (or Last-Event-ID on a
    reconnect) to the end, then whatever the bus produces next.

    History and live traffic are the same frames, so the page has one code path
    for both. A run this process is not executing ends after its history.
    """
    run_dir = _run_dir(name)
    last = request.headers.get("last-event-id")
    start = int(last) + 1 if last and last.isdigit() else since

    queue: asyncio.Queue = asyncio.Queue(maxsize=2048)
    # A playback is a second producer on this same stream, bringing its own bus
    # and history, and nothing below this line knows the difference. No host is
    # attached for one: a host builds a model client, and a playback exists for
    # the reader who has no key to build it with.
    rp = app.state.playback.session(name)
    # Attaching is what makes the page live before anyone has typed: the bus does
    # not exist until a host holds the run. Without a usable config the stream
    # degrades to history and ends — a run can always be read, only asking needs
    # credentials.
    if rp is None and not app.state.playback.on:
        # Only a credential may be missing here — a run can always be read,
        # only asking needs one. Anything else is a fault and stays loud.
        try:
            _host(name)
        except MissingConfigError:
            pass
    # Whichever bus this run has: the engine's while it executes, the host's once
    # an expert session attaches. The same object when both hold — attach reuses
    # a live run's bus rather than binding a second one to the same ledger.
    bus = rp.bus if rp is not None else _bus_of(name)
    unsubscribe = None
    history: list[dict] | None = None
    # Set when the queue overflowed on a durable event. Dropping one of those
    # would leave a hole in the reader's sequence that no reconnect fills
    # (Last-Event-ID resumes after the last frame it did get), so the stream
    # is closed instead: the browser reconnects with that id and the missing
    # rows come back off the ledger, where they are.
    overflowed = []

    # Never block in a bus subscriber: it is called inline from the engine,
    # so a full queue drops fragments rather than slowing the run down.
    def on_event(ev) -> None:
        try:
            queue.put_nowait(ev)
        except asyncio.QueueFull:
            if ev.durable and not overflowed:
                overflowed.append(ev.seq)

    if bus is not None:
        unsubscribe = bus.subscribe(on_event)
        # Snapshot after subscribing, with no await in between: a playback is
        # already emitting when this route opens, and an event landing between
        # the two reads would otherwise be in neither.
        if rp is not None:
            history = rp.history(start)

    async def frames():
        nonlocal bus, unsubscribe
        last = start - 1
        try:
            for row in (api_runs.ledger(run_dir, since=start)
                        if history is None else history):
                last = max(last, int(row.get("seq", last)))
                yield _frame(row)
            while True:
                if await request.is_disconnected():
                    break
                if bus is None:
                    # Nothing is speaking on this run yet. Held open rather
                    # than ended: ended, the browser reconnects every few
                    # seconds for as long as the page is up. A bus appears
                    # when something starts (a re-entry from the strip, the
                    # expert attaching), and the rows it wrote before this
                    # side subscribed are read off the ledger.
                    await asyncio.sleep(5)
                    yield ": keep-alive\n\n"
                    bus = None if app.state.playback.on else _bus_of(name)
                    if bus is not None:
                        unsubscribe = bus.subscribe(on_event)
                        for row in api_runs.ledger(run_dir, since=last + 1):
                            last = max(last, int(row.get("seq", last)))
                            yield _frame(row)
                    continue
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"      # keeps proxies from closing us
                    continue
                if overflowed and ev.durable and ev.seq >= overflowed[0]:
                    break            # the reader catches up from the ledger
                yield _frame(json.loads(ev.to_line()), durable=ev.durable)
        finally:
            if unsubscribe is not None:
                unsubscribe()

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def _frame(row: dict, durable: bool = True) -> str:
    """One SSE frame. A non-durable event carries no ``id:`` — it is not on the
    ledger, so it must not become a reader's resume point.

    Frames are unnamed: a named event makes EventSource dispatch to a per-name
    listener, so a client would have to enumerate every type up front and would
    drop in silence anything it did not name. The type is in the payload as
    ``t``, and one ``onmessage`` reads every event there is.
    """
    head = f"id: {row['seq']}\n" if durable else ""
    return f"{head}data: {json.dumps(row, ensure_ascii=False)}\n\n"


@app.get("/api/runs/{name}/tree")
def tree(name: str) -> dict:
    """The run's files, and the index that says which of them are current.

    Both, because neither answers on its own: a run that went back holds more
    than one directory per step. Resolved by api/runs.py the same way the engine
    does, so the page never re-implements the rule.
    """
    tree = api_runs.run_tree(_run_dir(name))
    # A playback's directory is complete from its first second, so the file list
    # would otherwise be the answer while the grid is still asking the question.
    tree["files"] = app.state.playback.visible(name, tree.get("files") or [])
    return tree


@app.get("/api/runs/{name}/file")
def file(name: str, path: str) -> dict:
    """One file, as text. The path is resolved inside the run directory and
    nowhere else — a console is not a file browser."""
    root = _run_dir(name).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, f"no file {path!r} in this run")
    return {"path": path, "text": target.read_text(encoding="utf-8",
                                                   errors="replace")}


def _reference_root(name: str) -> Path:
    """The corpus this run was checked against, from its own run.json.

    Only a run given ground truth has one; anything else is a 404. The path is
    read back rather than recomputed, so the console shows the corpus the run
    was actually scored against, not whatever the config points at now.
    """
    meta = _run_dir(name) / "run.json"
    try:
        gt = json.loads(meta.read_text(encoding="utf-8")).get("ground_truth")
    except (OSError, ValueError):
        gt = None
    if not gt:
        raise HTTPException(
            404, f"{name} was not given a corpus to check against, so there is "
                 f"no reference to read")
    here = app.state.playback.reference_root(Path(gt).resolve())
    if here is None:
        # Playing back with no corpus beside the runs. The recording is whole
        # without it, and the page turns this into "no reference offered".
        raise HTTPException(
            404, f"{name} was scored against a corpus that is not here; put "
                 f"one beside the runs, or point paths.lib_root at it")
    return here


@app.get("/api/runs/{name}/reference/tree")
def reference_tree(name: str) -> dict:
    """What the corpus holds for this protocol, as relative paths. Only the
    files that exist, so a protocol bringing no ProVerif model or no recorded
    attack has fewer entries instead of a dead link.
    """
    root = _reference_root(name)
    return {"root": str(root),
            "files": sorted(str(f.relative_to(root)) for f in root.rglob("*")
                            if f.is_file())}


@app.get("/api/runs/{name}/reference/file")
def reference_file(name: str, path: str) -> dict:
    """One corpus file, as text. The same shape and confinement as the run's own
    file route, one directory over: resolved inside this run's ground truth and
    nowhere else. Reading is all it does.
    """
    root = _reference_root(name)
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, f"no file {path!r} in this run's corpus")
    return {"path": path, "text": target.read_text(encoding="utf-8",
                                                   errors="replace")}


@app.get("/api/runs/{name}/review")
def review(name: str) -> dict:
    """Whether this run is still open for review, and every reading filed on it.

    The readings come off the ledger rather than a file: they are added after
    the run and a run directory is written once. Returned newest first, because
    the newest reading for a cell is the one that counts.
    """
    run_dir = _run_dir(name)
    return {"review": api_runs.review(run_dir),
            "findings": api_runs.findings(run_dir)}


@app.get("/api/runs/{name}/eval")
def evaluation(name: str) -> dict:
    """What this run's products scored against the corpus.

    The summary carries numbers and principals' alpha-renaming pairs; the
    per-product files hold the missed corpus entries and stay private. The
    renaming pairs go out because they explain which names the score treated as
    one formal value. Empty when the run had no corpus.
    """
    p = _run_dir(name) / "eval" / "summary.json"
    if not p.is_file():
        return {"products": {}}
    out = json.loads(p.read_text(encoding="utf-8"))
    out["products"] = app.state.playback.scored(name, out.get("products") or {})
    return out


_IDLE = {"queue": [], "summarizing": False, "queue_error": ""}


@app.get("/api/runs/{name}/attacks")
def attacks(name: str) -> dict:
    """The run's attack reproductions: every false cell and what was decided
    for it, where each reproduced cell's script and explanation are, the
    newest summary, and what the queue of requested cells holds. Answered by
    api/attacks.py off the run's own files.

    A playback shows them once it has reached the step, like the file tree.
    """
    out = api_attacks.index(_run_dir(name))
    step = out["step"]
    if step and not app.state.playback.visible(name, [step["dir"]]):
        return {"step": None, "cells": [], "summary": None, **_IDLE}
    queue = app.state.reproductions.get(name)
    return {**out, **(queue.state() if queue is not None else _IDLE)}


def _reproductions(name: str) -> api_attacks.Reproductions:
    """This run's queue of requested reproductions, created on first use.

    Refused while playing back (a request writes into the recorded run) and
    while the run itself is in flight: its own attack step has not decided
    which cells wait. A config that cannot reach the model is a 400.
    """
    app.state.playback.refuse("reproducing an attack")
    run_dir = _run_dir(name)
    entry = app.state.registry.get(name)
    if entry is not None and entry.running:
        raise HTTPException(
            409, f"run {name!r} is still in flight; its own attack step has "
                 f"not finished. Ask again once the run has ended")
    queue = app.state.reproductions.get(name)
    if queue is None:
        try:
            host = _host(name)
        except MissingConfigError as e:
            raise HTTPException(400, f"cannot reproduce: {e}") from None
        queue = app.state.reproductions[name] = api_attacks.Reproductions(
            run_dir, host)
    return queue


def _cells_of(body: dict) -> list[tuple[str, str]]:
    cells = body.get("cells")
    if not isinstance(cells, list) or not cells:
        raise HTTPException(
            400, "cells is required: a non-empty list of {scenario, goal}")
    out = []
    for c in cells:
        if not (isinstance(c, dict) and isinstance(c.get("scenario"), str)
                and isinstance(c.get("goal"), str)
                and c["scenario"] and c["goal"]):
            raise HTTPException(
                400, f"each cell is {{scenario, goal}}, both non-empty strings; "
                     f"got {c!r}")
        out.append((c["scenario"], c["goal"]))
    return out


@app.post("/api/runs/{name}/attacks")
async def request_attacks(name: str, body: dict) -> dict:
    """Reproduce the attacks behind these false cells. Answers at once with
    the cells queued and the ones refused; the work carries on in the
    background and every change arrives on the event stream. Nothing the page
    asked for being possible is a 400 naming why.
    """
    cells = _cells_of(body)
    queue = _reproductions(name)
    try:
        out = queue.enqueue(cells)
    except MissingConfigError as e:
        raise HTTPException(400, f"cannot reproduce: {e}") from None
    if not out["queued"]:
        raise HTTPException(
            400, "; ".join(f"{r['scenario']}/{r['goal']}: {r['why']}"
                           for r in out["refused"]))
    return out


@app.post("/api/runs/{name}/attacks/stop")
async def stop_attacks(name: str) -> dict:
    """Empty this run's queue and stop the cell in hand; each goes back to
    waiting."""
    queue = app.state.reproductions.get(name)
    return {"stopped": await queue.stop() if queue is not None else 0}


@app.post("/api/runs/{name}/attacks/summary")
async def resummarize_attacks(name: str) -> dict:
    """Rewrite the summary over every reproduced cell, in the background;
    ``attacks_summarized`` says when it is written. A 409 while cells are
    still in the queue."""
    queue = _reproductions(name)
    try:
        queue.summarize()
    except api_attacks.QueueBusy as e:
        raise HTTPException(409, str(e)) from None
    except MissingConfigError as e:
        raise HTTPException(400, f"cannot summarise: {e}") from None
    return {"accepted": True}


@app.post("/api/runs/{name}/review")
async def set_review(name: str, body: dict) -> dict:
    """Mark this run reviewed, or open it again.

    Not the run's ``status``: what the pipeline concluded and what a person
    concluded about it are two facts, and a reader closing a run must not
    overwrite the record of how it ended.
    """
    app.state.playback.refuse("filing a reading on a run")
    run_dir = _run_dir(name)
    try:
        payload = api_runs.close_review(run_dir,
                                        (body.get("state") or "archived").strip(),
                                        body.get("note") or "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    # On the ledger too, so the record says when somebody signed this off.
    try:
        _host(name).emit(ReviewClosed(run=name, node="review", **payload))
    except MissingConfigError:
        pass                    # a run with no usable config still archives
    return payload


# ── control ──────────────────────────────────────────────────────────────────

@app.post("/api/runs/{name}/interrupt")
async def interrupt(name: str) -> dict:
    """Stop the run in flight; the reply says whether there was one to stop."""
    if app.state.playback.on:
        return {"stopped": await app.state.playback.stop(name)}
    return {"stopped": app.state.registry.interrupt(name)}


@app.post("/api/runs/{name}/approve")
def approve(name: str) -> dict:
    """Release a run waiting at an approval gate."""
    return {"released": app.state.registry.approve(name)}


# ── expert ───────────────────────────────────────────────────────────────────

#: How many run files one question may carry. Every one of them is pasted into
#: the prompt whole (up to 40k characters each), so this is a real budget: a
#: cell attaches four or five by itself.
MAX_ATTACHED = 8


def _cell_material(name: str, cell: dict) -> tuple[str, list]:
    """The files behind one cell, as a block to lead the question with.

    Attached rather than named, so the model spends no rounds rediscovering what
    the page already knows. Only what exists is sent — a cell whose query held
    has no counter-example — and the list of what went is returned so the page
    can show it. A hand-picked set of a step's products arrives in the same
    shape with no goal and no scenario, and gets a shorter head. More than
    MAX_ATTACHED files raises HTTPException(400).
    """
    run_dir = _run_dir(name)
    goal, scenario = cell.get("goal", ""), cell.get("scenario", "")
    stage = cell.get("stage") or ""
    wanted = [p for p in (cell.get("paths") or []) if isinstance(p, str)]
    if len(wanted) > MAX_ATTACHED:
        # Said, not trimmed: silently sending four of seven files would leave the
        # reader believing the model had read the other three.
        raise HTTPException(
            400, f"{len(wanted)} files attached; the ceiling is "
                 f"{MAX_ATTACHED}. Drop some — every one of them is pasted "
                 f"into the question whole.")
    blocks, attached = [], []
    for rel in wanted:
        target = (run_dir / rel).resolve()
        if not target.is_relative_to(run_dir.resolve()) or not target.is_file():
            continue
        body = target.read_text(encoding="utf-8", errors="replace")
        # A trace can be tens of kilobytes. Cut the long file rather than the
        # question, and say in the text that it was cut.
        if len(body) > 40_000:
            body = body[:40_000] + "\n… (truncated; deepen_trace re-runs it)"
        blocks.append(f"### {rel}\n```\n{body}\n```")
        attached.append(rel)
    if not blocks:
        return "", []
    where = (f"looking at **{goal} @ {scenario}**, at the **{stage}** stage of "
             f"how its model was built" if goal and scenario else
             "reading this run\u2019s files")
    head = (f"The reader is {where}. These are the files they have on screen — "
            f"you do not need to go and find them:\n\n")
    return head + "\n\n".join(blocks) + "\n\n---\n\nTheir question:\n\n", attached


@app.post("/api/runs/{name}/chat")
async def chat(name: str, body: dict) -> dict:
    """Ask the expert. Returns as soon as the turn is scheduled, not when it
    answers: a question takes minutes, and the rounds, the tool calls and the
    reply itself all arrive on the event stream. A second question while one is
    in flight is a 409.
    """
    app.state.playback.refuse("asking the expert")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "empty message")
    host = _host(name)
    if host.turn is not None and not host.turn.done():
        raise HTTPException(409, "a question is already in flight; stop it first")
    # A question asked from a cell carries that cell's material with it: the
    # reader was looking at the code when they asked, and the cell plus the open
    # stage say exactly which files those were.
    cell = body.get("cell") or {}
    material, attached = _cell_material(name, cell) if cell else ("", [])
    host.emit(ExpertAsked(run=name, node="expert", text=text,
                           goal=cell.get("goal", ""),
                           scenario=cell.get("scenario", ""),
                           stage=cell.get("stage", ""), attached=attached))

    async def turn() -> None:
        try:
            reply = await host.chat(material + text if material else text)
        except asyncio.CancelledError:
            # Said on the ledger like any other outcome, so the conversation
            # still reads as one after a reload rather than trailing off.
            host.emit(ExpertReplied(run=name, node="expert",
                                     text="[stopped] the question was stopped "
                                          "before it was answered."))
            raise
        except Exception as e:                              # noqa: BLE001
            reply = f"[failed] {type(e).__name__}: {e}"
        # The answer is an event like everything else, so a browser that
        # reconnected mid-turn still receives it.
        host.emit(ExpertReplied(run=name, node="expert", text=reply))

    host.turn = asyncio.get_running_loop().create_task(turn())
    return {"accepted": True}


@app.post("/api/runs/{name}/chat/stop")
async def stop_chat(name: str) -> dict:
    """Stop the question in flight.

    The expert's round and reading counts are unbounded by default, so the
    person who asked is what guarantees a turn ends. Cancelling unwinds the
    agent loop; the session's transcript keeps what it had reached and the next
    question resumes from there.
    """
    host = _host(name)
    task = getattr(host, "turn", None)
    if task is None or task.done():
        return {"stopped": False}
    task.cancel()
    return {"stopped": True}


@app.get("/api/runs/{name}/pending")
async def pending(name: str) -> dict:
    """The fix plan waiting on a decision, in full. The event carries only a
    digest — short enough for a ledger — and the card needs the whole thing."""
    host = _host(name)
    return {"plan": getattr(host, "plan", None)}


@app.post("/api/runs/{name}/pending")
async def decide(name: str, body: dict) -> dict:
    """Answer the waiting fix plan: the body's ``execute`` flag resolves the
    future ``_WebHost.confirm`` is blocked on."""
    host = _host(name)
    fut = getattr(host, "pending", None)
    if fut is None or fut.done():
        return {"answered": False}
    fut.set_result(bool(body.get("execute")))
    return {"answered": True}


# ── the page ─────────────────────────────────────────────────────────────────

class _Revalidated(StaticFiles):
    """StaticFiles that sends ``no-cache``: the page is served from source with
    no build step, so a browser holding a cached copy without asking holds a
    version that no longer exists. ``no-cache`` means "ask first", not "do not
    store" — the etag StaticFiles already sends still answers most requests with
    a 304."""

    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["cache-control"] = "no-cache"
        return resp


app.mount("/static", _Revalidated(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    """The console page itself, revalidated like the rest of the static tree."""
    return FileResponse(STATIC / "index.html",
                        headers={"cache-control": "no-cache"})


def vocabulary_corpus_roots() -> list[Path]:
    """The corpus the vocabulary page measures protocol usage in: the configured
    root, which does not have to exist — the panel measures what it finds, and a
    checkout without a corpus still renders the vocabulary itself. A named
    function so a test can render the same page the route does.
    """
    return [api_settings.corpus(app.state.config_path)["lib"]]


@app.get("/vocabulary", response_class=HTMLResponse)
def vocabulary() -> HTMLResponse:
    """The assumption vocabulary as one page: the axes, their subtypes, the
    partial orders, the requires_world edges and the conflicts, with a panel
    naming which protocols each subtype was modelled in, measured off the
    configured corpora rather than declared on the classes.

    The same renderer the CLI writes to a file (``orrery kb <path>.html``).
    Rendered per request; a cached copy would go stale against the declarations
    it exists to show. A page of its own, unrelated to any run, so opening it
    leaves the console's live stream untouched."""
    from orrery.api.kb_graph import render_kb_html
    return HTMLResponse(
        render_kb_html(theme="dark", corpus_roots=vocabulary_corpus_roots()),
        headers={"cache-control": "no-cache"})
