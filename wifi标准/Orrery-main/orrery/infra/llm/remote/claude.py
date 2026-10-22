import asyncio
import json
import logging
from typing import Any

import anthropic

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


# Model families that reject any temperature, 0 included, with a 400. Matched as
# substrings because a gateway may prefix the id ("anthropic.claude-opus-5").
_NO_TEMPERATURE_MODELS = (
    "claude-opus-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def _accepts_temperature(model_name: str) -> bool:
    return not any(m in model_name for m in _NO_TEMPERATURE_MODELS)


# Model families that take adaptive thinking ({"type": "adaptive"}). The others
# know only the budget_tokens shape and 400 on "adaptive", so they get no
# thinking parameter at all. Substring matched as above.
_ADAPTIVE_THINKING_MODELS = (
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def _supports_adaptive_thinking(model_name: str) -> bool:
    return any(m in model_name for m in _ADAPTIVE_THINKING_MODELS)


# Effort rung -> output_config.effort; OutputConfigParam declares these five.
_EFFORT: dict[Effort, str] = {
    Effort.LOW: "low",
    Effort.MEDIUM: "medium",
    Effort.HIGH: "high",
    Effort.VERY_HIGH: "xhigh",
    Effort.MAX: "max",
}


# Each family's official max output tokens (thinking included). Substring
# matched, longest marker first, so "claude-opus-4-5" misses the shorter entries.
_MODEL_CEILINGS: tuple[tuple[str, int], ...] = (
    ("claude-opus-5", 128000),
    ("claude-opus-4-8", 128000),
    ("claude-opus-4-7", 128000),
    ("claude-opus-4-6", 128000),
    ("claude-sonnet-5", 128000),
    ("claude-sonnet-4-6", 128000),
    ("claude-fable-5", 128000),
    ("claude-mythos-5", 128000),
    ("claude-opus-4-5", 64000),
    ("claude-sonnet-4-5", 64000),
    ("claude-haiku-4-5", 64000),
)
# Unknown model id: low enough that every Claude generation accepts it.
_DEFAULT_CEILING = 16384

# The max_tokens this adapter asks for unless the family caps it lower; the
# parameter is required and no caller passes an output budget in. It has to bite
# before the timeout does: max_tokens truncates text a node can repair in one
# round, while the timeout raises and ends the run. 32000 tokens take roughly
# 400s, inside the 600s default timeout; a much lower llm.timeout_s inverts that.
_DEFAULT_MAX_TOKENS = 32000


def _max_output_tokens(model_name: str) -> int:
    """The default max_tokens, clamped to what the model family accepts.

    The ceilings differ per family and exceeding one is a 400.
    """
    ceiling = next((c for m, c in _MODEL_CEILINGS if m in model_name),
                   _DEFAULT_CEILING)
    return min(ceiling, _DEFAULT_MAX_TOKENS)


class RemoteChatClaude(RemoteChatClient):
    """Claude adapter, speaking Anthropic's native ``/v1/messages``.

    Translates ``RemoteChatClient.invoke``'s arguments into Anthropic's wire
    format and the reply back into a ``ChatResponse``; it assembles no prompts
    and retries nothing. ``json_schema`` is checked locally after the reply,
    never sent, since the map-shaped json nodes have keys no closed schema lists.
    """

    # Fallback when the caller passes no timeout. Generous because the deepest
    # step (flow at xhigh effort) thinks for as long as it takes.
    _DEFAULT_TIMEOUT = 600.0


    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-opus-5",
        url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        cache_ttl: str | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(model_name, api_key)
        # Cache lifetime for the system blocks: None uses the default 5m; "1h"
        # holds the shared corpus across repeat runs at 2x write cost and needs
        # the extended-TTL beta, whose header is added here so config stays one
        # switch.
        self.cache_ttl = cache_ttl
        if cache_ttl and cache_ttl != "5m":
            beta = "extended-cache-ttl-2025-04-11"
            extra_headers = dict(extra_headers or {})
            existing = extra_headers.get("anthropic-beta")
            extra_headers["anthropic-beta"] = (
                f"{existing},{beta}" if existing and beta not in existing else
                existing if existing else beta
            )
        self.logger = logging.getLogger(__name__)
        self.timeout_s = float(timeout_s or self._DEFAULT_TIMEOUT)
        self.max_tokens = _max_output_tokens(model_name)
        # One run makes hundreds of requests, so the temperature warning goes
        # out only the first time.
        self._temperature_warned = False
        # extra_headers go out with every request and override the SDK's own
        # defaults of the same name: anthropic-beta features, proxy headers.
        self.client = anthropic.AsyncClient(
            api_key=api_key,
            base_url=self._normalize_base_url(url),   # None goes to Anthropic directly
            default_headers=extra_headers,
            max_retries=0,   # fail immediately; the SDK would otherwise retry twice
            # Matches the asyncio.wait_for in invoke.
            timeout=self.timeout_s,
        )

    @staticmethod
    def _normalize_base_url(url: str | None) -> str | None:
        """Strip a trailing ``/v1`` from the configured base url.

        The anthropic SDK appends ``/v1/messages`` itself, so a base_url that
        carries ``/v1`` would post to ``/v1/v1/messages``. The same config url
        may be shared with the OpenAI backend, whose SDK does need the ``/v1``.
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
        temperature: float | None = None,   # None sends nothing; model default
        response_format: str | None = None,
        json_schema: dict | None = None,
        effort: Effort | None = None,
        on_delta: OnDelta | None = None,
        **kwargs,
    ) -> ChatResponse:
        if temperature is not None and not _accepts_temperature(self.model_name):
            self._warn_temperature_dropped(temperature)
            temperature = None
        want_json = response_format == "json"
        if tool_choice is not None:
            tool_choice.validate_against(tools)

        # Caching is on by default. Pass cache_system=False in kwargs to turn it off.
        cache = kwargs.pop("cache_system", True)

        # Adaptive thinking with a readable summary, decided per request. Sent
        # only when the family takes the adaptive shape, no forcing tool_choice
        # is set and the caller gave no temperature: both of the latter are
        # rejected alongside thinking on some models and platforms.
        # display="summarized" only affects visibility, not what runs or bills.
        forcing = tool_choice is not None and tool_choice.mode in (
            ToolChoiceMode.REQUIRED, ToolChoiceMode.TOOL,
        )
        thinking_param: Any = anthropic.NOT_GIVEN
        if (_supports_adaptive_thinking(self.model_name)
                and not forcing and temperature is None):
            thinking_param = {"type": "adaptive", "display": "summarized"}

        system_blocks, claude_messages = self._convert_messages(messages)
        tools_param = self._convert_tools(tools)

        try:
            return await asyncio.wait_for(
                self._invoke_once(
                    system_blocks=system_blocks,
                    claude_messages=claude_messages,
                    temperature=temperature,
                    cache=cache,
                    tools_param=tools_param,
                    tool_choice=tool_choice,
                    thinking_param=thinking_param,
                    effort=effort,
                    want_json=want_json,
                    json_schema=json_schema,
                    on_delta=on_delta,
                    **kwargs,
                ),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError as e:
            msg = (
                f"LLM timed out: {self.model_name} did not finish in "
                f"{self.timeout_s:.0f}s (max_tokens={self.max_tokens}, which "
                f"should have capped the reply first); treating the service as "
                f"unavailable"
            )
            self.logger.error(msg)
            raise RuntimeError(msg) from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"Claude connection failed: {e}") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Claude API error [{e.status_code}]: {e.message}") from e
        except Exception:
            self.logger.exception(f"Failed to dialogue with {self.model_name}.")
            raise

    def _warn_temperature_dropped(self, temperature: float) -> None:
        if self._temperature_warned:
            return
        self._temperature_warned = True
        self.logger.warning(
            f"temperature dropped for {self.model_name}: this model family removed "
            f"the sampling parameters and 400s on any value; requested "
            f"temperature={temperature}, sending none and using the default"
        )

    def _convert_messages(
        self, messages: list[ChatMessage],
    ) -> tuple[list[str] | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                # A list is one prompt pre-split at cache-breakpoint boundaries
                # (see ChatMessage.content); each part becomes its own block.
                if isinstance(msg.content, list):
                    system_parts.extend(msg.content)
                else:
                    system_parts.append(msg.content)

            elif msg.role == Role.USER:
                out.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                blocks: list[dict[str, Any]] = []
                # Thinking blocks go back first (Anthropic requires them ahead
                # of text/tool_use) and only when replayable; they do not count
                # as content for the empty-message check below.
                thinking_blocks = self._replayable_thinking(msg.thinking_blocks)
                if msg.content and msg.content.strip():
                    blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls or []:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": self._tool_call_input(tc),
                    })
                if not blocks:
                    raise RuntimeError(
                        "ASSISTANT message has neither content nor tool_calls; "
                        "Anthropic rejects empty content blocks."
                    )
                out.append({"role": "assistant",
                            "content": thinking_blocks + blocks})

            elif msg.role == Role.TOOL:
                if not msg.tool_call_id:
                    raise RuntimeError(
                        "TOOL message must carry tool_call_id matching the "
                        "originating assistant tool_use."
                    )
                block = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": msg.content,
                }
                # Every tool_result of one assistant round must land in the same
                # following user message, so consecutive TOOL messages merge.
                if self._is_tool_result_message(out[-1] if out else None):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})

            else:
                raise RuntimeError(f"Unsupported role: {msg.role}")

        return (system_parts or None), out

    @staticmethod
    def _replayable_thinking(blocks: list[dict] | None) -> list[dict[str, Any]]:
        """The signature gate on replaying thinking blocks: all or nothing.

        Blocks go back verbatim only when every ``thinking`` block carries a
        signature (``redacted_thinking`` is opaque and passes by construction).
        The endpoint rejects an unsigned block, so the whole list is dropped.
        Blocks of any other type are another backend's carrier (gemini's
        ``thought_signature``, the Responses API's ``reasoning`` items), left
        in the transcript by a session that ran there; the endpoint rejects an
        unknown block type, so they are left out, as the other adapters leave
        out this one's.
        """
        if not blocks:
            return []
        own = [b for b in blocks
               if b.get("type") in ("thinking", "redacted_thinking")]
        for b in own:
            if b.get("type") == "thinking" and not b.get("signature"):
                return []
        return [dict(b) for b in own]

    @staticmethod
    def _is_tool_result_message(msg: dict[str, Any] | None) -> bool:
        if not msg or msg.get("role") != "user":
            return False
        content = msg.get("content")
        return (
            isinstance(content, list)
            and bool(content)
            and content[0].get("type") == "tool_result"
        )

    @staticmethod
    def _tool_call_input(tc: dict[str, Any]) -> dict[str, Any]:
        """Recover a historical tool_use's arguments when replaying it, from
        ``arguments_json`` (parsed dict) or ``arguments`` (raw string). With
        neither usable it returns an empty dict and lets the caller fail on the
        missing argument.
        """
        args = tc.get("arguments_json")
        if isinstance(args, dict):
            return args
        raw = tc.get("arguments")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {}

    @staticmethod
    def _convert_tools(tools: list[FunctionTool] | None) -> Any:
        """``FunctionTool`` → Anthropic's tools shape.

        ``FunctionTool.schema()`` already produces JSON Schema, so it goes
        straight into ``input_schema``; the shape is flat, with no ``strict``
        field.
        """
        if not tools:
            return anthropic.NOT_GIVEN
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.schema(),
            }
            for t in tools
        ]

    @staticmethod
    def _convert_tool_choice(tc: ToolChoice | None) -> Any:
        """``ToolChoice`` → Anthropic's tool_choice object.

        "Must call something" is ``any``, and forbidding parallel calls is
        ``disable_parallel_tool_use`` inside the object. A pure default (auto,
        parallel allowed) is not sent at all: changing tool_choice invalidates
        the messages-level cache.
        """
        if tc is None:
            return anthropic.NOT_GIVEN
        type_by_mode = {
            ToolChoiceMode.AUTO: "auto",
            ToolChoiceMode.REQUIRED: "any",
            ToolChoiceMode.TOOL: "tool",
            ToolChoiceMode.NONE: "none",
        }
        out: dict[str, Any] = {"type": type_by_mode[tc.mode]}
        if tc.mode is ToolChoiceMode.TOOL:
            out["name"] = tc.tool_name
        if tc.disable_parallel:
            out["disable_parallel_tool_use"] = True
        if out == {"type": "auto"}:
            return anthropic.NOT_GIVEN
        return out

    def _build_system_param(self, system_blocks: list[str] | None, cache: bool) -> Any:
        """Build the system parameter and mark its cache breakpoints.

        Each block gets its own breakpoint, so a corpus block shared by several
        nodes hits the cache even when the node-specific block after it differs.
        Four breakpoints exist per request and the rolling message one takes one,
        so only the first three blocks are marked; the rest merge into the last.
        """
        if system_blocks is None:
            return anthropic.NOT_GIVEN
        if not cache:
            return "\n\n".join(system_blocks)
        blocks = list(system_blocks)
        if len(blocks) > 3:
            blocks[2:] = ["\n\n".join(blocks[2:])]
        control: dict[str, Any] = {"type": "ephemeral"}
        if self.cache_ttl and self.cache_ttl != "5m":
            control["ttl"] = self.cache_ttl
        return [{
            "type": "text",
            "text": text,
            "cache_control": dict(control),
        } for text in blocks]

    @staticmethod
    def _with_rolling_breakpoint(
        claude_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Put a rolling breakpoint on the last block of the last message.

        Everything before the mark is cached, and a tool loop only appends to
        its history, so the next round's prefix is exactly this round's content
        and hits in one piece. Returns a shallow copy, leaving the input alone.
        """
        if not claude_messages:
            return claude_messages
        msgs = [dict(m) for m in claude_messages]
        last = msgs[-1]
        content = last["content"]
        if isinstance(content, str):
            if not content.strip():
                return msgs
            blocks = [{"type": "text", "text": content}]
        else:
            blocks = [dict(b) for b in content]
        if not blocks:
            return msgs
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
        last["content"] = blocks
        return msgs

    async def _invoke_once(
        self,
        *,
        system_blocks: list[str] | None,
        claude_messages: list[dict[str, Any]],
        temperature: float | None,
        cache: bool,
        tools_param: Any,
        tool_choice: ToolChoice | None = None,
        thinking_param: Any = anthropic.NOT_GIVEN,
        effort: Effort | None = None,
        want_json: bool = False,
        json_schema: dict | None = None,
        on_delta: OnDelta | None = None,
        **kwargs,
    ) -> ChatResponse:
        msgs = (
            self._with_rolling_breakpoint(claude_messages) if cache else claude_messages
        )
        # The call is streamed and reassembled into the one final message, so the
        # reply is read whole. The SDK refuses a non-streaming request at these
        # max_tokens, since minutes of silence while the model thinks look idle
        # to every proxy in the path. The timeout bounds time-to-finish, not
        # time-to-first-byte.
        async with self.client.messages.stream(
            model=self.model_name,
            max_tokens=self.max_tokens,
            messages=msgs,
            system=self._build_system_param(system_blocks, cache),
            temperature=(
                temperature if temperature is not None else anthropic.NOT_GIVEN
            ),
            tools=tools_param,
            tool_choice=self._convert_tool_choice(tool_choice),
            thinking=thinking_param,
            # effort rides inside output_config, not at the top level, and goes
            # out only when the caller asked for one: omitting it is the API's
            # own default (high) and leaves the request bytes unchanged, so the
            # cache entry survives.
            output_config=({"effort": _EFFORT[effort]} if effort is not None
                           else anthropic.NOT_GIVEN),
            **kwargs,
        ) as stream:
            # Walking the stream is what feeds a sink, and it costs the final
            # message nothing: the SDK accumulates into its snapshot on every
            # event, and get_final_message hands that same snapshot over.
            if on_delta is not None:
                async for ev in stream:
                    if ev.type != "content_block_delta":
                        continue
                    d = ev.delta
                    # The two readable deltas: input_json_delta is a tool call's
                    # arguments in pieces, signature_delta is not text at all.
                    if d.type == "text_delta":
                        feed(on_delta, "text", d.text)
                    elif d.type == "thinking_delta":
                        feed(on_delta, "thinking", d.thinking)
            response = await stream.get_final_message()
        self._check_stop_reason(response.stop_reason)
        content = self._extract_text(response)
        tool_calls = self._extract_tool_calls(response)
        # Judged from the tool_calls themselves, since a gateway may silently
        # drop tool_choice.
        if tool_choice is not None:
            tool_choice.verify_response(tool_calls)
        # Nothing came back, in two shapes. The whole of max_tokens can go on
        # thinking before a single output token is emitted; the service is fine
        # and has said why it stopped, so that is a format violation, which the
        # runner turns into a repair round. Any other empty reply is a gateway
        # returning a shell and stays fatal.
        if not content.strip() and not tool_calls:
            if response.stop_reason == "max_tokens":
                thought = self._extract_thinking(response) or ""
                e = OutputFormatViolation(
                    f"the whole output budget ({self.max_tokens} tokens) went on "
                    f"deliberation and the reply ended before any answer was "
                    f"written"
                    + (f" ({len(thought)} characters of thinking)" if thought else "")
                    + ". Answer directly this time: reach the product first and "
                    "keep the reasoning to what the answer needs.")
                e.usage = self._build_usage(response.usage)
                raise e
            raise RuntimeError(
                f"empty response from {self.model_name}: no text and no tool_use, "
                f"stop_reason={response.stop_reason}; treating the service as degraded"
            )
        # Only a final reply that calls no tools is validated: the body of a
        # round carrying tool_calls is usually narration, and checking it
        # against the schema would discard that whole batch of tool_calls.
        if content.strip() and not tool_calls:
            try:
                if json_schema is not None:
                    content = ensure_schema_valid(content, json_schema, self.model_name)
                elif want_json:
                    content = ensure_valid_json(content, self.model_name)
            except OutputFormatViolation as e:
                # The rejected reply cost tokens like any other, and only this
                # layer still holds the usage, so it travels on the exception
                # for the runner to record.
                e.usage = self._build_usage(response.usage)
                raise
        return ChatResponse(
            content=content,
            usage=self._build_usage(response.usage),
            tool_calls=tool_calls,
            thinking=self._extract_thinking(response),
            thinking_blocks=self._extract_thinking_blocks(response),
        )

    def _check_stop_reason(self, stop_reason: str | None) -> None:
        """Act on the stop reason. Only refusal raises; max_tokens is a warning,
        since the truncated text is still worth parsing."""
        if stop_reason == "refusal":
            raise RuntimeError(f"{self.model_name} refused to generate (stop_reason=refusal)")
        if stop_reason == "max_tokens":
            self.logger.warning(
                f"output hit max_tokens={self.max_tokens} on {self.model_name}; "
                f"the result may be truncated"
            )

    @staticmethod
    def _extract_text(response) -> str:
        """Text blocks only; thinking goes through ``_extract_thinking``."""
        return "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )

    @staticmethod
    def _extract_thinking(response) -> str | None:
        """Thinking block text, for the trace only. None when thinking is off or
        a gateway stripped it."""
        parts = [
            b.thinking
            for b in response.content
            if getattr(b, "type", None) == "thinking"
            and getattr(b, "thinking", None)
        ]
        return "\n\n".join(parts) or None

    @staticmethod
    def _extract_thinking_blocks(response) -> list[dict] | None:
        """Raw thinking blocks as plain dicts, for replay through
        ``ChatMessage.thinking_blocks``. Kept verbatim, signature included,
        because Anthropic requires them handed back unchanged in a multi-round
        tool loop; ``_replayable_thinking`` decides whether they go back."""
        blocks = [
            b.model_dump()
            for b in response.content
            if getattr(b, "type", None) in ("thinking", "redacted_thinking")
        ]
        return blocks or None

    @staticmethod
    def _extract_tool_calls(response) -> list[dict[str, Any]]:
        """tool_use blocks → the ``{id, type, name, arguments, arguments_json}``
        dict the OpenAI backend also produces, so callers see one convention
        across backends.
        """
        out: list[dict[str, Any]] = []
        for b in response.content:
            if getattr(b, "type", None) != "tool_use":
                continue
            args = b.input if isinstance(b.input, dict) else {}
            out.append({
                "id": b.id,
                "type": "function",
                "name": b.name,
                "arguments": json.dumps(args, ensure_ascii=False),
                "arguments_json": args,
            })
        return out

    @staticmethod
    def _build_usage(usage) -> TokenUsage:
        input_t = getattr(usage, "input_tokens", 0) or 0
        output_t = getattr(usage, "output_tokens", 0) or 0
        cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        # Anthropic's input_tokens excludes the cached part; add it back.
        total_input = input_t + cache_create + cache_read
        return TokenUsage(
            input_tokens=total_input,
            output_tokens=output_t,
            total_tokens=total_input + output_t,
            cached_tokens=cache_read,
            cache_creation_tokens=cache_create,
        )
