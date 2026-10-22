"""Low-effort LLM alpha-renaming for assumption/property references: it maps the
symbols a candidate artifact uses onto the gold ones before scoring."""

from __future__ import annotations

import json

from orrery.agent.compose import localized, render_prompt
from orrery.infra.llm.client import ChatClient, ChatMessage, Effort, Role
from orrery.infra.llm.validation import OutputFormatViolation
from orrery.modules.scoring.symbols import validate_symbol_mappings
from orrery.services.transcript.writer import TranscriptWriter


_EFFORT = Effort.LOW
_ROW = {
    "type": "object",
    "properties": {
        "candidate": {"type": "string"},
        "gold": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["candidate", "gold", "evidence"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"mappings": {"type": "array", "items": _ROW}},
    "required": ["mappings"],
    "additionalProperties": False,
}


async def align_references(llm: ChatClient, *, kind: str, candidate: dict,
                           gold: dict, candidate_symbols: set[str],
                           gold_symbols: set[str], writer: TranscriptWriter,
                           model: str, lang: str = "en") -> tuple[dict, dict]:
    """Map ``candidate_symbols`` onto ``gold_symbols`` for one artifact kind,
    retrying once on format or semantic invalidity. Returns the raw alignment
    and the validated one-to-one mapping; raises ValueError when both calls
    fail."""
    system = render_prompt(__file__, localized("reference_alignment.sys.md", lang))
    user = render_prompt(
        __file__, localized("reference_alignment.user.md", lang), kind=kind,
        candidate=json.dumps(candidate, ensure_ascii=False, indent=2),
        gold=json.dumps(gold, ensure_ascii=False, indent=2),
        candidate_symbols=json.dumps(sorted(candidate_symbols), ensure_ascii=False),
        gold_symbols=json.dumps(sorted(gold_symbols), ensure_ascii=False),
        schema=json.dumps(SCHEMA, ensure_ascii=False))
    messages = [ChatMessage(Role.SYSTEM, system), ChatMessage(Role.USER, user)]
    writer.meta(node=f"extract_{kind}", step="symbol_alignment", model=model,
                effort=_EFFORT)
    writer.system(system)
    writer.user(user)
    writer.prompt(tools=[], system=system, user=user)

    last: Exception | None = None
    for attempt in range(2):
        try:
            with writer.bind():
                response = await llm.invoke(messages, json_schema=SCHEMA,
                                            effort=_EFFORT)
            writer.assistant(response)
            alignment = json.loads(response.content)
            mapping = validate_symbol_mappings(
                alignment["mappings"], candidate_symbols, gold_symbols)
            return alignment, mapping
        except (OutputFormatViolation, ValueError) as exc:
            last = exc
            if attempt:
                break
            correction = (
                "The proposed mapping was invalid: " + str(exc) +
                ". Return the complete corrected JSON object. Keep it one-to-one "
                "and leave uncertain references unmatched."
            )
            messages.append(ChatMessage(Role.USER, correction))
            writer.user(correction)
            writer.round_prompt(correction, how="alignment validation failed")
    raise ValueError(f"{kind} reference alignment failed after two calls: {last}")
