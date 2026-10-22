"""Logging setup: the one place in this project that installs handlers.

An entry point calls ``setup_logger()`` once, which puts the console handler on
this package's logger and leaves the root at WARNING so third-party info lines
stay out. The engine then wraps a run in ``to_file(<run_dir>/run.log)``, once
``Run.start()`` has decided the run directory.

The console carries what a person watching a run needs; the file takes
everything down to DEBUG, raw event lines included, so it is a superset of the
ledger.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from pathlib import Path

LIB_NAME = "orrery"

_RESET = "\033[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[90m",       # gray
    logging.INFO: "\033[36m",        # cyan
    logging.WARNING: "\033[33m",     # yellow
    logging.ERROR: "\033[31m",       # red
    logging.CRITICAL: "\033[1;31m",
}
# Marks the handlers this module installed, so a second setup replaces its own
# and leaves handlers someone else attached alone.
_MINE = "_aif_handler"

_CONSOLE_FMT = "%(asctime)s | %(short_name)s | %(levelname)-7s| %(message)s"
# Only the file carries the call site: on the console it would almost always be
# the one line in the bus that mirrors events.
_FILE_FMT = _CONSOLE_FMT + " (%(filename)s:%(lineno)d)"


class ShortNameFormatter(logging.Formatter):
    """Pad the logger name to a fixed width, cutting from the left when it is
    too long — the tail (the module) is the informative half."""

    def __init__(self, *args, name_width: int = 34, use_color: bool = False,
                 **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.name_width = name_width
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        name = record.name
        if len(name) > self.name_width:
            name = "..." + name[-(self.name_width - 3):]
        record.short_name = f"{name:<{self.name_width}}"
        message = super().format(record)
        color = _LEVEL_COLORS.get(record.levelno) if self.use_color else None
        return f"{color}{message}{_RESET}" if color else message


def _level(value: int | str) -> int:
    return value if isinstance(value, int) else \
        logging.getLevelNamesMapping()[value.upper()]


def _drop(logger: logging.Logger, kind: str) -> None:
    for h in [h for h in logger.handlers if getattr(h, _MINE, None) == kind]:
        logger.removeHandler(h)
        h.close()


def setup_logger(console_level: int | str = logging.INFO, *,
                 use_color: bool | None = None,
                 name_width: int = 34,
                 stream=None) -> logging.Logger:
    """Install this package's console handler and return its logger.

    Idempotent by replacement: a second call drops the handler this module
    installed before adding the new one, so a host running two protocols in one
    process does not print every line twice. Colour follows the stream — on for
    a terminal, off when the output is redirected into a file.
    """
    stream = stream or sys.stderr
    if use_color is None:
        use_color = hasattr(stream, "isatty") and stream.isatty()
    # The root keeps warnings and worse from every library, in plain format.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger(LIB_NAME)
    # The handlers decide what shows; filtering here would cap the file at the
    # console's level.
    logger.setLevel(logging.DEBUG)
    logger.propagate = False         # or the root handler prints our lines twice
    _drop(logger, "console")
    h = logging.StreamHandler(stream)
    h.setLevel(_level(console_level))
    h.setFormatter(ShortNameFormatter(fmt=_CONSOLE_FMT, datefmt="%H:%M:%S",
                                      name_width=name_width, use_color=use_color))
    setattr(h, _MINE, "console")
    logger.addHandler(h)
    return logger


@contextmanager
def to_file(path: str | Path, level: int | str = logging.DEBUG,
            name_width: int = 34):
    """Mirror this package's log into ``path`` for as long as the block runs,
    yielding the path.

    Append, never truncate, so a re-entered run adds to the file the attempt
    before it wrote. The handler comes off on the way out, so consecutive runs
    in one process do not write into each other's file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LIB_NAME)
    h = logging.FileHandler(path, mode="a", encoding="utf-8")
    h.setLevel(_level(level))
    h.setFormatter(ShortNameFormatter(fmt=_FILE_FMT, datefmt="%H:%M:%S",
                                      name_width=name_width))
    setattr(h, _MINE, "file")
    logger.addHandler(h)
    try:
        yield path
    finally:
        logger.removeHandler(h)
        h.close()
