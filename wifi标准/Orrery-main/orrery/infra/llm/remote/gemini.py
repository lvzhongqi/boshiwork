import asyncio
import base64
import json
import logging
import uuid
from typing import Any

from google import genai
from google.genai import types

from orrery.infra.llm.client import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    RemoteChatClient,
    Role,
)
from orrery.infra.llm.client import (
    Effort, FunctionTool, OnDelta, ToolChoice, ToolChoiceMode, feed,
)
from orrery.infra.llm.validation import (
    OutputFormatViolation,
    ensure_schema_valid,
    ensure_valid_json,
)


# Model families that have thinking_level. The 2.5 family carries only
# thinking_budget and 400s on any level, so a rung sent there fails the call.
# Matched as a substring because a gateway may prefix the model id.
_THINKING_LEVEL_MODELS = (
    "gemini-3",
    "gemini-4",
)


def _supports_thinking_level(model_name: str) -> bool:
    return any(m in model_name for m in _THINKING_LEVEL_MODELS)


# Effort rung -> thinking_config.thinking_level. The scale stops at HIGH, so the
# two rungs above it saturate there and say so once. A family without
# thinking_level gets no thinking parameter at all, only a warning.
_EFFORT: dict[Effort, "types.ThinkingLevel"] = {
    Effort.LOW: types.ThinkingLevel.LOW,
    Effort.MEDIUM: types.ThinkingLevel.MEDIUM,
    Effort.HIGH: types.ThinkingLevel.HIGH,
    Effort.VERY_HIGH: types.ThinkingLevel.HIGH,
    Effort.MAX: types.ThinkingLevel.HIGH,
}


class RemoteChatGemini(RemoteChatClient):
    """Gemini adapter over Google's native generateContent, via google-genai.

    Wire quirks: tool results pair by function name and call ids are synthesised
    here, parallel calls cannot be forbidden, and from Gemini 3 a round whose
    function_call parts lost their thought signature is rejected. json output is
    checked after the reply, since response_mime_type conflicts with tools.
    """

    # One call with no response for longer than this means the service is
    # unavailable: fail immediately, no retry.
    _TIMEOUT = 300.0

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(model_name, api_key)
        self.logger = logging.getLogger(__name__)
        # config's llm.timeout_s; None keeps this backend's own default.
        self.timeout_s = float(timeout_s or self._TIMEOUT)
        # One run makes hundreds of requests, so effort is warned about once.
        self._effort_warned = False
        http_options: types.HttpOptions | None = None
        if url or extra_headers:
            http_options = types.HttpOptions(
                base_url=self._normalize_base_url(url),
                headers=extra_headers,
            )
        # No retry_options means zero retries: a failure propagates immediately.
        self.client = genai.Client(api_key=api_key, http_options=http_options)

    @staticmethod
    def _normalize_base_url(url: str | None) -> str | None:
        """Strip a trailing /v1 from a configured base url.

        The SDK appends its own /v1beta/models/... to base_url, while the url in
        config may be shared with the OpenAI backend, which does carry /v1.
        """
        if not url:
            return None
        u = url.rstrip("/")
        if u.endswith("/v1"):
            u = u[: -len("/v1")]
        return u or None

    async def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[FunctionTool] | None = None,
        tool_choice: ToolChoice | None = None,
        temperature: float | None = None,   # None = not sent, model default
        response_format: str | None = None,
        json_schema: dict | None = None,
        effort: Effort | None = None,
        on_delta: OnDelta | None = None,
        **kwargs,
    ) -> ChatResponse:
        want_json = response_format == "json"
        if tool_choice is not None:
            tool_choice.validate_against(tools)

        system_prompt, contents = self._convert_messages(messages)

        config: dict[str, Any] = {}
        if system_prompt:
            config["system_instruction"] = system_prompt
        if temperature is not None:
            config["temperature"] = temperature
        # No API-side JSON forcing (response_mime_type / response_json_schema):
        # both output intents are validated locally after the reply.
        if tools:
            config["tools"] = self._convert_tools(tools)
        tc = self._convert_tool_choice(tool_choice)
        if tc is not None:
            config["tool_config"] = tc
        # include_thoughts is always on: Gemini bills thinking as output whether
        # or not it hands the trace back, and the 2.5 family has it too.
        # thinking_level is the effort rung and exists only from Gemini 3.
        thinking = types.ThinkingConfig(include_thoughts=True)
        if effort is not None:
            if not _supports_thinking_level(self.model_name):
                self._warn_effort_unsupported(effort)
            else:
                level = _EFFORT[effort]
                if level.value.lower() != effort.value:
                    self._warn_effort_saturated(effort, level)
                thinking.thinking_level = level
        config["thinking_config"] = thinking
        config.update(kwargs)  # pass through thinking_config, max_output_tokens, etc.

        try:
            return await asyncio.wait_for(
                self._invoke_once(
                    contents=contents,
                    config=config,
                    tool_choice=tool_choice,
                    want_json=want_json,
                    json_schema=json_schema,
                    on_delta=on_delta,
                ),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError as e:
            msg = (
                f"LLM timed out: {self.model_name} gave no response in "
                f"{self.timeout_s:.0f}s; treating the service as unavailable"
            )
            self.logger.error(msg)
            raise RuntimeError(msg) from e
        except Exception:
            self.logger.exception(f"Failed to dialogue with {self.model_name}.")
            raise

    def _convert_messages(
        self, messages: list[ChatMessage],
    ) -> tuple[str | None, list[types.Content]]:
        system_parts: list[str] = []
        out: list[types.Content] = []
        # The unified shape pairs tool results by id, Gemini by function name.
        name_by_call_id: dict[str, str] = {}

        for msg in messages:
            if msg.role == Role.SYSTEM:
                # A list is one prompt pre-split at cache breakpoints; Gemini's
                # implicit caching works on the joined prefix, so they join.
                if isinstance(msg.content, list):
                    system_parts.extend(msg.content)
                else:
                    system_parts.append(msg.content)

            elif msg.role == Role.USER:
                out.append(types.Content(
                    role="user", parts=[types.Part.from_text(text=msg.content)],
                ))

            elif msg.role == Role.ASSISTANT:
                parts: list[types.Part] = []
                # Gemini 3 400s a round whose function_call parts have lost the
                # thought_signature they were issued with; the signatures ride
                # in thinking_blocks, an opaque carrier only this adapter reads.
                text_sig, sig_by_call = self._signatures(msg.thinking_blocks)
                if msg.content and msg.content.strip():
                    parts.append(types.Part(
                        text=msg.content, thought_signature=text_sig,
                    ))
                for tc in msg.tool_calls or []:
                    args = tc.get("arguments_json")
                    if not isinstance(args, dict):
                        try:
                            args = json.loads(tc.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                    name_by_call_id[tc["id"]] = tc["name"]
                    # The call id is not sent back: it is usually synthesised
                    # here and pairing is by name. Only the signature returns.
                    parts.append(types.Part(
                        function_call=types.FunctionCall(name=tc["name"], args=args),
                        thought_signature=sig_by_call.get(tc["id"]),
                    ))
                if not parts:
                    raise RuntimeError(
                        "ASSISTANT message has neither content nor tool_calls."
                    )
                out.append(types.Content(role="model", parts=parts))

            elif msg.role == Role.TOOL:
                if not msg.tool_call_id:
                    raise RuntimeError(
                        "TOOL message must carry tool_call_id matching the "
                        "originating assistant tool_call."
                    )
                name = name_by_call_id.get(msg.tool_call_id)
                if name is None:
                    raise RuntimeError(
                        f"unknown tool_call_id={msg.tool_call_id!r}: not in any earlier "
                        f"assistant tool_calls, so the function name cannot be "
                        f"resolved (Gemini pairs tool results by name)"
                    )
                part = types.Part.from_function_response(
                    name=name, response={"result": msg.content},
                )
                # Several tool results from one round merge into one user
                # Content.
                if out and out[-1].role == "user" and out[-1].parts and \
                        out[-1].parts[0].function_response is not None:
                    out[-1].parts.append(part)
                else:
                    out.append(types.Content(role="user", parts=[part]))

            else:
                raise RuntimeError(f"Unsupported role: {msg.role}")

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        return system_prompt, out

    @staticmethod
    def _convert_tools(tools: list[FunctionTool]) -> list[types.Tool]:
        """FunctionTool -> Gemini's Tool.

        parameters_json_schema takes native JSON Schema, so the dict from
        FunctionTool.schema() goes in directly, with no extra nesting.
        """
        return [types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.schema(),
            )
            for t in tools
        ])]

    @staticmethod
    def _convert_tool_choice(tc: ToolChoice | None) -> types.ToolConfig | None:
        """ToolChoice -> Gemini's ToolConfig, or None when nothing is forced.

        REQUIRED -> ANY, TOOL -> ANY plus a single-name allowlist, NONE -> NONE,
        AUTO -> not sent. Gemini cannot forbid parallel calls, so
        disable_parallel raises NotImplementedError.
        """
        if tc is None:
            return None
        if tc.disable_parallel:
            raise NotImplementedError(
                "Gemini has no parameter to forbid parallel tool calls; disable_parallel cannot take effect"
            )
        match tc.mode:
            case ToolChoiceMode.AUTO:
                return None
            case ToolChoiceMode.REQUIRED:
                cfg = types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY)
            case ToolChoiceMode.TOOL:
                cfg = types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY,
                    allowed_function_names=[tc.tool_name],
                )
            case ToolChoiceMode.NONE:
                cfg = types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.NONE)
        return types.ToolConfig(function_calling_config=cfg)

    async def _invoke_once(
        self,
        *,
        contents: list[types.Content],
        config: dict[str, Any],
        tool_choice: ToolChoice | None,
        want_json: bool,
        json_schema: dict | None,
        on_delta: OnDelta | None = None,
    ) -> ChatResponse:
        # Two request paths, one parser. This SDK has no accumulator, so the
        # streaming path reassembles the chunks itself; both paths hand the same
        # (feedback, candidates, usage) triple to the checks below.
        if on_delta is None:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
            feedback = getattr(response, "prompt_feedback", None)
            candidates, usage = response.candidates, response.usage_metadata
        else:
            feedback, candidates, usage = await self._stream_and_merge(
                contents, config, on_delta)
        # A prompt blocked as a whole comes back with no candidates; report the
        # real reason before the empty-response error below.
        if feedback is not None and feedback.block_reason:
            raise RuntimeError(
                f"{self.model_name} refused the input "
                f"(block_reason={feedback.block_reason})"
            )
        if not candidates:
            raise RuntimeError(
                f"empty response from {self.model_name}: no candidates; "
                f"treating the service as degraded"
            )
        candidate = candidates[0]
        self._check_finish_reason(candidate.finish_reason)

        content, thinking, tool_calls, thinking_blocks = self._extract_parts(candidate)
        # Whether the forcing setting took effect is judged from tool_calls
        # themselves, since a gateway may drop tool_config.
        if tool_choice is not None:
            tool_choice.verify_response(tool_calls)
        if not content.strip() and not tool_calls:
            raise RuntimeError(
                f"empty response from {self.model_name}: no text and no function_call, "
                f"finish_reason={candidate.finish_reason}; treating the service as degraded"
            )
        # Result-side checks (infra/llm/validation.py). Only a final reply that
        # calls no tools is validated: the body of a round carrying tool_calls
        # is usually narration.
        if content.strip() and not tool_calls:
            try:
                if json_schema is not None:
                    content = ensure_schema_valid(content, json_schema, self.model_name)
                elif want_json:
                    content = ensure_valid_json(content, self.model_name)
            except OutputFormatViolation as e:
                # The rejected reply cost tokens and only this layer still holds
                # the usage, so it travels on the exception for the runner to
                # record (services/transcript/writer.py::rejected).
                e.usage = self._build_usage(usage)
                raise
        return ChatResponse(
            content=content,
            usage=self._build_usage(usage),
            tool_calls=tool_calls,
            thinking=thinking,
            thinking_blocks=thinking_blocks,
        )

    async def _stream_and_merge(
        self,
        contents: list[types.Content],
        config: dict[str, Any],
        on_delta: OnDelta,
    ) -> tuple[Any, list[types.Candidate], Any]:
        """Reassemble a streamed reply into (prompt_feedback, candidates, usage).

        Parts land in arrival order in one candidate, so both paths read the
        reply through _extract_parts. usage_metadata and a text part's signature
        are last-one-wins; the per-call signatures Gemini 3 checks are keyed by
        call id and survive intact.
        """
        parts: list[types.Part] = []
        feedback = None
        usage = None
        finish = None
        stream = await self.client.aio.models.generate_content_stream(
            model=self.model_name,
            contents=contents,
            config=types.GenerateContentConfig(**config),
        )
        async for chunk in stream:
            feedback = getattr(chunk, "prompt_feedback", None) or feedback
            usage = chunk.usage_metadata or usage
            candidate = (chunk.candidates or [None])[0]
            if candidate is None:
                continue
            finish = candidate.finish_reason or finish
            for part in (candidate.content.parts or []) if candidate.content else ():
                parts.append(part)
                feed(on_delta, "thinking" if part.thought else "text", part.text)
        # A prompt blocked outright streams feedback and no parts; handing back
        # no candidates lets the caller raise as on the non-streaming path.
        if not parts and finish is None:
            return feedback, [], usage
        merged = types.Candidate(
            content=types.Content(role="model", parts=parts),
            finish_reason=finish,
        )
        return feedback, [merged], usage

    def _warn_effort_unsupported(self, effort: Effort) -> None:
        """Warn once that effort was dropped. thinking_level exists only from
        Gemini 3 onwards, and ChatClient.invoke's contract for a backend without
        the knob is to drop it with a warning rather than fail."""
        if self._effort_warned:
            return
        self._effort_warned = True
        self.logger.warning(
            f"effort dropped for {self.model_name}: thinking_level exists only "
            f"from the Gemini 3 family onwards, and this model 400s on any "
            f"level, so the caller's {effort.value!r} was not sent. The reply "
            f"is valid but its thinking depth is the model's own choice."
        )

    def _warn_effort_saturated(self, effort: Effort, sent) -> None:
        """Warn once, and only when a rung was actually flattened. The two top
        rungs both land on HIGH here, so a run that tells them apart elsewhere
        cannot on this backend."""
        if self._effort_warned:
            return
        self._effort_warned = True
        self.logger.warning(
            f"effort saturated for {self.model_name}: the caller asked for "
            f"{effort.value!r}, and this backend's thinking_level stops at "
            f"{sent.value!r}, so that is what was sent. Rungs above it are "
            f"indistinguishable here; only the remote-claude backend separates "
            f"them."
        )

    def _check_finish_reason(self, reason: types.FinishReason | None) -> None:
        """STOP is normal, MAX_TOKENS logs a warning, and every other reason
        (SAFETY, RECITATION, MALFORMED_FUNCTION_CALL, ...) raises."""
        if reason is None or reason == types.FinishReason.STOP:
            return
        if reason == types.FinishReason.MAX_TOKENS:
            self.logger.warning(
                f"output hit the token limit on {self.model_name}; the result may be truncated"
            )
            return
        raise RuntimeError(
            f"{self.model_name} stopped abnormally (finish_reason={reason})"
        )

    @staticmethod
    def _extract_parts(
        candidate,
    ) -> tuple[str, str | None, list[dict[str, Any]], list[dict] | None]:
        """Split a candidate's parts into (content, thinking, tool_calls,
        thinking_blocks).

        Thought parts are trace only and may be absent, function_call ids are
        synthesised in order, and thinking_blocks carries the parts' thought
        signatures as base64 text since the transcript writer json.dumps it.
        """
        texts: list[str] = []
        thoughts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        signatures: list[dict] = []
        parts = (candidate.content.parts or []) if candidate.content else []
        for i, part in enumerate(parts):
            sig = getattr(part, "thought_signature", None)
            if getattr(part, "thought", False):
                if part.text:
                    thoughts.append(part.text)
                # A thought part's own signature is not kept: only text and
                # function_call parts are ever rebuilt on replay.
                continue
            if part.text:
                texts.append(part.text)
                if sig:
                    signatures.append({
                        "type": "thought_signature",
                        "target": "text",
                        "signature": base64.b64encode(sig).decode(),
                    })
            elif part.function_call is not None:
                fc = part.function_call
                args = dict(fc.args or {})
                # Gemini sends no call id, so one is made up. Unique per reply
                # rather than per position: a transcript pairs results to calls
                # by id, and the same position in every round would pair the
                # last round's dangling call with an earlier round's answer.
                call_id = fc.id or f"call_{i}_{fc.name}_{uuid.uuid4().hex[:8]}"
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "name": fc.name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                    "arguments_json": args,
                })
                if sig:
                    signatures.append({
                        "type": "thought_signature",
                        "target": "tool_call",
                        "id": call_id,
                        "signature": base64.b64encode(sig).decode(),
                    })
        return (
            "".join(texts),
            ("\n\n".join(thoughts) or None),
            tool_calls,
            signatures or None,
        )

    @staticmethod
    def _signatures(blocks: list[dict] | None) -> tuple[bytes | None, dict[str, bytes]]:
        """Read the carrier shape back: (text part signature, call_id ->
        signature map). Anything unrecognised is skipped rather than raising, so
        a transcript written by another backend replays with no signatures.
        """
        text_sig: bytes | None = None
        by_call: dict[str, bytes] = {}
        for b in blocks or []:
            if b.get("type") != "thought_signature":
                continue
            try:
                raw = base64.b64decode(b.get("signature") or "")
            except (ValueError, TypeError):
                continue
            if not raw:
                continue
            if b.get("target") == "text":
                text_sig = raw
            elif b.get("target") == "tool_call" and b.get("id"):
                by_call[b["id"]] = raw
        return text_sig, by_call

    @staticmethod
    def _build_usage(usage) -> TokenUsage:
        if usage is None:
            return TokenUsage(
                input_tokens=0, output_tokens=0, total_tokens=0, cached_tokens=0,
            )
        prompt = usage.prompt_token_count or 0
        candidates = usage.candidates_token_count or 0
        thoughts = usage.thoughts_token_count or 0
        return TokenUsage(
            # prompt_token_count already includes the cache hit; thoughts bill
            # as output.
            input_tokens=prompt,
            output_tokens=candidates + thoughts,
            total_tokens=usage.total_token_count or (prompt + candidates + thoughts),
            cached_tokens=usage.cached_content_token_count or 0,
        )
