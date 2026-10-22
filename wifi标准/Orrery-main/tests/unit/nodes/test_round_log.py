"""RoundLog's naming: the slot number leads each file name so a directory
listing reads as the order things happened.

Everything lands in rounds/ beside the session, leaving the step's own
directory to hold only the step's product."""

from orrery.nodes.base import RoundLog
from orrery.services.transcript.writer import TranscriptWriter


def test_every_round_is_its_prompt_then_its_files(tmp_path):
    """Two writers share one slot band: RoundLog writes the round files and the
    agent loop writes the prompt that opens the next round. Each round reads as
    the prompt first, then what that round produced."""
    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    w.prompt(tools=[], system="rules", user="do it")
    w.user("do it")
    log = RoundLog(tmp_path)
    log.begin("round one")
    log.stem("typecheck").with_suffix(".pv").write_text("ran", encoding="utf-8")
    log.finish(["still broken"])
    w.round_prompt("still broken: fix the type of x")   # opens round 2
    log.begin("round two")
    log.finish([])

    assert sorted(p.name for p in (tmp_path / 'rounds').iterdir()) == [
        "00_prompt.md",           # what the session was told
        "01_r1.pv",               # round 1's submission
        "02_r1_typecheck.pv",     # its first ProVerif call
        "03_r1_checks.md",        # what round 1 ended with
        "04_prompt.md",           # what the framework sent next
        "05_r2.pv",               # round 2's submission
        "06_r2_checks.md",
    ]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "rounds", "transcript.jsonl"]        # the step's own level stays clean
    later = (tmp_path / "rounds" / "04_prompt.md").read_text(encoding="utf-8")
    assert "fix the type of x" in later
    assert "rules" not in later          # the system prompt is sent once, filed once


def test_a_resumed_session_numbers_after_the_rounds_it_finds(tmp_path):
    """Two RoundLogs over one session must not renumber over each other, so the
    first slot taken is the next free one, not a fixed number. A re-worked step
    gets its own directory and starts again at 00."""
    first = RoundLog(tmp_path)
    first.begin("round one")
    first.finish(["broken"])
    again = RoundLog(tmp_path)
    again.begin("round one of the second attempt")

    assert (tmp_path / "rounds" / "01_r1.pv").read_text().strip() == "round one"
    assert (tmp_path / "rounds" / "03_r1.pv").read_text().strip() == "round one of the second attempt"


def test_the_request_is_filed_before_what_it_assembled_to(tmp_path):
    """Where the model names edits and the framework splices them, both halves
    go on the band in order: the request, then what came out of it."""
    w = TranscriptWriter(tmp_path / "transcript.jsonl")
    w.prompt(tools=[], system="rules", user="do it")
    w.user("do it")
    log = RoundLog(tmp_path)
    log.submission({"edits": [{"anchor": "process 0", "position": "before",
                               "text": "out(c, K);"}]})
    log.begin("assembled round one")
    log.finish(["still broken"])
    w.round_prompt("that anchor is not in the model")
    # round 2's request never assembles: the anchor matched nothing, so begin
    # is never reached
    log.submission({"edits": [{"anchor": "no such line", "position": "after",
                               "text": "out(c, K);"}]})

    assert sorted(p.name for p in (tmp_path / 'rounds').iterdir()) == [
        "00_prompt.md",           # what the session was told
        "01_r1_edits.json",       # what round 1 asked for
        "02_r1.pv",               # what the framework assembled from it
        "03_r1_checks.md",
        "04_prompt.md",
        "05_r2_edits.json",       # round 2 asked …
    ]                             # … and nothing followed: nothing was built


def test_a_filed_request_replays_without_a_model(tmp_path):
    """A round's assembled text is a pure function of the text it started from
    and its filed edits, so filing the request as data lets the result be
    re-derived and audited with no model in the loop."""
    import json

    from orrery.modules.pvtext.anchored import Edit, apply_edits

    base = "free c: channel.\nprocess 0\n"
    edits = [{"anchor": "process 0", "position": "before",
              "text": "free K: key [private]."}]
    log = RoundLog(tmp_path)
    log.submission({"edits": edits})
    assembled = apply_edits(base, [Edit(**e) for e in edits])
    log.begin(assembled)

    filed = json.loads((tmp_path / "rounds" / "01_r1_edits.json").read_text(encoding="utf-8"))
    replayed = apply_edits(base, [Edit(**e) for e in filed["edits"]])
    on_disk = (tmp_path / "rounds" / "02_r1.pv").read_text(encoding="utf-8")
    assert replayed.rstrip("\n") == on_disk.rstrip("\n")
