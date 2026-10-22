"""Writing transcripts: one transcript.jsonl per agent session, one record per
line, append only.

An entry is a session message made concrete, plus two marker kinds (meta and
interrupted); payload shapes match ChatMessage / ChatResponse in infra/llm.
resume reads it back into a message list to continue from, expert reads the
thinking out of it. This same object also writes the session's markdown
prompts (transcript/prompt.py), which is what a human reads instead.
"""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

import json

#: The transcript being written by the work in flight, or None outside a
#: session. Set by ``TranscriptWriter.bind`` and read by anything that needs to
#: know which session a model call belongs to. A ContextVar rather than an
#: argument because the answer is needed several layers down, at
#: ``ChatClient.invoke``; asyncio copies the context per task, so concurrent
#: sessions each see their own without coordinating.
current_session: ContextVar[Path | None] = ContextVar("current_session",
                                                      default=None)

from orrery.infra.llm.client import ChatResponse
from orrery.services.store.atomic import append_line


class TranscriptWriter:
    """Append-only writer for one session's transcript, and the place its
    markdown prompt files are written from."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """Where this session is being written. Callers that report the session
        on the ledger name the file from here rather than guessing it."""
        return self._path

    @contextmanager
    def bind(self):
        """Mark this transcript as the session in flight for the duration.

        Every model call made inside the block belongs to this session, which
        lets a client outside the engine correlate calls with the file that
        records them. Reset on the way out, so nothing leaks into whatever runs
        next on the same task.
        """
        token = current_session.set(self._path)
        try:
            yield self
        finally:
            current_session.reset(token)

    def _append(self, entry: dict) -> None:
        append_line(self._path, json.dumps(entry, ensure_ascii=False))

    def meta(self, **fields) -> None:
        """The session's header line: node name, model, start time and so on.
        The caller supplies the fields; they are not prescribed here."""
        self._append({"t": "meta", "ts": datetime.now().isoformat(timespec="seconds"),
                      **fields})

    def prompt(self, *, tools, system, user) -> Path:
        """Write the session's opening prompt beside the transcript and return
        its path. Called once, when the session opens; every round after that
        goes through ``round_prompt``.

        Both go through the writer so one session's files cannot end up in
        different places, and so a caller outside the agent loop
        (checks/reviewer) can leave the same record with the writer it was
        handed."""
        from orrery.services.store.atomic import write_text
        from orrery.services.transcript.prompt import prompt_path, render
        path = prompt_path(self._path)
        write_text(path, render(tools=tools, system=system, user=user))
        return path

    def round_prompt(self, text: str, *, how: str = "") -> Path:
        """Write the prompt that opens the next round — the framework's new
        message, in the slot between the round that failed and the round it
        starts — and return its path."""
        from orrery.services.store.atomic import write_text
        from orrery.services.transcript.prompt import (
            render_round, round_prompt_path,
        )
        path = round_prompt_path(self._path)
        write_text(path, render_round(text, how=how))
        return path

    def system(self, content: str) -> None:
        """Record the system prompt as sent."""
        self._append({"t": "system", "content": content})

    def user(self, content: str) -> None:
        """Record one user message as sent."""
        self._append({"t": "user", "content": content})

    def assistant(self, resp: ChatResponse) -> None:
        """Record one model reply: content, thinking, tool calls and usage."""
        self._append({
            "t": "assistant",
            "content": resp.content,
            "thinking": resp.thinking,
            # Provider-native opaque payload, persisted so a resumed session
            # can replay it: Anthropic wants signed thinking blocks back in a
            # tool loop, and dropping them 400s the first round after a resume.
            "thinking_blocks": resp.thinking_blocks,
            "tool_calls": resp.tool_calls,
            "usage": dataclasses.asdict(resp.usage),
        })

    def rejected(self, content: str, reason: str, usage=None) -> None:
        """Record a reply the format layer refused, verbatim, as a marker line
        resume never replays.

        A marker rather than an assistant entry because resume rebuilds the
        session from this file, and replaying the refused text puts the very
        shape that was rejected back in front of the model. It is kept because
        after a failed round it is the one thing worth reading, and its usage
        is kept so a session's cost covers rounds that produced nothing."""
        self._append({"t": "rejected", "content": content, "reason": reason,
                      "usage": dataclasses.asdict(usage) if usage else None,
                      "ts": datetime.now().isoformat(timespec="seconds")})

    def tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        """Record what one tool call returned, keyed by the call's id."""
        self._append({"t": "tool_result", "tool_call_id": tool_call_id,
                      "name": name, "content": content})

    def interrupted(self, reason: str) -> None:
        """Mark where the session stopped. Takes no part in restoring it."""
        self._append({"t": "interrupted", "reason": reason,
                      "ts": datetime.now().isoformat(timespec="seconds")})
