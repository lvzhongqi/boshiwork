"""Agent-domain events: rounds and tool calls. Emitted from agent/runner, where
the emitter is optional — with no emitter, nothing is sent."""

from __future__ import annotations

from dataclasses import dataclass

from orrery.services.events.types import Event


@dataclass
class RoundStarted(Event):
    """One round of the loop, counted.

    Emitted after the model call returns, not before it goes out: the round is
    numbered once there is a reply to number. A round opens with PromptFiled,
    and the reply arrives in between as ModelDelta fragments.
    """

    round_no: int = 0
    # What this one round cost. SessionUsage carries the session total, emitted
    # once at the end; these are the same numbers split per round, so a reader
    # can see which round was the expensive one.
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0          # part of input_tokens served from cache
    # Wall clock around llm.invoke in the runner, covering queueing, request and
    # parsing alike; output_tokens divided by it is the throughput an A/B
    # between endpoints is decided on. A ledger written before this field
    # reads back 0.
    duration_ms: int = 0


@dataclass
class ModelDelta(Event):
    """One fragment of a reply, while it is still arriving.

    The only non-durable event (see ``Event.durable``): broadcast to whoever is
    watching, never written down — the whole reply is in the transcript and the
    round is in the ledger, so a late watcher loses nothing. It is also the only
    event with no renderer and stays out of ``KNOWN``, since a log with one line
    per token is not a log.
    """

    durable = False
    kind: str = "text"          # "thinking" | "text"
    text: str = ""


@dataclass
class PromptFiled(Event):
    """A step was told something, and this is where the readable copy went.

    Emitted where the prompt is written, before the call goes out. The text
    stays in the file: a system prompt runs to tens of kilobytes, so only the
    path travels. The slot is claimed against the directory at write time
    (transcript/prompt.py::next_slot), so a reader cannot derive the name.
    """

    path: str = ""          # run-relative, the file just written
    round_no: int = 1       # the round this prompt opens
    chars: int = 0          # its length, so a collapsed line can say so
    how: str = ""           # why the framework opened this round, when it did


@dataclass
class ToolCalled(Event):
    """One tool invocation by the agent, with its arguments reduced to a
    digest."""

    tool: str = ""
    args_digest: str = ""           # argument summary (truncated), never large text


@dataclass
class SessionUsage(Event):
    """What one agent session cost, emitted when the session ends on every path
    (finished, failed, interrupted). The per-round figures are in the
    transcripts, scattered across the run directory; this puts the totals in the
    ledger, where work.md can add them up without reading anything else."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0          # part of input_tokens served from cache, billed at 0.1x
    rounds: int = 0


@dataclass
class ToolReturned(Event):
    """The outcome of one tool invocation, with the return value truncated to a
    digest."""

    tool: str = ""
    ok: bool = True
    result_digest: str = ""   # first ~120 chars of the return value, truncated mechanically
