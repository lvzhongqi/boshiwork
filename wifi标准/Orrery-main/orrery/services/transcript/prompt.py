"""A session's prompts written out for a human to read — one file per round.

The transcript is JSON Lines: tool definitions never appear in it and prompts
arrive as one escaped string. These files hold the same payload unescaped and
unexplained (any added text would read as part of the prompt), under three
ruled bands (TOOLS / SYS / USER), in ``rounds/`` beside the transcript — slot
00 for the opening prompt, the next free slot for each later round. Each is
written before its call goes out, so a run killed mid-round still says what it
was asking.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CANONICAL_TRANSCRIPT = "transcript.jsonl"
ROUNDS = "rounds"
PROMPT_MD = "00_prompt.md"
_SLOT = re.compile(r"^(\d+)_")


def rounds_dir(transcript: Path) -> Path:
    """Where a session's process goes: ``rounds/`` beside its transcript."""
    return Path(transcript).parent / ROUNDS


def prompt_path(transcript: Path) -> Path:
    """Where this session's opening prompt goes: the reserved slot of its
    rounds directory."""
    return rounds_dir(transcript) / PROMPT_MD


def round_prompt_path(transcript: Path) -> Path:
    """Where the prompt that opens the next round goes: the next free slot of
    the session's rounds directory, between the round that failed and the round
    it starts.

    The slot is read off the directory at each call, not counted in memory: the
    round files and these are written by two different objects (the node's
    RoundLog and the agent loop), and a counter that has not seen the other's
    files hands out a slot that is already taken."""
    d = rounds_dir(transcript)
    return d / f"{next_slot(d):02d}_prompt.md"


def next_slot(directory: Path) -> int:
    """The next free two-digit slot of a session directory. 00 is reserved for
    the opening prompt, so this never returns it.

    Raises RuntimeError past 99: with two-digit formatting a third digit sorts
    before its predecessors and reads back truncated, so the band would wrap
    and new files would claim taken slots."""
    d = Path(directory)
    used = []
    if d.exists():
        for p in d.glob("[0-9]*_*"):
            m = _SLOT.match(p.name)
            if m:
                used.append(int(m.group(1)))
    n = max(used + [0]) + 1
    if n > 99:
        raise RuntimeError(
            f"{d}: the slot band is full (99 numbered files); a third digit "
            f"would break the ordering the band exists for. This session has "
            f"repaired an extreme number of times — check why before "
            f"continuing")
    return n


def is_session_file(name: str) -> bool:
    """Is this file name a record — the session transcript or the step's fact
    file — rather than a product?

    Every artifact listing filters on this (the ledger's artifact line, the gap
    report's view of an upstream node, the tool-layer fence), so a record is
    never reported as something a step produced nor fed back to a model as an
    upstream product. An exact-name test: the process lives in ``rounds/`` and
    nothing here is renamed.
    """
    return name in (CANONICAL_TRANSCRIPT, "facts.jsonl")


def band(name: str) -> str:
    """One section rule. The only text in these files that is not payload, so
    its shape is one no prompt contains rather than a heading a reader could
    mistake for one."""
    return f"{'-' * 20} {name} {'-' * 20}"


def render(*, tools, system, user) -> str:
    """Render the opening of one session: the three parts of the request, each
    under its rule and otherwise untouched.

    ``tools`` are FunctionTool objects, written as the JSON array the request
    carries (name / description / input_schema). ``system`` is one prompt or
    the list of cache-breakpoint blocks it was split into, joined the way the
    model reads them; ``user`` is the first user message. Both go in raw and
    unfenced — prompts carry fenced blocks of their own, and a wrapping fence
    would end at the first of them.
    """
    blocks = [system] if isinstance(system, str) else list(system)
    payload = [{"name": t.name, "description": t.description,
                "input_schema": t.schema()} for t in tools]
    return "\n".join([
        band("TOOLS"), "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```", "",
        band("SYS"), "",
        "\n\n".join(blocks), "",
        band("USER"), "",
        user, ""])


def render_round(text: str, *, how: str = "") -> str:
    """Render the prompt that opens a later round: the framework's new message
    alone.

    The system prompt is not re-sent, so it stays in the opening file of the
    same session rather than being copied once per repair. ``how`` names the
    channel the message went out on when it was not a plain user message (a
    rejected submit call comes back as that call's tool result); it goes in the
    rule, where nothing can read it as part of the message.
    """
    return "\n".join([band(f"USER ({how})" if how else "USER"), "", text, ""])
