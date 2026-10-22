"""Tests for playback: a recorded run replayed so the console cannot tell it
from a live one.

The claim under test is equality with the record — every durable frame the
playback emits, in order, is a line of ``events.jsonl``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from orrery.api import playback
from orrery.web import server

ROOT = Path(__file__).resolve().parents[3]

#: A recorded run to test against. No fixture is committed — the material is a
#: whole run with its ledger and every session transcript — so the published
#: tree is used where present and these tests skip where it is not.
FIXTURE = ROOT / "tests" / "fixtures" / "recorded_run"


def _recorded() -> list[Path]:
    """Every recorded run available to test against.

    Each protocol's recording has a different shape — overlapping sessions,
    re-entered steps, replies with no displayable text — so all of them are
    used as fixture parameters rather than one.
    """
    if FIXTURE.is_dir():
        return [FIXTURE]
    root = playback.default_root()
    return [run
            for proto in sorted(p for p in (root.iterdir() if root.is_dir()
                                            else ()) if p.is_dir())
            for run in sorted(r for r in proto.iterdir() if r.is_dir())
            if playback._playable(run)]


def _ledger(run_dir: Path) -> list[dict]:
    return [json.loads(l) for l in
            (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]


@pytest.fixture(params=_recorded() or [None],
                ids=lambda p: p.name if p is not None else "none")
def run_dir(request) -> Path:
    if request.param is None:
        pytest.skip(f"no recorded run under {FIXTURE} or "
                    f"{playback.default_root()}")
    return request.param


# ── the record, unchanged ────────────────────────────────────────────────────

def test_durable_frames_are_the_ledger(run_dir: Path) -> None:
    """The durable frames are the ledger lines: same order, same seq, same ts.

    seq is the SSE ``id:`` a reconnect resumes from, so a playback that
    renumbered would hand the browser a resume point belonging to nothing.
    """
    frames, _, _ = playback.build_timeline(run_dir)
    assert [row for _, row, durable in frames if durable] == _ledger(run_dir)


def test_fragments_carry_no_seq_of_their_own(run_dir: Path) -> None:
    """A fragment borrows its round's envelope and never lands on the ledger.

    Borrowing puts it on the right lane — the browser keys its live buffer off
    (node, scenario, unit) — while taking a seq would put it on the record.
    """
    frames, _, _ = playback.build_timeline(run_dir)
    seqs = {row["seq"] for _, row, durable in frames if durable}
    for _, row, durable in frames:
        if durable:
            continue
        assert row["t"] == "model_delta"
        assert set(row["data"]) == {"kind", "text"}
        assert row["data"]["kind"] in ("thinking", "text")
        # It carries its round's seq; `_frame` writes `id:` only for a durable
        # row, so the SSE frame drops it.
        assert row["seq"] in seqs


def test_offsets_are_monotone_and_start_at_zero(run_dir: Path) -> None:
    """Offsets are the playback's own clock, so they need not end at ``span``.

    The timeline is paced rather than the recording divided by one number, so
    all this can assert is that offsets go forward and start at zero.
    """
    frames, span, _ = playback.build_timeline(run_dir)
    offsets = [off for off, _, _ in frames]
    assert offsets == sorted(offsets)
    assert offsets[0] == 0.0
    assert 0.0 < offsets[-1] <= span          # compressed, never stretched


def test_no_single_wait_is_long_enough_to_read_as_stuck(run_dir: Path) -> None:
    """No single gap in the paced timeline exceeds ``GAP_CAP_S``.

    One factor over the whole timeline keeps the recording's proportions, and
    those include minutes-long waits with nothing streaming. Asserted per gap
    rather than in aggregate: idle time spread over half-second pieces reads as
    busy, while one six-second stall reads as broken.
    """
    frames, _, _ = playback.build_timeline(run_dir)
    offsets = [off for off, _, _ in frames]
    gaps = [b - a for a, b in zip(offsets, offsets[1:])]
    assert max(gaps, default=0.0) <= playback.GAP_CAP_S + 1e-6


def test_speed_lands_the_playback_in_the_minute_it_aims_at(run_dir: Path) -> None:
    """``span / factor`` is the playback's real length, near the target minute.

    ``factor`` is derived from the paced result rather than being its input, so
    the gap capping raises it. The accepted window is wide because how much a
    run loses to the cap depends on how long its waits were.
    """
    _, span, factor = playback.build_timeline(run_dir)
    assert factor >= 1.0                      # never slower than it happened
    if span > playback.TARGET_S:
        assert 30.0 <= span / factor <= 70.0


# ── session attribution ──────────────────────────────────────────────────────

def test_each_round_speaks_its_own_session_s_words(run_dir: Path) -> None:
    """Every round's fragments come from the session that round belongs to.

    ``extract_flow``'s own session and the ``review`` session under it share
    (node, scenario, unit), so a one-pass lookup table hands one's rounds to
    the other and the words arrive on the wrong lane rather than not at all.
    Rounds with no displayable reply, replies with no recorded round, and
    replies whose text several sessions hold, are not asserted on.
    """
    frames, _, _ = playback.build_timeline(run_dir)
    # Every reply in the run indexed by its text, so a fragment can be traced
    # back to the session directory it came from. A set, not one directory: the
    # release scrubber replaces a quoted specification passage with one fixed
    # marker, so several sessions can hold byte-identical text and the index
    # would otherwise silently hand all of them to whichever sorts first.
    homes_of: dict[str, set[Path]] = {}
    for t in sorted(run_dir.rglob("transcript.jsonl")):
        for line in t.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            for field in ("thinking", "content"):
                if entry.get(field):
                    homes_of.setdefault(entry[field], set()).add(t.parent)

    glued: dict[int, dict[str, str]] = {}
    for _, row, durable in frames:
        if durable:
            continue
        buf = glued.setdefault(row["seq"], {"thinking": "", "text": ""})
        buf[row["data"]["kind"]] += row["data"]["text"]

    rounds = {row["seq"]: row for _, row, d in frames
              if d and row["t"] == "round_started"}
    spoke_from: dict[int, str] = {}
    assert glued, "no round in this run plays any text at all"
    for seq, said in glued.items():
        row = rounds[seq]
        for text in (said["thinking"], said["text"]):
            if not text:
                continue
            homes = homes_of.get(text)
            assert homes, \
                f"seq {seq} played back text that is in no transcript"
            # Text that several sessions hold names none of them, so it is
            # evidence neither way. Redacted replies are the whole of this case.
            if len(homes) > 1:
                continue
            rel = next(iter(homes)).relative_to(run_dir).as_posix()
            spoke_from[seq] = rel
            # A session ran inside the scenario its round names. The unit is
            # not checked: a unit and its session directory do not always share
            # a name, so that would test the naming, not the attribution.
            if row.get("scenario") and row["scenario"] != "root":
                assert row["scenario"] in rel, \
                    f"seq {seq} ({row['scenario']}) spoke {rel}'s words"

    # Sessions sharing a key run one after the other, so their rounds never
    # interleave. One-pass attribution gives the whole key to the last session,
    # which shows up here as a directory that is left and then returned to.
    by_key: dict[tuple, list[str]] = {}
    for seq in sorted(spoke_from):
        row = rounds[seq]
        key = (row.get("node"), row.get("scenario"), row.get("unit"))
        by_key.setdefault(key, []).append(spoke_from[seq])
    for key, seen in by_key.items():
        blocks = [d for i, d in enumerate(seen) if i == 0 or seen[i - 1] != d]
        assert len(blocks) == len(set(blocks)), \
            f"{key} left a session directory and came back to it: {seen}"



def _speaking_rounds(run_dir: Path, one_pass: bool) -> int:
    """How many rounds get words, under stream-order or one-pass attribution.

    The one-pass form builds the (node, scenario, unit) -> session table in a
    first sweep, so the last session under a key wins the whole key. It fails
    quietly: the words still arrive, from the wrong session, and only a count
    notices.
    """
    rows = playback._rows(run_dir)
    table: dict[tuple, Path] = {}
    if one_pass:
        for row in rows:
            if row["t"] == "prompt_filed":
                key = (row.get("node"), row.get("scenario"), row.get("unit"))
                table[key] = (run_dir / row["data"]["path"]).parent.parent
    sessions: dict[Path, playback._Session] = {}
    current: dict[tuple, playback._Session] = {}
    spoke = 0
    for row in rows:
        key = (row.get("node"), row.get("scenario"), row.get("unit"))
        if row["t"] == "prompt_filed":
            home = (table[key] if one_pass
                    else (run_dir / row["data"]["path"]).parent.parent)
            current[key] = sessions.setdefault(home, playback._Session(home))
        elif row["t"] == "round_started":
            session = current.get(key)
            reply = session.next_reply() if session is not None else None
            if reply and (reply.get("thinking") or reply.get("content")):
                spoke += 1
    return spoke


def test_stream_order_attribution_beats_a_lookup_table(run_dir: Path) -> None:
    """Stream-order attribution never speaks less than a one-pass table.

    ``extract_flow``'s own session and the ``review`` session under it carry the
    same (node, scenario, unit), so a one-pass table gives the review's single
    reply to the whole key and the run goes quiet where it did the most work.
    """
    assert (_speaking_rounds(run_dir, one_pass=False)
            >= _speaking_rounds(run_dir, one_pass=True))

# ── what the mode does to the read routes ────────────────────────────────────

def test_files_appear_as_their_step_is_reached(run_dir: Path) -> None:
    session = playback.PlaybackSession(run_dir)
    files = sorted(str(f.relative_to(run_dir))
                   for f in run_dir.rglob("*") if f.is_file())
    assert session.visible(files) != files          # nothing has started yet
    assert "run.json" in session.visible(files)     # the run itself always is
    session.started.add("extract_flow")
    shown = session.visible(files)
    assert any(f.startswith("02_extract_flow/") for f in shown)
    assert not any(f.startswith("08_scenarios/") for f in shown)


def test_live_mode_leaves_every_read_route_alone(run_dir: Path,
                                                 tmp_path) -> None:
    """With the switch off, every read route behaves as it does live.

    Including the reference root: a real run was scored against the corpus its
    run.json names, and a packed copy in the checkout must not replace it.
    """
    mode = playback.Mode(tmp_path / "config.yaml", on=False)
    assert mode.session(run_dir.name) is None
    assert mode.visible(run_dir.name, ["08_scenarios/x"]) == ["08_scenarios/x"]
    assert mode.scored(run_dir.name, {"aggregate": 1}) == {"aggregate": 1}
    recorded = Path("/elsewhere/VerdictBench/academic/NSPK")
    assert mode.reference_root(recorded) == recorded
    mode.refuse("deleting a run")                   # silent when off


def test_no_corpus_beside_the_runs_offers_no_reference(run_dir: Path,
                                                       tmp_path) -> None:
    """With no corpus configured, no reference root is offered.

    Nothing of the corpus is packed with the runs; the console re-anchors the
    recorded ground-truth path on whatever corpus is configured. With none
    there it answers nothing, which the page shows as a missing reference side
    rather than an error.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths:\n  lib_root: {tmp_path / 'nowhere'}\n",
                   encoding="utf-8")
    mode = playback.Mode(cfg)
    assert mode.reference_root(Path("/x/VerdictBench/academic/NSPK")) is None
    # The launch row still lists: playability comes from the recording, not
    # from the corpus the run was scored against.
    rows = mode.protocols(str(run_dir.parent.parent))["protocols"]
    assert rows and all(not r["ground_truth"] and r["goals"] == 0 for r in rows)


def test_a_corpus_beside_the_runs_resolves_by_its_tail(run_dir: Path,
                                                       tmp_path) -> None:
    """The recorded path is one machine's; the tail after the corpus name is
    everyone's, so the reference root is resolved by matching on that name."""
    lib = tmp_path / "VerdictBench"
    (lib / "academic" / "NSPK" / "claims").mkdir(parents=True)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths:\n  lib_root: {lib}\n", encoding="utf-8")
    mode = playback.Mode(cfg)
    assert (mode.reference_root(Path("/some/other/box/VerdictBench/academic/NSPK"))
            == lib / "academic" / "NSPK")
    assert mode.reference_root(Path("/a/path/with/no/corpus/name")) is None


def test_playback_mode_refuses_every_write() -> None:
    mode = playback.Mode("config.yaml")
    with pytest.raises(PermissionError):
        mode.refuse("deleting a run")


def test_starting_twice_replaces_rather_than_doubles(run_dir: Path) -> None:
    """Starting the same playback twice replaces the producer. Two producers
    under one name would interleave: the same run told twice, out of order."""
    async def go() -> None:
        mode = playback.Mode("config.yaml")
        first = await mode.start({"protocol_dir": str(run_dir.parent)})
        a = mode.session(first["name"])
        second = await mode.start({"protocol_dir": str(run_dir.parent)})
        b = mode.session(second["name"])
        assert first["name"] == second["name"]
        assert a is not b and not a.running
        await b.stop()

    asyncio.run(go())


# ── the guarantee the published artifact rests on ────────────────────────────

class _Disconnected:
    """The smallest thing the stream route asks a request for.

    The route function is driven directly rather than through a TestClient: its
    StreamingResponse generator stays open for the life of the run, so a client
    would wait for it for ever. Here it is opened, read from, and closed by
    hand, which also proves the ``finally`` unsubscribes.
    """

    headers: dict = {}

    async def is_disconnected(self) -> bool:
        return True


def _console_reads(monkeypatch, tmp_path: Path, root: Path) -> None:
    """Point the running console's playback at ``root``.

    Through a config file, because that is the only handle there is: the tree a
    playback reads is ``paths.playback_root``, and every route resolves through
    the work root cached off it.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths:\n  playback_root: {root}\n", encoding="utf-8")
    monkeypatch.setattr(server.app.state.playback, "config_path", str(cfg))
    monkeypatch.setattr(server.app.state.playback, "on", True)
    monkeypatch.setattr(server.app.state, "work_root", server._work_root())


def test_a_playback_never_builds_a_model_client(run_dir: Path, tmp_path,
                                                monkeypatch) -> None:
    """Nothing on the path from start to stream constructs an LLM client.

    ``_host`` builds a ``_WebHost``, which builds an LLM client out of the
    config. A reviewer opening the published artifact has no config to build one
    from, so ``_host`` is replaced by a raise rather than left to a
    ``try/except`` that would fail into an empty stream.
    """
    def boom(name: str):
        raise AssertionError(f"a playback asked for a host on {name}")

    monkeypatch.setattr(server, "_host", boom)
    _console_reads(monkeypatch, tmp_path, run_dir.parent.parent)

    async def go() -> None:
        started = await server.start_run({"protocol_dir": str(run_dir.parent)})
        name = started["name"]
        assert name == run_dir.name
        # A connection always arrives after the playback started speaking;
        # `history` is what catches it up, and this sleep reproduces the gap.
        await asyncio.sleep(0.2)
        response = await server.stream(name, _Disconnected())
        gen = response.body_iterator
        try:
            first = await gen.asend(None)
        finally:
            await gen.aclose()
        assert first.startswith("id: ")
        assert '"t": "run_started"' in first
        # The read routes a playback page calls, on the same monkeypatched _host.
        assert server.tree(name)["files"]
        server.evaluation(name)
        assert await server.app.state.playback.stop(name)

    asyncio.run(go())


def test_the_run_routes_read_the_configured_playback_root(
        run_dir: Path, tmp_path, monkeypatch) -> None:
    """A run root other than the built-in one is where the run routes read.

    The seven recordings a clone ships are a sample; the whole set is a separate
    download, so the tree to replay is a setting. Before it was one, the launch
    panel listed protocols from the given root and started them, and then every
    run page under them answered 404 — the routes were still reading the
    built-in root, which has never heard of those run names.
    """
    elsewhere = tmp_path / "downloaded" / "main"
    home = elsewhere / "MyProtocol" / "MYPROTO01"
    shutil.copytree(run_dir, home)
    # Renamed, protocol and run both: a run under a name the shipped root has
    # never heard of is what proves which tree was read, where a copy under its
    # own name would be found either way.
    meta = json.loads((home / "run.json").read_text(encoding="utf-8"))
    meta["run_name"] = "MYPROTO01"
    meta["protocol_id"] = meta["protocol"] = "MyProtocol"
    (home / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    _console_reads(monkeypatch, tmp_path, elsewhere)

    async def go() -> None:
        rows = server.protocols(str(elsewhere))["protocols"]
        assert [r["abs"] for r in rows] == [str(elsewhere / "MyProtocol")]
        started = await server.start_run({"protocol_dir": rows[0]["abs"]})
        assert started["name"] == "MYPROTO01"
        try:
            assert server.tree("MYPROTO01")["files"]
            assert server.evaluation("MYPROTO01")
            assert any(r["name"] == "MYPROTO01" for r in server.runs())
        finally:
            await server.app.state.playback.stop("MYPROTO01")

    asyncio.run(go())


def test_the_panel_writes_the_run_root_back_to_the_config(tmp_path) -> None:
    """The box in the launch panel is a config knob, so what a reader typed is
    still there on the next start. Stored absolute and only if it exists — an
    unreadable root would surface later as an empty list, which reads exactly
    like a root holding nothing."""
    from orrery.api import settings as api_settings

    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths: {}\n", encoding="utf-8")
    root = tmp_path / "downloaded" / "main"
    root.mkdir(parents=True)

    api_settings.store(cfg, "paths.playback_root", str(root))
    assert api_settings.playback_root(cfg) == root.resolve()
    assert playback.Mode(cfg).root == root.resolve()

    with pytest.raises(ValueError):
        api_settings.store(cfg, "paths.playback_root", str(tmp_path / "nope"))


def test_the_wait_before_a_re_entry_is_not_played() -> None:
    """A run re-entered weeks after it finished plays straight on: only the
    time it was running counts."""
    rows = [{"t": "run_started", "ts": "2026-08-26T10:00:00"},
            {"t": "run_finished", "ts": "2026-08-26T10:10:00"},
            {"t": "run_started", "ts": "2026-09-17T18:00:00"},
            {"t": "run_finished", "ts": "2026-09-17T18:01:00"}]
    assert playback._active_offsets(rows) == [0.0, 600.0, 600.0, 660.0]
    # the scores filed after a run ends do not reopen it
    late = rows[:2] + [{"t": "node_scored", "ts": "2026-08-26T10:10:30"}] + rows[2:]
    assert playback._active_offsets(late) == [0.0, 600.0, 630.0, 630.0, 690.0]
