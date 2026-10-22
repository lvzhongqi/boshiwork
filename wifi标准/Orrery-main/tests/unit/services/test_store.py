"""Tests for store: the atomic write, the limit of truncation recovery (a
broken middle line raises), the layout paths resolved through the stage index,
and listing or deleting the runs already on disk."""

import pytest
import yaml

from orrery.services.store.atomic import (
    append_line, read_jsonl_tolerant, write_json, write_text,
)
from orrery.services.store.layout import RunLayout
from orrery.services.store.runs import delete_run, list_runs, point_latest


def test_run_config_is_written_with_api_keys_redacted(tmp_path):
    lay = RunLayout(tmp_path, "NSPK", "run1")
    config = {
        "llm": {
            "api_key": "live-key",
            "url": "https://live-relay.example/v1",
            "profiles": {
                "one": {"apiKey": "profile-key", "model": "m1",
                        "url": "https://relay-one.example/v1"},
                "two": {"api-key": "other-key", "model": "m2",
                        "url": "https://relay-two.example/v1"},
                "three": {"apykey": "misspelled-key", "model": "m3"},
            },
        },
        "paths": {"work_root": "/runs"},
        "document": {"source_url": "https://public.example/spec"},
    }

    lay.write_config(config)

    saved = yaml.safe_load(lay.config_yaml.read_text(encoding="utf-8"))
    assert saved == {
        "llm": {
            "api_key": "********",
            "profiles": {
                "one": {"apiKey": "********", "model": "m1"},
                "two": {"api-key": "********", "model": "m2"},
                "three": {"apykey": "********", "model": "m3"},
            },
        },
        "paths": {"work_root": "/runs"},
        "document": {"source_url": "https://public.example/spec"},
    }
    assert config["llm"]["api_key"] == "live-key"
    assert config["llm"]["profiles"]["one"]["apiKey"] == "profile-key"


def test_atomic_write_and_no_partial_leftover(tmp_path):
    p = tmp_path / "a" / "output.pv"
    write_text(p, "free c: channel.\n")
    write_text(p, "free c: channel.\nprocess 0\n")     # a complete replacement
    assert p.read_text().endswith("process 0\n")
    assert list(p.parent.glob(".*")) == []              # no temporary file left


def test_jsonl_middle_bad_line_raises(tmp_path):
    p = tmp_path / "x.jsonl"
    append_line(p, '{"a": 1}')
    append_line(p, "not JSON")
    append_line(p, '{"a": 3}')
    with pytest.raises(ValueError, match="middle line"):
        read_jsonl_tolerant(p)


def _open(lay, *nodes):
    lay.run_dir.mkdir(parents=True, exist_ok=True)
    return [lay.open_node(n) for n in nodes]


def test_layout_paths_come_from_the_index_not_from_a_name(tmp_path):
    """A step's directory is a fact about this run rather than about the node
    table, so layout resolves it through the index instead of spelling it."""
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "extract_principals", "extract_flow", "build_world", "build_root")
    run = tmp_path / "NSPK" / "run1"
    assert lay.node_dir("extract_principals").name == "01_extract_principals"
    assert lay.node_transcript("extract_flow") == run / "02_extract_flow" / "transcript.jsonl"
    # products keep plain canonical names; an apply chain's result sits inside
    # the apply/ band that produced it
    assert lay.world_pv == run / "03_build_world" / "apply" / "world.pv"
    assert lay.root_pv == run / "04_build_root" / "apply" / "root.pv"
    assert lay.events_path == run / "events.jsonl"


def test_asking_for_a_step_that_has_no_current_work_is_loud(tmp_path):
    """Answering with a path would have the caller create a directory nothing
    recorded, whose place in the run's timeline is lost, so it raises."""
    from orrery.services.store.layout import StageMissing
    lay = RunLayout(tmp_path, "NSPK", "run1")
    lay.run_dir.mkdir(parents=True)
    with pytest.raises(StageMissing, match="never ran"):
        lay.node_dir("extract_flow")
    assert lay.find_node_dir("extract_flow") is None


def test_going_back_appends_and_the_earlier_attempt_stays_put(tmp_path):
    """Nothing is renamed, so one `ls` reads as the run's own timeline and a
    backtrack shows up as a later directory bearing an earlier step's name."""
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "extract_principals", "extract_flow")
    write_text(lay.node_dir("extract_principals") / "principals.json", "v1")

    again = lay.open_node("extract_principals", cause="gap", by="extract_flow")
    assert again.name == "03_extract_principals"
    assert (lay.run_dir / "01_extract_principals" / "principals.json"
            ).read_text() == "v1"                       # untouched
    assert lay.node_dir("extract_principals") == again  # and no longer current
    assert sorted(p.name for p in lay.run_dir.iterdir() if p.is_dir()) == [
        "01_extract_principals", "02_extract_flow", "03_extract_principals"]


def test_a_resumed_step_carries_its_session_but_not_its_rounds(tmp_path):
    """An accepted gap asks a step to reconsider one thing, so its session
    carries over. The rounds stay with the attempt that wrote them, which lets
    the new directory's slot band start at 00."""
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "extract_flow")
    first = lay.node_dir("extract_flow")
    write_text(first / "transcript.jsonl", '{"t": "user"}')
    write_text(first / "rounds" / "00_prompt.md", "asked")

    second = lay.open_node("extract_flow", cause="gap", by="claims", resume=True)
    assert (second / "transcript.jsonl").read_text() == '{"t": "user"}'
    assert not (second / "rounds").exists()


def test_facts_reach_the_attempt_after_the_one_they_were_filed_for(tmp_path):
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "extract_flow")
    write_text(lay.node_dir("extract_flow") / "facts.jsonl", '{"text": "fix it"}')
    second = lay.open_node("extract_flow", cause="fix", by="user")
    assert (second / "facts.jsonl").read_text() == '{"text": "fix it"}'


# a refused reply is kept, never replayed, and still counted


def test_rejected_reply_is_recorded_but_not_replayed(tmp_path):
    from orrery.infra.llm.client import ChatResponse, Role, TokenUsage
    from orrery.services.transcript.reader import TranscriptReader
    from orrery.services.transcript.writer import TranscriptWriter

    p = tmp_path / "transcript.jsonl"
    w = TranscriptWriter(p)
    w.system("rules")
    w.user("do the thing")
    w.rejected("Looking at this scenario, I need to...", "no JSON object",
               TokenUsage(input_tokens=100, output_tokens=40))
    w.assistant(ChatResponse(content='{"ok": true}',
                             usage=TokenUsage(input_tokens=120, output_tokens=30)))

    r = TranscriptReader(p)
    roles = [m.role for m in r.messages()]
    assert roles == [Role.SYSTEM, Role.USER, Role.ASSISTANT]   # not replayed
    assert any(e["t"] == "rejected" and "Looking at this" in e["content"]
               for e in r.entries())                           # but on the record
    assert r.usage_total() == (220, 70)                        # and billed too


def test_every_session_is_named_transcript_jsonl(tmp_path):
    """Every rule about sessions keys on the exact file name: the expert's
    discovery scans for it, the artifact fence refuses it, resume reads it. A
    session under any other name falls silently out of all three."""
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "scenarios")
    home = lay.open_scenario("s1")
    point = lay.open_apply_point(home, "ltk_reveal_A")
    assert point.name == "01_ltk_reveal_A"
    encode = lay.apply_transcript(home, "ltk_reveal_A")
    assert encode.name == "transcript.jsonl"
    assert encode.parent == point


def test_an_apply_point_is_named_by_its_assumption_not_its_subtype(tmp_path):
    """Otway-Rees assumes lkr_from_start of both A and B: two points, one
    subtype. The number is execution order, so the name carries the identity."""
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "scenarios")
    home = lay.open_scenario("s1")
    a = lay.open_apply_point(home, "ltk_reveal_A")
    b = lay.open_apply_point(home, "ltk_reveal_B")
    assert (a.name, b.name) == ("01_ltk_reveal_A", "02_ltk_reveal_B")
    # re-working the first lands after the second, which is what makes the
    # second stale without anything having to say so
    again = lay.open_apply_point(home, "ltk_reveal_A", cause="fix", by="user")
    assert again.name == "03_ltk_reveal_A"
    assert lay.find_apply_point_dir(home, "ltk_reveal_B") is None


def test_parallel_siblings_share_a_generation(tmp_path):
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "scenarios")
    assert lay.open_scenario("baseline").name == "00_baseline"
    assert lay.open_scenario("lowe").name == "00_lowe"
    assert lay.open_scenario("baseline", cause="fix", by="user").name == "01_baseline"
    assert lay.find_scenario_dir("lowe").name == "00_lowe"   # untouched by its sibling


def test_final_answer_paths_come_from_layout(tmp_path):
    lay = RunLayout(tmp_path, "NSPK", "run1")
    _open(lay, "aggregate", "cross_check")
    run = tmp_path / "NSPK" / "run1"
    assert lay.results_json == run / "01_aggregate" / "results.json"
    assert lay.cases_results_json == run / "01_aggregate" / "cases_results.json"
    # the evaluation report is cross_check's own artifact, resolved through the
    # index like every other step's product
    assert lay.cross_check_json == run / "02_cross_check" / "cross_check.json"


def _run_on_disk(root, protocol, name, *, status="ok", started="",
                 verdicts=None, acc=None):
    """One run directory as the pipeline would have left it."""
    d = root / protocol / name
    d.mkdir(parents=True)
    write_json(d / "run.json",
               {"run_name": name, "status": status, "started": started})
    lay = RunLayout(root, protocol, name)
    if verdicts is not None:
        # where the pipeline puts them: the aggregate step's own directory,
        # found through the index
        agg = lay.open_node("aggregate")
        write_json(agg / "results.json",
                   {"results": [{"id": f"g{i}", "verdict": v}
                                for i, v in enumerate(verdicts)]})
    if acc is not None:
        # same rule: cross_check's own directory, through the index
        cc = lay.open_node("cross_check")
        write_json(cc / "cross_check.json", {"acc": acc})
    return d


def test_list_runs_summarizes_and_orders(tmp_path):
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01", status="check_failed",
                 started="2026-08-18T10:00:00",
                 verdicts=["true", "false", "false"], acc=0.5)
    _run_on_disk(root, "NSSK", "NSSK01", status="ok",
                 started="2026-08-18T12:00:00", verdicts=["true"])

    rows = list_runs(root)
    assert [r.name for r in rows] == ["NSSK01", "NSPK01"]      # newest first
    nspk = rows[1]
    assert nspk.protocol == "NSPK" and nspk.status == "check_failed"
    assert nspk.verdicts == {"true": 1, "false": 2} and nspk.acc == 0.5
    assert rows[0].verdicts == {"true": 1} and rows[0].acc is None


def test_list_runs_skips_what_is_not_a_run(tmp_path):
    """A run with no run.json is not a run; `latest` points at one that is
    already listed, so following it would report the same run twice."""
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01", started="2026-08-18T10:00:00")
    (root / "NSPK" / "scratch").mkdir()                 # no run.json
    point_latest(root, "NSPK", "NSPK01")

    assert [r.name for r in list_runs(root)] == ["NSPK01"]


def test_list_runs_tolerates_an_older_or_broken_run(tmp_path):
    """Older runs lack `started`, and a killed one can leave half a JSON file;
    neither takes the listing down."""
    root = tmp_path / "wr"
    d = root / "NSPK" / "NSPK01"
    d.mkdir(parents=True)
    write_json(d / "run.json", {"status": "ok"})        # no run_name, no started
    (d / "results.json").write_text('{"results": [', encoding="utf-8")

    (row,) = list_runs(root)
    assert row.name == "NSPK01" and row.started == "" and row.verdicts == {}


def test_list_runs_on_an_empty_root(tmp_path):
    assert list_runs(tmp_path / "nothing-here") == []


# deleting a run: the one thing in the store that destroys something


def test_delete_removes_the_run_and_repoints_latest(tmp_path):
    """`latest` is a symlink into the tree, so deleting what it names would
    leave it dangling; delete_run repoints it at a surviving run."""
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01", started="2026-01-01")
    _run_on_disk(root, "NSPK", "NSPK02", started="2026-01-02")
    point_latest(root, "NSPK", "NSPK02")

    removed = delete_run(root, "NSPK", "NSPK02")
    assert removed == ["NSPK/NSPK02"]
    assert not (root / "NSPK" / "NSPK02").exists()
    assert (root / "NSPK" / "NSPK01").is_dir()          # the sibling is untouched
    assert (root / "NSPK" / "latest").resolve() == (root / "NSPK" / "NSPK01").resolve()


def test_deleting_a_run_latest_does_not_name_leaves_the_pointer_alone(tmp_path):
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01")
    _run_on_disk(root, "NSPK", "NSPK02")
    point_latest(root, "NSPK", "NSPK02")

    delete_run(root, "NSPK", "NSPK01")
    assert (root / "NSPK" / "latest").resolve() == (root / "NSPK" / "NSPK02").resolve()


def test_the_last_run_takes_its_protocol_with_it(tmp_path):
    """An empty protocol directory has nothing left to list, and the pointer
    left in it would name nothing."""
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01")
    point_latest(root, "NSPK", "NSPK01")

    removed = delete_run(root, "NSPK", "NSPK01")
    assert not (root / "NSPK").exists()
    assert "NSPK" in removed
    assert list_runs(root) == []


def test_the_stowed_ground_truth_is_not_a_run(tmp_path):
    """A protocol directory can hold `_ground_truth`, the answers results are
    checked against. Listed as a run it would be a row with no verdicts, and
    taken as the newest run it would become what `latest` names."""
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01", started="2026-01-01")
    _run_on_disk(root, "NSPK", "NSPK02", started="2026-01-02")
    point_latest(root, "NSPK", "NSPK02")
    # `_` sorts after the capitals a protocol id starts with, so a walk that
    # forgets it picks it as the newest run
    (root / "NSPK" / "_ground_truth" / "results").mkdir(parents=True)

    assert [r.name for r in list_runs(root)] == ["NSPK02", "NSPK01"]
    delete_run(root, "NSPK", "NSPK02")
    assert (root / "NSPK" / "latest").resolve() == (root / "NSPK" / "NSPK01").resolve()


def test_the_last_run_leaves_a_stowed_ground_truth_standing(tmp_path):
    """Deleting the last run leaves `_ground_truth` alone, so the protocol
    directory stays for as long as it holds one."""
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01")
    point_latest(root, "NSPK", "NSPK01")
    (root / "NSPK" / "_ground_truth" / "claims").mkdir(parents=True)

    removed = delete_run(root, "NSPK", "NSPK01")
    assert removed == ["NSPK/NSPK01", "NSPK/latest"]        # the protocol is not in it
    assert (root / "NSPK" / "_ground_truth" / "claims").is_dir()
    assert not (root / "NSPK" / "latest").exists()
    assert list_runs(root) == []


def test_delete_refuses_the_pointer_and_anything_outside_the_root(tmp_path):
    root = tmp_path / "wr"
    _run_on_disk(root, "NSPK", "NSPK01")
    (tmp_path / "corpus").mkdir()
    with pytest.raises(ValueError, match="pointer to the newest run"):
        delete_run(root, "NSPK", "latest")
    with pytest.raises(ValueError, match="not a run inside"):
        delete_run(root, "NSPK", "../../corpus")
    # "." resolves to the protocol directory itself: every run and the stowed
    # ground truth would go with it
    with pytest.raises(ValueError):
        delete_run(root, "NSPK", ".")
    # a directory in the right place that is not a run is not removed either
    (root / "NSPK" / "notes").mkdir()
    with pytest.raises(ValueError, match="not a run"):
        delete_run(root, "NSPK", "notes")
    assert (root / "NSPK" / "notes").is_dir()
    with pytest.raises(FileNotFoundError):
        delete_run(root, "NSPK", "NSPK99")
    assert (tmp_path / "corpus").is_dir()               # nothing outside was touched
    assert (root / "NSPK" / "NSPK01").is_dir()


def test_append_line_cuts_a_half_line_that_ends_mid_character(tmp_path):
    """The kill this repair exists for, on a ledger written with
    ensure_ascii=False: the surviving half line ends inside a multi-byte
    character, so the probe for the last newline has to read bytes, not text."""
    p = tmp_path / "events.jsonl"
    # cut inside the last character's three bytes, so the tail does not decode
    p.write_bytes('{"seq": 0}\n{"a": "中文'.encode("utf-8")[:-1])
    # readable as it stands: the damaged tail is dropped, not decoded first
    assert read_jsonl_tolerant(p) == [{"seq": 0}]
    append_line(p, '{"b": 1}')
    assert p.read_text(encoding="utf-8") == '{"seq": 0}\n{"b": 1}\n'
    assert read_jsonl_tolerant(p) == [{"seq": 0}, {"b": 1}]


def test_a_line_separator_inside_a_record_is_not_a_line_break(tmp_path):
    """json.dumps(ensure_ascii=False) leaves U+2028, U+2029 and U+0085 raw
    inside a string, and str.splitlines breaks on all three. A model reply
    carrying one would then read as a line the writer never wrote, and the
    whole ledger as edited from outside. Only the newline the writer writes
    is a record boundary."""
    import json
    p = tmp_path / "transcript.jsonl"
    rows = [{"t": "user", "content": "a\u2028b\u2029c\x85d"}, {"t": "user", "content": "e"}]
    for row in rows:
        append_line(p, json.dumps(row, ensure_ascii=False))
    assert read_jsonl_tolerant(p) == rows
    from orrery.services.store.atomic import read_jsonl_records
    assert [r for _, r in read_jsonl_records(p, what="a test file")] == rows


def test_appending_after_a_kill_leaves_a_file_that_still_reads(tmp_path):
    """Re-entering a run appends to the ledger the kill damaged. The half line
    has to go: kept, it stops being the last line and the tolerant reader turns
    it into a hard "this file was edited externally" — which would brick
    events.jsonl for every later read, EventBus.bind included."""
    p = tmp_path / "events.jsonl"
    p.write_text('{"seq": 0}\n{"seq": 1, "half"', encoding="utf-8")
    append_line(p, '{"seq": 2}')
    assert read_jsonl_tolerant(p) == [{"seq": 0}, {"seq": 2}]



def test_a_fix_at_an_apply_point_reaches_the_goal_families(tmp_path):
    """Through the layout: the family opened on a scenario's chain stops being
    current the moment a point of that chain is opened again, and the model it
    left is no longer what inject reads back."""
    lay = RunLayout(tmp_path / "wr", "P", "r1")
    lay.run_dir.mkdir(parents=True)
    lay.open_node("scenarios")
    home = lay.open_scenario("s1")
    lay.open_apply_point(home, "k1")
    fam = lay.open_inject_family("s1", "Secrecy")
    assert lay.find_inject_family_dir("s1", "Secrecy") == fam
    lay.open_apply_point(home, "k1", cause="fix", by="user")
    assert lay.find_inject_family_dir("s1", "Secrecy") is None
    again = lay.open_inject_family("s1", "Secrecy", cause="fix", by="user")
    assert again != fam and lay.find_inject_family_dir("s1", "Secrecy") == again
