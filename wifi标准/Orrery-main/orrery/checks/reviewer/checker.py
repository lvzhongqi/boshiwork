"""Independent review, the third class of check: a separate model call with its
own context, seeing only the final .pv and the reference material — the
document's protocol-flow text and the semantic principals / value inventory.

Each finding carries a counterfactual assertion, and one that fails mechanical
checking is marked unverified. It is warning level and never blocks the run.
"""

from __future__ import annotations

import json
from pathlib import Path

from orrery.checks.reviewer.claims_verify import verify_findings
from orrery.infra.llm.client import (
    ChatClient, ChatMessage, ChatResponse, Effort, Role,
)
from orrery.infra.llm.validation import OutputFormatViolation

# The review answers six fixed questions about a model it is handed and writes
# no .pv text; higher effort here costs most of the run's wall clock.
_REVIEW_EFFORT = Effort.LOW

_SIX_ITEMS = """1. Security goals: count and meaning match one for one (the flow model should carry zero query; any is a finding)
2. Auth event keying: which value begin/end bind to and who emits them (skip when the flow model has no event)
3. The honest-peer test: how it is decided and where it is inserted (is every check the document spells out built in, and in the right place)
4. Message structure and field fidelity: every field the document lists is present, with the same order and types at both ends
5. Primitive usage: encryption / signature / MAC / KDF used according to their semantics and the document
6. The value a secrecy probe binds to (the flow model should carry no probe; any is a finding)"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "integer"},
                    "finding": {"type": "string"},
                    "counterfactual": {"type": "string"},
                },
                "required": ["item", "finding", "counterfactual"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["findings"],
    "additionalProperties": False,
}


async def review_flow(llm: ChatClient, *, pv_text: str,
                        knowledge: dict, flow_text: str,
                        flow_source: str = "?",
                        writer, model: str = "?", note=None,
                        on_prompt=None, on_delta=None) -> list[dict]:
    """Walk the six items once and return the stamped findings, possibly empty.

    ``flow_text`` is the document's protocol-flow text and ``flow_source`` names
    the selection that produced it (modules/document/corpus.py::flow_text).
    ``writer`` takes the whole session; ``note``, ``on_prompt`` and ``on_delta``
    are optional None-safe reporters, untyped so checks needs no services import.
    """
    def _note(text: str) -> None:
        if note is not None:
            note(text)

    system = (
        "You are an independent reviewer of formal models of cryptographic "
        "protocols. You see only the final .pv and the reference material "
        "(the semantic principals and pre-run values / the protocol-flow text of the "
        "document itself). You cannot see how it was produced, and there is no "
        "reference answer.\n\n"
        "Reconcile the model against the six items below and report **findings** "
        "(where it disagrees with the reference material or with the protocol's "
        "meaning):\n"
        + _SIX_ITEMS +
        "\n\nRules:\n"
        "- Reconcile, do not opine: every finding must name a concrete value / "
        "field / statement, never an impression;\n"
        "- Every finding must carry a counterfactual: the text that **should "
        "appear** in the .pv if your conclusion holds (several candidate "
        "wordings may be given, separated by |; it is checked by mechanical "
        "search, so do not report a finding you cannot turn into searchable "
        "text);\n"
        "- Report an empty array when there is nothing to report; do not pad."
    )
    user = (
        f"## .pv under review\n```proverif\n{pv_text}\n```\n\n"
        f"## Semantic principals and pre-run values\n{json.dumps(knowledge, ensure_ascii=False)}\n\n"
        f"## Protocol flow, from the document\n{flow_text}\n\n"
        f"Walk the six items and submit your findings against the schema.\n\n"
        f"<output_format>\nOutput exactly one object matching this JSON Schema, "
        f"and nothing else:\n"
        f"{json.dumps(_SCHEMA, ensure_ascii=False)}\n</output_format>"
    )
    writer.meta(node="extract_flow", step="independent_review", model=model,
                effort=_REVIEW_EFFORT, flow_source=flow_source)
    writer.system(system)
    writer.user(user)
    # This call has no tool, so the tool list is empty rather than absent.
    prompt_path = writer.prompt(tools=[], system=system, user=user)
    if on_prompt is not None:
        on_prompt(prompt_path)
    _note("independent review (warning level, non-blocking): reconciling the "
          "flow model against the six-item list")

    messages = [ChatMessage(Role.SYSTEM, system), ChatMessage(Role.USER, user)]
    calls = 0

    async def _ask() -> ChatResponse:
        """One recorded call, counted before the request so a raising call
        still counts. ``writer.bind()`` tells anything downstream of invoke()
        which transcript the call belongs to.
        """
        nonlocal calls
        calls += 1
        with writer.bind():
            resp = await llm.invoke(messages, json_schema=_SCHEMA,
                                    effort=_REVIEW_EFFORT, on_delta=on_delta)
        writer.assistant(resp)
        return resp

    try:
        try:
            resp = await _ask()
        except OutputFormatViolation as e:
            # The model sometimes writes narration first. This review sits outside
            # run_agent's repair loop, so it retries once on its own.
            writer.meta(step="independent_review", call=calls,
                        outcome="format_violation", detail=str(e))
            _note(f"independent review: call {calls} did not match the schema, "
                  f"retrying once")
            messages.append(ChatMessage(
                Role.USER, "Your last reply was not valid JSON. Output only the "
                           "JSON object matching the schema, with no other text."))
            writer.user(messages[-1].content)
            writer.round_prompt(messages[-1].content)
            resp = await _ask()
        findings = json.loads(resp.content)["findings"]
    except OutputFormatViolation as e:
        # Warning level: a failure degrades to one "review void" record instead
        # of bringing the node down.
        writer.meta(step="independent_review", call=calls,
                    outcome="format_violation", detail=str(e))
        _note(f"independent review: void after {calls} call(s), the output "
              f"never matched the schema")
        return [{"item": 0, "finding": f"independent review failed: output did not match the format; {e}",
                 "counterfactual": "", "status": "unverified"}]
    stamped = verify_findings(findings, pv_text)
    confirmed = sum(1 for f in stamped if f["status"] == "confirmed")
    _note(f"independent review: {calls} model call(s), {len(stamped)} finding(s), "
          f"{confirmed} confirmed by mechanical search — full session in "
          f"{Path(writer.path).name}")
    return stamped
