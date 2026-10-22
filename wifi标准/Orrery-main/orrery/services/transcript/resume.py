"""The data side of resuming a session: transcript → message list.

Continuing is the agent loop's job. This module guarantees only that a
transcript from any moment restores to a session that can be sent: a damaged
tail is dropped on the read side, and interrupt markers never enter the list.
"""

from __future__ import annotations

from pathlib import Path

from orrery.infra.llm.client import ChatMessage
from orrery.services.transcript.reader import TranscriptReader


def load_messages(path: Path) -> list[ChatMessage]:
    """The message list a transcript restores to. The file must exist."""
    return TranscriptReader(path).messages()


def resume_messages(path: Path) -> list[ChatMessage] | None:
    """A non-empty transcript (the last attempt was interrupted) restores to a
    message list to continue from; otherwise None, meaning a fresh start."""
    if not path.exists():
        return None
    return load_messages(path) or None
