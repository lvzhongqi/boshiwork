"""Logging setup: who installs handlers, and what a run leaves in run.log."""

import asyncio
import io
import logging

import pytest

from orrery.nodes.base import Node
from orrery.pipeline.main import Run
from orrery.services.logs import LIB_NAME, setup_logger, to_file
from orrery.services.store.atomic import write_text


@pytest.fixture(autouse=True)
def _restore_package_logger():
    """setup_logger turns the package logger's propagation off and never turns
    it back on, and pytest's caplog listens on the root: a test elsewhere that
    reads the package's log lines off caplog then sees nothing once this file
    has run. The logger goes back to how it was found."""
    log = logging.getLogger(LIB_NAME)
    saved = (list(log.handlers), log.level, log.propagate)
    yield
    for h in list(log.handlers):
        log.removeHandler(h)
    for h in saved[0]:
        log.addHandler(h)
    log.setLevel(saved[1])
    log.propagate = saved[2]


def _fresh(stream, level="info"):
    """setup_logger against a captured stream, so tests cannot leak handlers
    into each other."""
    return setup_logger(level, use_color=False, stream=stream)


def test_second_setup_replaces_its_own_handler(tmp_path):
    """A host running two protocols in one process calls setup twice. The
    second call takes over the output, and no line is printed twice."""
    a, b = io.StringIO(), io.StringIO()
    _fresh(a)
    _fresh(b)
    logging.getLogger(f"{LIB_NAME}.x").info("once")
    assert a.getvalue() == ""                      # the first handler is gone
    assert b.getvalue().count("once") == 1


def test_console_level_filters_but_the_file_keeps_everything(tmp_path):
    out = io.StringIO()
    _fresh(out, "info")
    log = logging.getLogger(f"{LIB_NAME}.x")
    with to_file(tmp_path / "run.log") as path:
        log.debug("fine detail")
        log.info("the skeleton")
    assert "fine detail" not in out.getvalue()
    assert "the skeleton" in out.getvalue()
    text = path.read_text(encoding="utf-8")
    assert "fine detail" in text and "the skeleton" in text


def test_to_file_appends_and_detaches(tmp_path):
    """to_file appends, because a re-entered run writes into the same file,
    and detaches on exit, so the next run in this process writes elsewhere."""
    _fresh(io.StringIO())
    log = logging.getLogger(f"{LIB_NAME}.x")
    p = tmp_path / "run.log"
    with to_file(p):
        log.info("first attempt")
    log.info("between runs")
    with to_file(p):
        log.info("second attempt")
    text = p.read_text(encoding="utf-8")
    assert "first attempt" in text and "second attempt" in text
    assert "between runs" not in text


def test_third_party_info_stays_out(tmp_path):
    """The HTTP client under every model call narrates each request at info;
    only this package's logger is turned up."""
    out = io.StringIO()
    _fresh(out, "info")
    logging.getLogger("httpx").info("HTTP Request: POST /v1/messages 200 OK")
    assert out.getvalue() == ""


# the engine's half: the run writes its own log file

class _Mem(Node):
    name = "load_document"
    always_run = True

    def is_done(self, env):
        return True

    async def run(self, env):
        pass


class _Product(Node):
    always_run = False

    def __init__(self, name):
        self.name = name

    def is_done(self, env):
        return (env.layout.node_dir(self.name) / "out.txt").exists()

    async def run(self, env):
        write_text(env.layout.node_dir(self.name) / "out.txt", "x")


def test_a_run_writes_its_own_log_beside_the_ledger(tmp_path):
    _fresh(io.StringIO())
    cfg = {"llm": {"backend": "stub",
                   "profiles": {"stub": {"api_key": "k", "model": "x"}}},
           "proverif": {"executable": "/bin/true"},
           "paths": {"work_root": str(tmp_path / "wr")}}
    r = asyncio.run(Run("P", tmp_path, cfg,
                        table=[_Mem(), _Product("a")]).start())
    text = (r.run_dir / "run.log").read_text(encoding="utf-8")
    assert "▶ a" in text and "✔ a" in text          # the sentences
    assert '"t": "node_started"' in text            # and the raw event under them
    # the log is a projection of the ledger: every event has a line in both
    events = (r.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert text.count("| DEBUG  | event ") == len(events)
