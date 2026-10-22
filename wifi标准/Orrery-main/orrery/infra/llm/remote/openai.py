import asyncio
import json
import logging
from typing import Any

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, Omit

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


# Effort rung -> reasoning.effort; the two top rungs both saturate at "high".
_EFFORT: dict[Effort, str] = {
    Effort.LOW: "low",
    Effort.MEDIUM: "medium",
    Effort.HIGH: "high",
    Effort.VERY_HIGH: "high",
    Effort.MAX: "high",
}

# Streaming event type -> the kind of fragment it carries. Matched on the wire
# string rather than the SDK class, so a delta event this map does not know is
# ignored instead of crashing the read loop.
_DELTA_KINDS = {
    "response.output_text.delta": "text",
    "response.reasoning_summary_text.delta": "thinking",
    "response.reasoning_text.delta": "thinking",
}

# Item types this adapter replays verbatim from a previous reply.
_REPLAYED_ITEM_TYPES = ("reasoning",)


class RemoteChatOpenAI(RemoteChatClient):
    """OpenAI adapter speaking OpenAI's own ``/v1/responses``.

    Modern GPT models reject ``tools`` on ``/v1/chat/completions`` together with
    a non-``none`` reasoning effort, and the agent loop sends tools every round,
    so this is the only path where reasoning and tools coexist. Differences from
    ``openai_compatible.py``: ``input`` is a flat item list paired by
    ``call_id`` (an assistant turn is a message item plus sibling
    ``function_call`` items, a tool result is a ``function_call_output``); tools
    are flat rather than nested under ``"function"``; there is no ``seed``; and
    completion is a ``status`` rather than a ``finish_reason``. Reasoning items
    come back carrying ``encrypted_content`` and must go back inside ``input``
    on the next round or the model reasons from scratch, which is why the
    request sends ``store=False`` with ``include=["reasoning.encrypted_content"]``
    and the items ride in ``ChatResponse.thinking_blocks``.
    ``response_format="json"`` and ``json_schema`` are checked locally after the
    reply, never forced API-side.
    """

    # No response for this long means the service is unavailable; retry is the
    # layer above's policy, so this one fails immediately.
    _TIMEOUT = 300.0

    def __init__(
        self,
        api_key: str,
        model_name: str,
        url: str | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(model_name, api_key)
        self.logger = logging.getLogger(__name__)
        # config's llm.timeout_s; None keeps this backend's own default.
        self.timeout_s = float(timeout_s or self._TIMEOUT)
        # Warn-once flags: one run makes hundreds of requests.
        self._effort_warned = False
        self._temperature_warned = False
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=url,
            timeout=self.timeout_s,
            max_retries=0,   # this layer promises to fail immediately
            default_headers=extra_headers,
        )

    async def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[FunctionTool] | None = None,
        tool_choice: ToolChoice | None = None,
        temperature: float | None = None,   # None = do not send it, use the default
        response_format: str | None = None,
        json_schema: dict | None = None,
        effort: Effort | None = None,
        on_delta: OnDelta | None = None,
        **kwargs,
    ) -> ChatResponse:
        if response_format not in (None, "json"):
            raise RuntimeError(
                f"unknown response_format intent {response_format!r} "
                "(only None / 'json' accepted)"
            )
        if tool_choice is not None:
            tool_choice.validate_against(tools)
        if temperature is not None:
            self._warn_temperature_dropped(temperature)
            temperature = None

        # summary="auto" asks for the readable account of the reasoning, sent on
        # every request: the reasoning happens and is billed as output either
        # way, and asking costs no extra tokens. Without it the reasoning item
        # comes back with `summary: []` — encrypted_content for replay, nothing
        # a person can read — and `thinking` is always None. A model with no
        # reasoning to summarise ignores the field.
        reasoning: Any = {"summary": "auto"}
        if effort is not None:
            sent = _EFFORT[effort]
            if sent != effort.value:
                self._warn_effort_saturated(effort, sent)
            reasoning["effort"] = sent

        try:
            return await asyncio.wait_for(
                self._invoke_once(
                    input_items=self._build_input(messages),
                    tools_param=self._convert_tools(tools),
                    tool_choice=tool_choice,
                    temperature=temperature,
                    reasoning=reasoning,
                    want_json=response_format == "json",
                    json_schema=json_schema,
                    on_delta=on_delta,
                    kwargs=kwargs,
                ),
                timeout=self.timeout_s,
            )
        except (asyncio.TimeoutError, APITimeoutError) as e:
            msg = (
                f"LLM timed out: {self.model_name} gave no response in "
                f"{self.timeout_s:.0f}s ({type(e).__name__}); treating the "
                f"service as unavailable — check the model service or proxy"
            )
            self.logger.error(msg)
            raise RuntimeError(msg) from e
        except APIConnectionError as e:
            # Split out of the branch above, which reported it as a timeout that
            # never happened: a dropped connection returns in seconds, so
            # "no response in 600s" sent every investigation at the wrong thing.
            # Must stay below it — APITimeoutError is a subclass of this one.
            msg = (
                f"{self.model_name} connection failed ({type(e).__name__}: {e}); "
                f"treating the service as unavailable — the connection dropped, "
                f"no timeout was reached"
            )
            self.logger.error(msg)
            raise RuntimeError(msg) from e
        except Exception as e:
            self.logger.error(f"Failed to dialogue with {self.model_name}. {e}")
            raise

    async def _invoke_once(
        self, *, input_items, tools_param, tool_choice, temperature, reasoning,
        want_json, json_schema, on_delta=None, kwargs,
    ) -> ChatResponse:
        """One call plus parsing, for invoke to wrap in a hard timeout."""
        tc_param, parallel_param = self._convert_tool_choice(tool_choice)
        # Streamed whether or not a sink was given: a reasoning request that
        # emits nothing for minutes looks idle to every proxy in the path.
        # get_final_response hands over the server's own `response.completed`
        # payload, byte for byte what create() would have returned.
        async with self.client.responses.stream(
            model=self.model_name,
            input=input_items,
            tools=tools_param,
            tool_choice=tc_param,
            parallel_tool_calls=parallel_param,
            reasoning=reasoning,
            # store=False keeps the conversation here rather than on OpenAI's
            # servers; include= is what makes the reasoning replayable in that
            # mode, so the two travel together.
            store=False,
            include=["reasoning.encrypted_content"],
            temperature=temperature if temperature is not None else Omit(),
            **kwargs,
        ) as stream:
            if on_delta is not None:
                async for ev in stream:
                    kind = _DELTA_KINDS.get(getattr(ev, "type", None))
                    if kind is not None:
                        feed(on_delta, kind, getattr(ev, "delta", None))
            try:
                response = await stream.get_final_response()
            except RuntimeError as e:
                # The SDK's wording is "Didn't receive a `response.completed`
                # event", which means the SSE connection ended early — through a
                # relay, the ordinary shape of an upstream giving up.
                raise RuntimeError(
                    f"{self.model_name} closed the stream before completing it "
                    f"({e}); treating the service as degraded — a relay that "
                    f"truncates SSE is the usual cause"
                ) from e
        self._raise_if_api_error(response)
        self._check_status(response)

        content, thinking, tool_calls, thinking_blocks = self._extract_output(response)
        # Judged from tool_calls themselves: a gateway may silently drop
        # tool_choice.
        if tool_choice is not None:
            tool_choice.verify_response(tool_calls)
        # Neither text nor tool calls means the upstream returned a shell;
        # content="" would reach the caller as a real empty result.
        if not content.strip() and not tool_calls:
            raise RuntimeError(
                f"empty response from {self.model_name}: no output text and no "
                f"function_call; treating the service as degraded. "
                f"raw response: {self._describe_response(response)}"
            )
        # Only a final reply that calls no tools is validated: the body of a
        # round carrying tool_calls is usually narration, and checking it would
        # raise a format violation over text that was never the answer.
        if content.strip() and not tool_calls:
            try:
                if json_schema is not None:
                    content = ensure_schema_valid(content, json_schema, self.model_name)
                elif want_json:
                    content = ensure_valid_json(content, self.model_name)
            except OutputFormatViolation as e:
                # The rejected reply cost tokens, and only this layer still
                # holds the usage, so it travels on the exception.
                e.usage = self._extract_usage(response)
                raise
        return ChatResponse(
            content=content,
            usage=self._extract_usage(response),
            tool_calls=tool_calls,
            thinking=thinking,
            thinking_blocks=thinking_blocks,
        )

    # ------------------------------------------------------------------ #
    # Request building
    # ------------------------------------------------------------------ #
    def _build_input(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        """``ChatMessage`` list → Responses' flat ``input`` item list.

        One ASSISTANT message becomes several sibling items in the order they
        came back: its reasoning items, its text, then one ``function_call`` per
        tool call. A TOOL message becomes a ``function_call_output`` paired by
        ``call_id``. Raises RuntimeError on an empty assistant turn, a TOOL
        message with no ``tool_call_id``, or an unsupported role.
        """
        items: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                # A list is one prompt pre-split at cache-breakpoint boundaries
                # (see ChatMessage.content). OpenAI's prefix caching is
                # automatic, so the blocks are simply joined.
                content = ("\n\n".join(msg.content)
                           if isinstance(msg.content, list) else msg.content)
                items.append({"role": "system", "content": content})

            elif msg.role == Role.USER:
                items.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                # Reasoning first: an item replayed out of order is not the reply
                # the model produced. Unrecognised blocks are skipped rather
                # than raising, so a transcript written by another backend
                # replays as a round that reasoned from scratch.
                for block in msg.thinking_blocks or []:
                    if isinstance(block, dict) and block.get("type") in _REPLAYED_ITEM_TYPES:
                        items.append(dict(block))
                if msg.content and msg.content.strip():
                    items.append({"role": "assistant", "content": msg.content})
                for tc in msg.tool_calls or []:
                    items.append({
                        "type": "function_call",
                        "call_id": tc["id"],
                        "name": tc["name"],
                        "arguments": (tc.get("arguments")
                                      or json.dumps(tc.get("arguments_json") or {})),
                    })
                if not (msg.thinking_blocks or msg.content or msg.tool_calls):
                    raise RuntimeError(
                        "ASSISTANT message has neither content nor tool_calls."
                    )

            elif msg.role == Role.TOOL:
                if not msg.tool_call_id:
                    raise RuntimeError(
                        "TOOL message must carry tool_call_id matching the "
                        "originating assistant tool_call."
                    )
                items.append({
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id,
                    "output": msg.content,
                })

            else:
                raise RuntimeError(f"Unsupported role: {msg.role}")

        return items

    @staticmethod
    def _convert_tools(tools: list[FunctionTool] | None) -> list[dict[str, Any]] | Omit:
        """``FunctionTool`` → Responses' flat tool shape.

        This API takes name and parameters at the top level, without Chat
        Completions' nesting under ``"function"``, so ``FunctionTool.to_dict()``
        does not fit here. Returns ``Omit()`` when there are no tools.
        """
        if not tools:
            return Omit()
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.schema(),
                "strict": t.strict,
            }
            for t in tools
        ]

    @staticmethod
    def _convert_tool_choice(tc: ToolChoice | None) -> tuple[Any, Any]:
        """``ToolChoice`` → (tool_choice, parallel_tool_calls).

        Forbidding parallel calls is a separate top-level parameter, hence the
        pair. The TOOL shape is flat: ``{"type": "function", "name": …}``.
        """
        if tc is None:
            return Omit(), Omit()
        parallel = False if tc.disable_parallel else Omit()
        match tc.mode:
            case ToolChoiceMode.AUTO:
                choice: Any = Omit()   # the default is not sent
            case ToolChoiceMode.REQUIRED:
                choice = "required"
            case ToolChoiceMode.NONE:
                choice = "none"
            case ToolChoiceMode.TOOL:
                choice = {"type": "function", "name": tc.tool_name}
        return choice, parallel

    # ------------------------------------------------------------------ #
    # Response parsing
    # ------------------------------------------------------------------ #
    def _check_status(self, response: Any) -> None:
        """``completed`` is normal; ``incomplete`` warns on truncation and
        raises on a content filter; ``failed`` raises with the upstream's own
        error. Any other status is logged as a warning."""
        status = getattr(response, "status", None)
        if status in (None, "completed"):
            return
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None)
        if status == "incomplete" and reason == "max_output_tokens":
            self.logger.warning(
                f"{self.model_name} response truncated at max_output_tokens"
            )
            return
        if status == "incomplete" and reason == "content_filter":
            raise RuntimeError(
                f"Response blocked by content filter in {self.model_name}"
            )
        if status == "failed":
            error = getattr(response, "error", None)
            raise RuntimeError(
                f"{self.model_name} failed: {self._error_message(error)}"
            )
        self.logger.warning(
            f"Unexpected status from {self.model_name}: {status} (reason={reason})"
        )

    @staticmethod
    def _extract_output(
        response: Any,
    ) -> tuple[str, str | None, list[dict[str, Any]], list[dict] | None]:
        """Walk ``response.output`` once, splitting it four ways: message text,
        the readable reasoning summary, tool calls, and the reasoning items to
        replay.

        Tool calls use the unified shape shared with the other adapters, with
        ``id`` holding Responses' ``call_id`` — what a ``function_call_output``
        pairs against.
        """
        texts: list[str] = []
        summaries: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        replay: list[dict] = []

        for item in getattr(response, "output", None) or []:
            kind = getattr(item, "type", None)
            if kind == "message":
                for part in getattr(item, "content", None) or []:
                    text = getattr(part, "text", None)
                    if text:
                        texts.append(text)
            elif kind == "function_call":
                raw = getattr(item, "arguments", None)
                args_json = None
                if raw:
                    try:
                        args_json = json.loads(raw)
                    except json.JSONDecodeError:
                        pass
                tool_calls.append({
                    "id": getattr(item, "call_id", None),
                    "type": "function",
                    "name": getattr(item, "name", None),
                    "arguments": raw,
                    "arguments_json": args_json,
                })
            elif kind in _REPLAYED_ITEM_TYPES:
                for part in getattr(item, "summary", None) or []:
                    text = getattr(part, "text", None)
                    if text:
                        summaries.append(text)
                # Kept whole and opaque: the model_dump is what goes back into
                # input, and this adapter does not interpret its fields.
                replay.append(item.model_dump(exclude_none=True))
            else:
                # An item shape this adapter does not read is indistinguishable
                # downstream from the service returning nothing, and the two
                # need opposite fixes.
                logging.getLogger(__name__).warning(
                    "output item of type %r ignored: this adapter reads "
                    "message, function_call and %s", kind,
                    ", ".join(_REPLAYED_ITEM_TYPES))

        return (
            "".join(texts),
            ("\n\n".join(summaries) or None),
            tool_calls,
            replay or None,
        )

    @staticmethod
    def _extract_usage(response: Any) -> TokenUsage:
        """Responses' usage counters → TokenUsage. They are named
        input_tokens / output_tokens rather than prompt_ / completion_, the
        cache hit sits under input_tokens_details, and reasoning tokens are
        billed as output and already counted inside output_tokens."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return TokenUsage(
                input_tokens=0, output_tokens=0, total_tokens=0, cached_tokens=0,
            )
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details else 0
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=(getattr(usage, "total_tokens", 0) or 0)
                         or (input_tokens + output_tokens),
            cached_tokens=cached or 0,
        )

    def _warn_temperature_dropped(self, temperature: float) -> None:
        """Warn once that temperature was dropped; this adapter never sends it.

        Not gated on a model list: with the ``include`` this adapter always
        sends, some GPT families reject ``temperature`` outright while the rest
        accept it and silently ignore it, and the split does not follow version
        order. A caller that needs sampling control wants the compatible
        adapter, which still passes it through.
        """
        if self._temperature_warned:
            return
        self._temperature_warned = True
        self.logger.warning(
            f"temperature dropped for {self.model_name}: this adapter never "
            f"sends it, because the reasoning families reject it outright and "
            f"the rest ignore it silently; requested temperature={temperature}, "
            f"sending none and using the model default. For a model where "
            f"temperature really works, use the remote-openai-compatible backend."
        )

    def _warn_effort_saturated(self, effort: Effort, sent: str) -> None:
        """Warn once, and only when a rung was actually flattened. The two top
        rungs both land on "high" here, so a run that distinguishes them
        elsewhere does not on this backend."""
        if self._effort_warned:
            return
        self._effort_warned = True
        self.logger.warning(
            f"effort saturated for {self.model_name}: the caller asked for "
            f"{effort.value!r}, and this backend's reasoning effort stops at "
            f"{sent!r}, so that is what was sent. Rungs above it are "
            f"indistinguishable here; only the remote-claude backend separates "
            f"them."
        )

    # ------------------------------------------------------------------ #
    # Upstream / relay error surfacing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _raise_if_api_error(response: Any) -> None:
        """Raise on an error carried inside an HTTP 200 body, a relay habit; the
        body is sometimes a bare string. Surfaces the real error before
        ``.output`` raises an unrelated AttributeError over it."""
        if isinstance(response, str):
            raise RuntimeError(f"Upstream API returned a raw string: {response}")
        error = getattr(response, "error", None)
        if error is None and isinstance(response, dict):
            error = response.get("error")
        # A completed response may still carry error=None; only a populated one
        # is a failure. `status: failed` is _check_status's business.
        if not error:
            return
        raise RuntimeError(
            f"Upstream API error: {RemoteChatOpenAI._error_message(error)}"
        )

    @staticmethod
    def _error_message(error: Any) -> str:
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(getattr(error, "message", None) or error)

    @staticmethod
    def _describe_response(response: Any) -> str:
        """Describe what came back, for the empty-response raise.

        Reports the envelope's verdict fields, the counters, and one line per
        output item naming its type — enough to separate "the service degraded"
        from "this adapter did not read what it was sent". Ciphertext is given
        as a length and never quoted, so the string's size follows the item
        count rather than the size of the reply.
        """
        parts = [f"status={getattr(response, 'status', None)!r}"]
        details = getattr(response, "incomplete_details", None)
        if details is not None:
            parts.append(f"incomplete={getattr(details, 'reason', None)!r}")
        err = getattr(response, "error", None)
        if err is not None:
            parts.append(f"error={getattr(err, 'message', None) or err!r}")
        usage = getattr(response, "usage", None)
        if usage is not None:
            out_details = getattr(usage, "output_tokens_details", None)
            parts.append(
                f"tokens in={getattr(usage, 'input_tokens', None)} "
                f"out={getattr(usage, 'output_tokens', None)} "
                f"reasoning={getattr(out_details, 'reasoning_tokens', None)}")
        items = list(getattr(response, "output", None) or [])
        if not items:
            parts.append("output: no items at all")
        for item in items:
            kind = getattr(item, "type", None)
            if kind == "message":
                n = sum(len(getattr(p, "text", "") or "")
                        for p in getattr(item, "content", None) or [])
                parts.append(f"output.message {n} char(s) of text")
            elif kind == "function_call":
                parts.append(
                    f"output.function_call {getattr(item, 'name', None)!r}")
            elif kind in _REPLAYED_ITEM_TYPES:
                enc = getattr(item, "encrypted_content", None) or ""
                parts.append(
                    f"output.{kind} "
                    f"{len(getattr(item, 'summary', None) or [])} summary "
                    f"part(s), {len(enc)} char(s) encrypted")
            else:
                # An item shape this adapter drops, which would otherwise read
                # as the service's fault.
                parts.append(f"output.{kind} — this adapter does not read it")
        return "; ".join(parts)
