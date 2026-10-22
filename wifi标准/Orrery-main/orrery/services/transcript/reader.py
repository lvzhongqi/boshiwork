"""Reading transcripts back: restore a session, split it into rounds, take only
the thinking, or slice a length-capped excerpt.

A damaged tail (the half line a kill leaves behind) is dropped by
read_jsonl_tolerant, and meta / interrupted marker lines take no part in
restoring a session. One round = one assistant entry plus every tool_result it
triggered.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orrery.infra.llm.client import ChatMessage, Role
from orrery.services.store.atomic import read_jsonl_tolerant


@dataclass
class Round:
    """One round of a session: the assistant entry and the tool results it
    triggered."""

    index: int                  # 1-based, the round number a human reads
    assistant: dict             # this round's assistant entry (with thinking / usage)
    tool_results: list[dict]


class TranscriptReader:
    """Read-side view of one transcript.jsonl."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def entries(self) -> list[dict]:
        """Every entry of the transcript, in order, damaged tail dropped."""
        return read_jsonl_tolerant(self._path)

    def messages(self) -> list[ChatMessage]:
        """Restore the message list — the data side of resuming a session.
        Raises ValueError on an entry type this reader does not know."""
        out: list[ChatMessage] = []
        for e in self.entries():
            match e["t"]:
                case "meta" | "interrupted" | "rejected":
                    # A rejected reply is a record only: replaying the refused
                    # shape is exactly what the rejection was about.
                    continue
                case "system":
                    out.append(ChatMessage(Role.SYSTEM, e["content"]))
                case "user":
                    out.append(ChatMessage(Role.USER, e["content"]))
                case "assistant":
                    out.append(ChatMessage(
                        Role.ASSISTANT, e["content"],
                        tool_calls=e["tool_calls"] or None,
                        thinking=e["thinking"],
                        # .get: transcripts lacking the key restore with no
                        # payload, so nothing is replayed.
                        thinking_blocks=e.get("thinking_blocks"),
                    ))
                case "tool_result":
                    out.append(ChatMessage(
                        Role.TOOL, e["content"], tool_call_id=e["tool_call_id"],
                    ))
                case other:
                    raise ValueError(f"{self._path}: unknown transcript entry type {other!r}")
        # An interrupt can land mid tool execution: the last assistant entry
        # carries tool_calls but only some tool_results were written. A
        # dangling tool_use is a 400 from the API, so pad the unanswered calls
        # and keep the promise that any transcript restores to a sendable
        # session.
        if out and out[-1].role in (Role.ASSISTANT, Role.TOOL):
            at = max((i for i, m in enumerate(out) if m.role == Role.ASSISTANT),
                     default=None)
            last_asst = out[at] if at is not None else None
            if last_asst is not None and last_asst.tool_calls:
                # Only the results that follow this entry answer its calls: an
                # adapter that synthesises call ids (gemini) repeats them from
                # round to round, so an id answered in an earlier round says
                # nothing about this one.
                answered = {m.tool_call_id for m in out[at + 1:]
                            if m.role == Role.TOOL}
                for call in last_asst.tool_calls:
                    cid = call.get("id")
                    if cid and cid not in answered:
                        out.append(ChatMessage(
                            Role.TOOL, "[interrupted: this tool call did not finish, result missing]",
                            tool_call_id=cid,
                        ))
        return out

    def rounds(self) -> list[Round]:
        """The session split into rounds, numbered from 1. A tool_result before
        any assistant entry has no round to attach to and is dropped."""
        out: list[Round] = []
        for e in self.entries():
            if e["t"] == "assistant":
                out.append(Round(index=len(out) + 1, assistant=e, tool_results=[]))
            elif e["t"] == "tool_result" and out:
                out[-1].tool_results.append(e)
        return out

    def usage_total(self) -> tuple[int, int]:
        """(input, output) tokens over the whole session. Every assistant entry
        carries the usage of the call that produced it, so a session's cost is
        readable from its own record without a second ledger."""
        # Rejected rounds count too: they were billed.
        rows = [e.get("usage") or {} for e in self.entries()
                if e["t"] in ("assistant", "rejected")]
        return (sum(int(u.get("input_tokens", 0)) for u in rows),
                sum(int(u.get("output_tokens", 0)) for u in rows))

    def thinking_only(self) -> list[str]:
        """Each round's thinking, in order. Rounds without thinking are skipped
        rather than left as empty slots."""
        return [r.assistant["thinking"] for r in self.rounds()
                if r.assistant.get("thinking")]

    def slice(self, from_round: int = 1, to_round: int | None = None,
              max_chars: int = 20_000) -> tuple[str, str | None]:
        """Render a range of rounds as text, capped at ``max_chars``. Returns
        (text, note): over the cap the text is truncated and the note spells
        out how much is left, following the convention for tool returns; the
        note is None when nothing was cut."""
        rounds = self.rounds()
        picked = [r for r in rounds
                  if r.index >= from_round and (to_round is None or r.index <= to_round)]
        parts: list[str] = []
        for r in picked:
            if r.assistant.get("thinking"):
                parts.append(f"[round {r.index} thinking]\n{r.assistant['thinking']}")
            parts.append(f"[round {r.index} assistant]\n{r.assistant['content']}")
            for tr in r.tool_results:
                parts.append(f"[round {r.index} tool {tr['name']} returned]\n{tr['content']}")
        text = "\n\n".join(parts)
        if len(text) <= max_chars:
            return text, None
        cut = text[:max_chars]
        rest = f"truncated: {len(text)} chars total, {len(text) - max_chars} not shown; " \
               f"narrow the round range and fetch in parts"
        return cut, rest
