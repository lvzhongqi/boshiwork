"""The LLM session that aligns a candidate principals artifact with the gold
one, so the two vocabularies can be scored against each other."""

from __future__ import annotations

import json
from pathlib import Path

from orrery.agent.compose import localized, render_prompt
from orrery.infra.llm.client import ChatClient, ChatMessage, Effort, Role
from orrery.infra.llm.validation import OutputFormatViolation
from orrery.modules.scoring.alignment import ALIGNMENT_SCHEMA, validate_alignment
from orrery.services.transcript.writer import TranscriptWriter


_EFFORT = Effort.LOW


def _prompt(candidate: dict, gold: dict, lang: str) -> tuple[str, str]:
    system = render_prompt(
        __file__, localized("principals_alignment.sys.md", lang))
    user = render_prompt(
        __file__, localized("principals_alignment.user.md", lang),
        candidate=json.dumps(candidate, ensure_ascii=False, indent=2),
        gold=json.dumps(gold, ensure_ascii=False, indent=2),
        schema=json.dumps(ALIGNMENT_SCHEMA, ensure_ascii=False),
    )
    return system, user


async def align_principals(llm: ChatClient, *, candidate: dict, gold: dict,
                           writer: TranscriptWriter, model: str,
                           lang: str = "en") -> tuple[dict, dict]:
    """Ask for one alignment, retrying once on format or semantic invalidity.
    Returns the raw alignment and the validated maps; raises ValueError when
    both calls fail. The whole exchange is written to ``writer``."""
    system, user = _prompt(candidate, gold, lang)
    messages = [ChatMessage(Role.SYSTEM, system), ChatMessage(Role.USER, user)]
    writer.meta(node="extract_principals", step="symbol_alignment",
                model=model, effort=_EFFORT)
    writer.system(system)
    writer.user(user)
    writer.prompt(tools=[], system=system, user=user)

    last: Exception | None = None
    for attempt in range(2):
        try:
            with writer.bind():
                response = await llm.invoke(messages, json_schema=ALIGNMENT_SCHEMA,
                                            effort=_EFFORT)
            writer.assistant(response)
            alignment = json.loads(response.content)
            maps = validate_alignment(candidate, gold, alignment)
            return alignment, maps
        except (OutputFormatViolation, ValueError) as exc:
            last = exc
            if attempt:
                break
            correction = (
                "The proposed alignment was invalid: " + str(exc) +
                ". Return the complete corrected JSON object. Map only the same "
                "formal value, keep mappings one-to-one, and leave uncertain "
                "values unmatched."
            )
            messages.append(ChatMessage(Role.USER, correction))
            writer.user(correction)
            writer.round_prompt(correction, how="alignment validation failed")
    raise ValueError(f"principals symbol alignment failed after two calls: {last}")


def alignment_paths(eval_dir: Path, prefix: str) -> tuple[Path, Path]:
    """The public result and its private session trace."""
    stem = eval_dir / f"{prefix}_principals_alignment"
    return stem.with_suffix(".json"), stem / "transcript.jsonl"
