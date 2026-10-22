"""Replay a finished run's ledger onto the console's event stream.

The console folds one event stream, and a playback is a second producer on it:
nothing is written and no model is called, only ``events.jsonl`` and the session
transcripts beside it are read. ``seq`` and ``ts`` stay the recording's own —
``seq`` is the SSE ``id:`` a reconnect resumes from. ``ModelDelta`` never
reaches the ledger, so its fragments are cut back out of the transcript.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from orrery.api import settings as api_settings
from orrery.api.truth import corpus_rel
from orrery.api.reading_order import name_rank
from orrery.pipeline.config import DEFAULTS, PROJECT_ROOT
from orrery.services.store.atomic import read_jsonl_tolerant

__all__ = ["Mode", "PlaybackBus", "PlaybackSession", "build_timeline"]

_log = logging.getLogger(__name__)

#: How long a playback should take, whatever the run took. The speed-up factor
#: is worked out per run in ``build_timeline``; this is the length it aims at.
TARGET_S = 60.0

#: Upper bound on that factor, past which the steps stop being readable.
MAX_FACTOR = 60.0

#: Fragments per second of playback time, and a ceiling on how many a single
#: reply is cut into: fast enough to read as typing, short of a thousand frames.
FRAGMENT_RATE = 20.0
MAX_FRAGMENTS = 400

#: The longest a playback may show nothing happening. Each gap is capped on its
#: own, so short bursts keep their shape and only the recording's long dead waits
#: are cut; a gap a reply streamed through is measured between fragments.
GAP_CAP_S = 1.0

#: A run directory's step directories are numbered; the number is the order they
#: ran in and the name after it is the node's.
_STEP_DIR = re.compile(r"^\d+_(.+)$")


def _ts(row: dict) -> datetime:
    return datetime.fromisoformat(row["ts"])


def _rows(run_dir: Path) -> list[dict]:
    """The ledger, in the order it was written."""
    path = run_dir / "events.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist; there is nothing to play back")
    out = read_jsonl_tolerant(path)
    if not out:
        raise ValueError(f"{path} is empty; there is nothing to play back")
    return out


class _Session:
    """One agent session's replies, handed out in the order they arrived.

    A session is a directory: transcript at ``<dir>/transcript.jsonl``, prompts
    under ``<dir>/rounds/``. Replies are consumed rather than indexed, because
    the n-th ``round_started`` of a session is its n-th reply and a session
    re-entered for a repair round carries on from where it stopped.
    """

    def __init__(self, home: Path) -> None:
        self.home = home
        self._replies = self._read(home / "transcript.jsonl")
        self._at = 0
        #: Offset of the last event attributed to this session, where the next
        #: round's fragments start from.
        self.since = 0.0

    @staticmethod
    def _read(path: Path) -> list[dict]:
        if not path.is_file():
            # A session interrupted before its first reply leaves prompts and no
            # transcript; the ledger still has its rounds, they play unfragmented.
            return []
        return [entry for entry in read_jsonl_tolerant(path)
                if entry.get("t") in ("assistant", "rejected")]

    def next_reply(self) -> dict | None:
        if self._at >= len(self._replies):
            return None
        self._at += 1
        return self._replies[self._at - 1]


def _fragments(text: str, n: int) -> list[str]:
    if not text or n <= 0:
        return []
    size = max(1, -(-len(text) // n))
    return [text[i:i + size] for i in range(0, len(text), size)]


def _deltas(row: dict, since: float, until: float, reply: dict,
            factor: float) -> list[tuple[float, dict, bool]]:
    """Cut one reply back into the fragments it arrived in.

    The envelope is the round's own so the fragments land on the round's lane;
    the browser keys its live buffer off (node, scenario, unit), and a fragment
    addressed elsewhere opens a lane nobody draws. Thinking comes before the
    answer, the order they arrive and the order the fold buffers them in.
    """
    thinking = reply.get("thinking") or ""
    content = reply.get("content") or ""
    if not thinking and not content:
        return []
    window = max(0.0, until - since)
    n = max(1, min(MAX_FRAGMENTS, int(window / factor * FRAGMENT_RATE)))
    total = len(thinking) + len(content)
    n_think = round(n * len(thinking) / total) if thinking else 0
    n_think = max(1, n_think) if thinking else 0
    n_text = max(1, n - n_think) if content else 0
    parts = ([("thinking", f) for f in _fragments(thinking, n_think)]
             + [("text", f) for f in _fragments(content, n_text)])
    out = []
    for i, (kind, text) in enumerate(parts):
        # Spread across the gap the ledger records: the gap is the model call,
        # and the fragments are what filled it.
        at = since + window * (i + 0.5) / len(parts)
        out.append((at, {**row, "t": "model_delta",
                         "data": {"kind": kind, "text": text}}, False))
    return out


def build_timeline(run_dir: Path, *, target_s: float = TARGET_S
                   ) -> tuple[list[tuple[float, dict, bool]], float, float]:
    """The whole recording on one clock: ``(frames, span_s, factor)``.

    ``frames`` is ``(offset_s, row, durable)`` sorted by offset, one timeline for
    every session, so scenarios that overlapped in the recording overlap here.
    Offsets are on the playback clock — each gap divided by the run's speed-up,
    then capped at ``GAP_CAP_S`` — and ``factor`` is the speed-up that capping
    produced, the number the page puts on screen.
    """
    rows = _rows(run_dir)
    offsets = _active_offsets(rows)
    span = max(0.0, offsets[-1])
    factor = min(MAX_FACTOR, max(1.0, round(span / target_s, 1)))

    frames: list[tuple[float, dict, bool]] = []
    sessions: dict[Path, _Session] = {}
    current: dict[tuple, _Session] = {}
    for row, off in zip(rows, offsets):
        key = (row.get("node"), row.get("scenario"), row.get("unit"))
        if row["t"] == "prompt_filed":
            # `<step>/rounds/NN_prompt.md` -> the session directory. Two sessions
            # can share (node, scenario, unit), so attribution follows stream
            # order: this one is current for the key until the next prompt_filed.
            home = (run_dir / row["data"]["path"]).parent.parent
            sess = sessions.get(home)
            if sess is None:
                sess = sessions[home] = _Session(home)
            current[key] = sess
            sess.since = off
        elif row["t"] == "round_started":
            sess = current.get(key)
            if sess is not None:
                reply = sess.next_reply()
                if reply is not None:
                    frames.extend(_deltas(row, sess.since, off, reply, factor))
                sess.since = off
        frames.append((off, row, True))
    # Stable, so a round's fragments — appended before it — stay in front of the
    # round even when the gap they filled was too small to measure.
    frames.sort(key=lambda f: f[0])
    paced = _pace(frames, factor)
    played = paced[-1][0] if paced else 0.0
    return paced, span, (round(span / played, 1) if played > 0 else factor)


#: The events a run ends on; the ledger is quiet from one of these until the
#: run is started again.
_RUN_ENDS = frozenset({"run_finished", "run_failed", "interrupted"})


def _active_offsets(rows: list[dict]) -> list[float]:
    """Each row's offset in seconds, counting only the time the run was
    running: a re-entry weeks after the run ended follows straight on. A run
    stays ended until it is started again, whatever lands in between — the
    scores filed after the last step are late rows of the same run."""
    out: list[float] = []
    active, prev, ended = 0.0, _ts(rows[0]), False
    for row in rows:
        now = _ts(row)
        if not (ended and row["t"] == "run_started"):
            active += max(0.0, (now - prev).total_seconds())
        if row["t"] == "run_started":
            ended = False
        ended = ended or row["t"] in _RUN_ENDS
        prev = now
        out.append(active)
    return out


def _pace(frames: list[tuple[float, dict, bool]], factor: float,
          cap: float = GAP_CAP_S) -> list[tuple[float, dict, bool]]:
    """Recording offsets to playback offsets: each gap compressed, then capped.

    Offsets accumulate forward, since shortening one gap moves every later frame
    up by what it saved. Frames sharing an offset keep it, so a round's fragments
    stay with their round.
    """
    if not frames:
        return []
    out: list[tuple[float, dict, bool]] = []
    played, prev = 0.0, frames[0][0]
    for off, row, durable in frames:
        played += min((off - prev) / factor, cap)
        prev = off
        out.append((played, row, durable))
    return out


@dataclass(frozen=True)
class _Frame:
    """What a subscriber gets, shaped like the event the engine would have sent.

    The console's stream route reads only ``to_line()`` and ``durable`` off an
    event, so those two are the whole contract and the route needs no branch on
    who produced the frame.
    """

    row: dict
    durable: bool

    def to_line(self) -> str:
        return json.dumps(self.row, ensure_ascii=False)


class PlaybackBus:
    """``EventBus``'s shape without its ledger path or its re-stamping.

    Nothing is written, and ``ts``/``seq`` stay the recording's own, where
    ``EventBus.emit`` would overwrite them. ``seq`` is the SSE ``id:`` a
    reconnect resumes from.
    """

    def __init__(self) -> None:
        self._subs: list[Callable[[_Frame], None]] = []

    def subscribe(self, fn: Callable[[_Frame], None]) -> Callable[[], None]:
        self._subs.append(fn)

        def unsubscribe() -> None:
            if fn in self._subs:
                self._subs.remove(fn)

        return unsubscribe

    def emit(self, frame: _Frame) -> None:
        for fn in list(self._subs):
            try:
                fn(frame)
            except Exception:                               # noqa: BLE001
                # Same rule as the engine's bus: a failing watcher does not stop
                # the thing it is watching.
                _log.warning("playback subscriber failed", exc_info=True)


class PlaybackSession:
    """One run being played back, and the bus it is playing back on."""

    def __init__(self, run_dir: Path, *, target_s: float = TARGET_S) -> None:
        self.run_dir = run_dir
        self.name = run_dir.name
        self.bus = PlaybackBus()
        self.frames, self.span, self.factor = build_timeline(
            run_dir, target_s=target_s)
        #: Durable rows already sent, which a late or reconnecting reader is
        #: caught up with — ``api_runs.ledger``'s role for a real run.
        self.sent: list[dict] = []
        #: Which nodes have started, so the file tree and the corpus scores stay
        #: held to what the playback has actually reached.
        self.started: set[str] = set()
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.get_running_loop().create_task(self._drive())

    async def stop(self) -> None:
        if self.task is None or self.task.done():
            return
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def _drive(self) -> None:
        loop = asyncio.get_running_loop()
        began = loop.time()
        for off, row, durable in self.frames:
            # build_timeline already compressed and capped these, so the wait is
            # to the offset itself.
            delay = began + off - loop.time()
            if delay > 0.002:
                await asyncio.sleep(delay)
            if durable:
                self.sent.append(row)
                if row["t"] == "node_started" and row.get("node"):
                    self.started.add(row["node"])
            self.bus.emit(_Frame(row, durable))

    def history(self, since: int) -> list[dict]:
        return [r for r in self.sent if r["seq"] >= since]

    def visible(self, files: list[str]) -> list[str]:
        """The run's files, less the ones its playback has not got to yet.

        The directory is complete from the first second, so without this the
        file tree gives the answer while the grid is still asking. Judged by
        step-directory name: ``08_scenarios/...`` appears when ``scenarios``
        starts.
        """
        return [f for f in files if self._reached(f)]

    def reached_nodes(self) -> set[str]:
        return set(self.started)

    def _reached(self, rel: str) -> bool:
        m = _STEP_DIR.match(rel.split("/", 1)[0])
        return m is None or m.group(1) in self.started


def default_root() -> Path:
    """Where a fresh clone's recorded runs are: the built-in
    ``paths.playback_root``, before any config file has said otherwise.

    Off DEFAULTS rather than a second constant, so the value a clone starts on
    and the value the config declares cannot drift apart. What a running console
    actually reads is ``Mode.root``, which is the configured one.
    """
    return Path(os.path.normpath(
        PROJECT_ROOT / DEFAULTS["paths"]["playback_root"]))


def claims_shape(claims: Path) -> tuple[int, int, int]:
    """Shared with the console's launch panel (web/server.py), which sizes a
    live run by the same numbers.

    (goals, scenarios, cells) for a corpus claims file — the same three
    numbers the live launch panel shows. Zeroes when the file is missing."""
    try:
        d = json.loads(claims.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, 0, 0
    claimed = d.get("claims", []) or []
    return (len(claimed), len(d.get("scenarios", []) or []),
            sum(len(c.get("scenarios", [])) for c in claimed))


def _playable(run_dir: Path) -> bool:
    """A run with a ledger and at least one transcript beside it.

    The transcript is the load-bearing part: without it a playback has the steps
    but never shows the model speaking. What is playable is therefore a property
    of what was packed, and needs no manifest.
    """
    return ((run_dir / "run.json").is_file()
            and (run_dir / "events.jsonl").is_file()
            and any(run_dir.rglob("transcript.jsonl")))


def _meta(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Mode:
    """Whether the console is playing back, and everything that follows from it.

    Playback is the default, because a fresh clone of the published artifact has
    no API key. The switch is on the page, so the same build is also the live
    console: flipping it makes the launch panel ask for a corpus and a key.
    """

    def __init__(self, config_path: str | Path, *, on: bool = True) -> None:
        self.on = on
        #: Required with no default: an empty path resolves to ``Path(".")``,
        #: which fails deep inside the YAML loader instead of here.
        if not str(config_path):
            raise ValueError(
                "Mode needs the config file that names the recordings and the "
                "corpus")
        #: Kept as a path and re-read on use, so repointing either setting moves
        #: the launch tree or the reference pane without a restart.
        self.config_path = config_path
        self._sessions: dict[str, PlaybackSession] = {}

    @property
    def root(self) -> Path:
        """The tree of recorded runs, read from ``paths.playback_root``.

        A setting rather than a constant, because the seven recordings a clone
        ships are a sample: the whole set is a separate download, and pointing
        at it is one line of config or one box in the launch panel. Re-read on
        use for the same reason ``corpus`` is — the panel writes the box back to
        the config, and the run routes must see the new tree without a restart.
        """
        return api_settings.playback_root(self.config_path)

    def describe(self) -> dict:
        root = self.root
        return {"on": self.on, "root": str(root),
                "root_exists": root.is_dir(),
                "runs": [{"name": s.name, "factor": s.factor,
                          "span": round(s.span, 1), "running": s.running}
                         for s in self._sessions.values()]}

    async def set(self, on: bool) -> dict:
        """Switch modes and report the new state. Leaving playback stops every
        session, which would otherwise keep pushing recorded events at a page
        now watching a real run."""
        if not on:
            for s in list(self._sessions.values()):
                await s.stop()
            self._sessions.clear()
        self.on = bool(on)
        return self.describe()

    def session(self, name: str) -> PlaybackSession | None:
        return self._sessions.get(name) if self.on else None

    def refuse(self, what: str) -> None:
        """Every route that writes calls this first; raises PermissionError in
        playback mode.

        A playback's run directory is the recorded run's own directory, so
        deleting it, re-entering it or filing a reading on it would edit the
        record the playback exists to show.
        """
        if self.on:
            raise PermissionError(
                f"the console is in playback mode, so {what} is not available; "
                f"switch to live mode to work on real runs")

    @property
    def corpus(self) -> Path:
        """Where the protocol corpus is, read from the console's own setting.

        The published artifact puts the corpus beside the runs, which is what
        ``paths.lib_root`` defaults to, so nothing has to be configured.
        """
        return api_settings.corpus(self.config_path)["lib"]

    def reference_root(self, recorded: Path) -> Path | None:
        """A run's ground truth, re-anchored on the corpus that is actually here.

        run.json records an absolute path on the machine that produced the run;
        the portable part is the tail after the corpus name. ``None`` when the
        corpus is not beside the runs, which is not a fault — the runs play back
        whole without it. Live mode returns ``recorded`` unchanged.
        """
        if not self.on:
            return recorded
        rel = corpus_rel(recorded)
        if not rel:
            return None
        here = self.corpus / rel
        return here if here.is_dir() else None

    def protocols(self, root: str | None = None) -> dict:
        """What can be played back under a run root, in the launch panel's shape.

        One row per protocol, not per run: a reader picks a protocol and presses
        start, as in live mode, and the newest run packed with its transcripts is
        the one that plays. Raises FileNotFoundError if ``root`` is given and is
        not a directory.
        """
        base = Path(root).expanduser().resolve() if root else self.root
        if root and not base.is_dir():
            raise FileNotFoundError(f"not a directory: {base}")
        out = []
        for proto in sorted(p for p in (base.iterdir() if base.is_dir() else ())
                            if p.is_dir() and not p.name.startswith("_")):
            runs = sorted((r for r in proto.iterdir()
                           if r.is_dir() and _playable(r)),
                          key=lambda r: _meta(r).get("started") or "")
            if not runs:
                continue
            meta = _meta(runs[-1])
            recorded = Path(meta.get("ground_truth") or "")
            # None when the corpus is not beside the runs. The row still lists,
            # since the recording is what makes a protocol playable.
            gt = self.reference_root(recorded)
            goals, scenarios, cells = (
                claims_shape(gt / "claims" / "claims.json") if gt else (0, 0, 0))
            src = (gt / "source") if gt else None
            out.append({
                # Corpus-relative, as in the live panel: where in the corpus this
                # protocol sits, which the directory name alone does not say.
                "dir": corpus_rel(recorded) or proto.name, "abs": str(proto),
                # protocol_id, not protocol: a sub-protocol's `protocol` is its
                # parent's name, so two rows of one standard would be identical.
                "name": meta.get("protocol_id") or proto.name,
                "name_from": "declared",
                "version": meta.get("version"),
                "subprotocols": [],
                "ground_truth": gt is not None,
                "goals": goals, "scenarios": scenarios, "cells": cells,
                "doc": (sum(f.stat().st_size for f in src.rglob("*")
                            if f.is_file()) if src and src.is_dir() else 0),
                # Extra over the live panel's rows; the template ignores keys it
                # does not name.
                "run": runs[-1].name,
            })
        # The corpus's reading order rather than the directory's, from
        # api/reading_order.py, which the live launch panel and the vocabulary
        # page already use.
        return {"root": str(base),
                "protocols": sorted(out, key=lambda e: name_rank(e["dir"]))}

    async def start(self, body: dict) -> dict:
        """Begin a playback, and answer with the run name the page navigates to.

        ``body`` needs ``protocol_dir``. The reply has a real launch's shape,
        since the page has nowhere to go until it knows the name. Raises if the
        directory is missing or holds no recording.
        """
        directory = (body.get("protocol_dir") or "").strip()
        if not directory:
            raise ValueError("protocol_dir is required to pick what to play back")
        proto = Path(directory)
        runs = sorted((r for r in (proto.iterdir() if proto.is_dir() else ())
                       if r.is_dir() and _playable(r)),
                      key=lambda r: _meta(r).get("started") or "")
        if not runs:
            raise FileNotFoundError(
                f"nothing under {proto} was packed with its transcripts, so "
                f"there is no recording to play back")
        run_dir = runs[-1]
        # Starting the same one twice restarts it: two producers under one name
        # would interleave and the page would fold both.
        if (old := self._sessions.pop(run_dir.name, None)) is not None:
            await old.stop()
        session = PlaybackSession(run_dir)
        session.start()
        self._sessions[run_dir.name] = session
        return {"name": run_dir.name, "factor": session.factor}

    async def stop(self, name: str) -> bool:
        session = self._sessions.get(name)
        if session is None or not session.running:
            return False
        await session.stop()
        return True

    def visible(self, name: str, files: list[str]) -> list[str]:
        session = self.session(name)
        return files if session is None else session.visible(files)

    def scored(self, name: str, products: dict) -> dict:
        """The corpus scores, less the steps the playback has not reached.

        Same reason as the file tree: a run one step in should not already wear
        the badges it earns at the end.
        """
        session = self.session(name)
        if session is None:
            return products
        # Keyed by the node's own name (eval/summary.json), which is what
        # node_started carries — no directory numbering in between.
        reached = session.reached_nodes()
        return {k: v for k, v in products.items() if k in reached}
