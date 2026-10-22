"""Remote chat client speaking OpenAI's ``/v1/chat/completions`` protocol, the
endpoint most third-party vendors and relays implement."""

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
    Effort, FunctionTool, OnDelta, ToolChoice, ToolChoiceMode,
)
from orrery.infra.llm.validation import (
    OutputFormatViolation,
    ensure_schema_valid,
    ensure_valid_json,
)


# Effort rung -> reasoning_effort. The scale stops at "high", so the two rungs
# above it saturate there and warn once.
_EFFORT: dict[Effort, str] = {
    Effort.LOW: "low",
    Effort.MEDIUM: "medium",
    Effort.HIGH: "high",
    Effort.VERY_HIGH: "high",
    Effort.MAX: "high",
}

# How much of a response may appear in an exception message.
_DESCRIBE_LIMIT = 500


class RemoteChatOpenAICompatible(RemoteChatClient):
    """Adapter for ``/v1/chat/completions``, spoken by DeepSeek, GLM, Grok, Qwen,
    vLLM, Ollama and the relays. Reasoning models belong on ``remote/openai.py``:
    this endpoint cannot carry vendor-private reasoning state across tool rounds,
    and from gpt-5.5 on it rejects ``tools`` together with a non-``none``
    ``reasoning_effort``."""

    # Hard timeout for one call, in seconds: past this asyncio cancels the call
    # and raises. A healthy call takes 30-90s. Retry policy belongs to the layer
    # above; this one never retries.
    _TIMEOUT = 300.0

    def __init__(
        self,
        api_key: str,
        model_name: str,
        url: str = None,
        extra_headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(model_name, api_key)
        self.logger = logging.getLogger(__name__)
        # config's llm.timeout_s; None keeps this backend's own default.
        self.timeout_s = float(timeout_s or self._TIMEOUT)
        # One run makes hundreds of requests, so this warning is logged once.
        self._effort_warned = False
        # The SDK timeout is only a backstop; the hard limit is the
        # asyncio.wait_for in invoke. extra_headers come from config and
        # override the SDK's own defaults of the same name.
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=url,
            timeout=self.timeout_s,
            max_retries=0,
            default_headers=extra_headers,
        )

    async def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[FunctionTool] | None = None,
        tool_choice: ToolChoice | None = None,
        temperature: float | None = None,   # None: not sent, use the model default
        response_format: str | None = None,
        json_schema: dict | None = None,
        effort: Effort | None = None,
        # Accepted and ignored: streaming here splits tool calls into fragments
        # the caller must reassemble, and drops usage entirely unless
        # stream_options.include_usage is honoured, which relays often skip.
        on_delta: OnDelta | None = None,
        **kwargs,
    ) -> ChatResponse:
        if effort is not None:
            sent = _EFFORT[effort]
            if sent != effort.value:
                self._warn_effort_saturated(effort, sent)
            kwargs["reasoning_effort"] = sent
        response_format_obj = self._get_response_format(response_format, json_schema)
        openai_messages = self._build_openai_messages(messages)
        tools_dict = self._convert_tools(tools)
        if tool_choice is not None:
            tool_choice.validate_against(tools)
        # Sent only on request: some compatible endpoints reject the parameter,
        # and seeded determinism is best effort at most anyway.
        seed = kwargs.pop("seed", None)

        # One call under a hard timeout: running out of it means the service is
        # stuck, which raises at once rather than waiting it out.
        try:
            return await asyncio.wait_for(
                self._invoke_once(
                    openai_messages, tools_dict, temperature, seed,
                    response_format_obj, tool_choice, response_format,
                    json_schema, kwargs,
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
        self, openai_messages, tools_dict, temperature, seed,
        response_format_obj, tool_choice, response_format, json_schema, kwargs,
    ) -> ChatResponse:
        """One LLM call plus parsing, for invoke to wrap in a hard timeout."""
        tc_param, parallel_param = self._convert_tool_choice(tool_choice)
        response = await self.client.chat.completions.create(
            messages=openai_messages,
            model=self.model_name,
            stream=False,
            # None must become Omit: sending "temperature": null makes some
            # OpenAI-compatible endpoints answer 400.
            temperature=temperature if temperature is not None else Omit(),
            seed=seed if seed is not None else Omit(),
            response_format=response_format_obj,
            tools=tools_dict,
            tool_choice=tc_param,
            parallel_tool_calls=parallel_param,
            **kwargs,
        )
        # A failing proxy often returns an error body as a bare string or dict
        # with no choices, so the real error is surfaced before .choices or
        # _extract_usage bury it under an unrelated AttributeError.
        self._raise_if_api_error(response)
        if not getattr(response, "choices", None):
            raise RuntimeError(
                f"No choices returned from {self.model_name}; "
                f"raw response: {self._describe_response(response)}"
            )
        choice = response.choices[0]
        self._check_finish_reason(choice.finish_reason)
        tool_calls = self._extract_tool_calls(choice.message)
        # Whether the forcing setting took effect is judged from tool_calls
        # themselves, since a gateway may silently drop tool_choice.
        if tool_choice is not None:
            tool_choice.verify_response(tool_calls)
        # A valid response carries content or tool_calls; both empty means a
        # degraded service, and content="" would read as a legitimate result.
        content = choice.message.content or ""
        if not content.strip() and not tool_calls:
            raise RuntimeError(
                f"empty response from {self.model_name}: choices present but content "
                f"empty and no tool_calls; treating the service as degraded. "
                f"raw response: {self._describe_response(response)}"
            )
        # Re-checked locally (infra/llm/validation.py) because a relay may have
        # swallowed the parameter. Only a final reply that calls no tools is
        # validated: the body of a tool_calls round is narration, and validating
        # it would flag a bogus violation and discard the whole batch.
        if content.strip() and not tool_calls:
            try:
                if json_schema is not None:
                    content = ensure_schema_valid(content, json_schema, self.model_name)
                elif response_format == "json":
                    content = ensure_valid_json(content, self.model_name)
            except OutputFormatViolation as e:
                # The rejected reply cost tokens, and only this layer holds the
                # usage, so it rides the exception out to the runner.
                e.usage = self._extract_usage(response)
                raise
        usage = self._extract_usage(response)
        # Some backends (DeepSeek-R1, thinking models behind a gateway) put
        # thinking text in reasoning_content. For the trace only, never replayed.
        thinking = getattr(choice.message, "reasoning_content", None) or None
        return ChatResponse(
            content=content,
            usage=usage,
            tool_calls=tool_calls,
            thinking=thinking,
        )

    def _build_openai_messages(
        self,
        messages: list[ChatMessage],
    ) -> list[Any]:
        """Convert ChatMessage into OpenAI's wire message list.

        Raises RuntimeError on an unsupported role, or on a TOOL message with no
        tool_call_id.
        """
        openai_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                # A list is one prompt pre-split at cache breakpoints; OpenAI's
                # prefix caching is automatic, so the blocks are just joined.
                content = ("\n\n".join(msg.content)
                           if isinstance(msg.content, list) else msg.content)
                openai_messages.append({"role": "system", "content": content})

            elif msg.role == Role.USER:
                openai_messages.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": tc["name"],
                                "arguments": tc.get("arguments")
                                or json.dumps(tc.get("arguments_json") or {}),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                    # OpenAI requires content to be null or a string when
                    # tool_calls are present.
                    assistant_msg["content"] = msg.content or ""
                else:
                    assistant_msg["content"] = msg.content
                openai_messages.append(assistant_msg)

            elif msg.role == Role.TOOL:
                if not msg.tool_call_id:
                    raise RuntimeError(
                        "TOOL message must carry tool_call_id matching the "
                        "originating assistant tool_call."
                    )
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )

            else:
                raise RuntimeError(f"Unsupported role: {msg.role}")

        return openai_messages

    @staticmethod
    def _convert_tools(tools: list[FunctionTool] | None) -> list[dict[str, Any]] | Omit:
        """Convert FunctionTool objects into OpenAI's tools array, or Omit when
        there are none."""
        if not tools:
            return Omit()

        return [tool.to_dict() for tool in tools]

    @staticmethod
    def _convert_tool_choice(tc: ToolChoice | None) -> tuple[Any, Any]:
        """``ToolChoice`` → the pair (tool_choice, parallel_tool_calls), Omit for
        whichever is unset. Forcing a tool makes OpenAI report finish_reason
        "stop" rather than "tool_calls", so whether a tool ran is judged from the
        tool_calls themselves (``ToolChoice.verify_response``)."""
        if tc is None:
            return Omit(), Omit()
        parallel = False if tc.disable_parallel else Omit()
        match tc.mode:
            case ToolChoiceMode.AUTO:
                choice: Any = Omit()   # the default is not sent at all
            case ToolChoiceMode.REQUIRED:
                choice = "required"
            case ToolChoiceMode.NONE:
                choice = "none"
            case ToolChoiceMode.TOOL:
                choice = {"type": "function", "function": {"name": tc.tool_name}}
        return choice, parallel

    def _check_finish_reason(self, finish_reason: str | None) -> None:
        """Act on finish_reason: None / "stop" / "tool_calls" are normal,
        "length" (truncated at max_tokens) and any unknown value warn, and
        "content_filter" raises RuntimeError."""
        if finish_reason in (None, "stop", "tool_calls"):
            return

        if finish_reason == "length":
            self.logger.warning(
                f"{self.model_name} response truncated due to max token length"
            )
            return

        if finish_reason == "content_filter":
            raise RuntimeError(
                f"Response blocked by content filter in {self.model_name}"
            )

        self.logger.warning(
            f"Unexpected finish_reason from {self.model_name}: {finish_reason}"
        )

    def _warn_effort_saturated(self, effort: Effort, sent: str) -> None:
        """Log once, and only when a rung was actually flattened onto this
        backend's top reasoning_effort. The two highest rungs are
        indistinguishable here, which is a fact about the run, not the
        transport."""
        if self._effort_warned:
            return
        self._effort_warned = True
        self.logger.warning(
            f"effort saturated for {self.model_name}: the caller asked for "
            f"{effort.value!r}, and this backend's reasoning_effort stops at "
            f"{sent!r}, so that is what was sent. Rungs above it are "
            f"indistinguishable here; only the remote-claude backend separates "
            f"them."
        )

    @staticmethod
    def _extract_tool_calls(message) -> list[dict[str, Any]]:
        """Extract every tool call as a dict with id, type, name, arguments (the
        raw JSON string) and arguments_json (the parsed dict, or None when the
        arguments do not parse)."""
        raw_tool_calls = getattr(message, "tool_calls", None)
        if not raw_tool_calls:
            return []

        tool_calls = []
        for call in raw_tool_calls:
            function = getattr(call, "function", None)

            args_raw = getattr(function, "arguments", None) if function else None

            # Unparseable arguments stay as the raw string; the caller decides.
            args_json = None
            if args_raw:
                try:
                    args_json = json.loads(args_raw)
                except json.JSONDecodeError:
                    pass

            tool_calls.append(
                {
                    "id": getattr(call, "id", None),
                    "type": getattr(call, "type", "function"),
                    "name": getattr(function, "name", None) if function else None,
                    "arguments": args_raw,
                    "arguments_json": args_json,
                }
            )

        return tool_calls

    @staticmethod
    def _raise_if_api_error(response: Any) -> None:
        """Raise the real error when the upstream or a proxy put it inside the
        response body — HTTP 200 with an error field, or the error body returned
        as a bare string — instead of letting the later .choices or usage
        extraction bury it under an unrelated AttributeError."""
        # A proxy may return the whole error body as a string, including an SSE
        # stream of `data: {...}` lines with a bare `{"error":...}` at the end.
        if isinstance(response, str):
            err = RemoteChatOpenAICompatible._scan_error_in_text(response)
            if err is not None:
                raise RuntimeError(f"Upstream API error: {err}")
            raise RuntimeError(f"Upstream API returned a raw string: {response}")

        error = getattr(response, "error", None)
        if error is None and isinstance(response, dict):
            error = response.get("error")
        if not error:
            return
        raise RuntimeError(f"Upstream API error: {RemoteChatOpenAICompatible._error_message(error)}")

    @staticmethod
    def _scan_error_in_text(text: str) -> str | None:
        """Collect the message of every JSON fragment carrying an ``error`` field
        from text that may be an SSE stream or concatenated JSON, deduplicated
        and joined with ` | `; None when there is none. All fragments are kept
        because proxies often append a second-order symptom while the real cause
        sits in an earlier one."""
        messages: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[len("data:"):].strip()
            if not line or line == "[DONE]" or not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("error"):
                msg = RemoteChatOpenAICompatible._error_message(payload["error"])
                if msg and msg not in messages:
                    messages.append(msg)
        if not messages:
            return None
        return " | ".join(messages)

    @staticmethod
    def _error_message(error: Any) -> str:
        """Take the human-readable message out of an error object or dict,
        falling back to the whole thing."""
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(getattr(error, "message", None) or error)

    @staticmethod
    def _describe_response(response: Any) -> str:
        """A short textual form of the response, for diagnostics, truncated at
        _DESCRIBE_LIMIT: it lands in an exception message and the log, where a
        full dump of a long reply would be thousands of characters."""
        try:
            if hasattr(response, "model_dump_json"):
                text = response.model_dump_json()
            else:
                text = str(response)
        except Exception:
            text = repr(response)
        return text if len(text) <= _DESCRIBE_LIMIT else (
            f"{text[:_DESCRIBE_LIMIT]}… (+{len(text) - _DESCRIBE_LIMIT} chars)"
        )

    @staticmethod
    def _extract_usage(response: Any) -> TokenUsage:
        """Extract token usage, all zeros when the response carries none."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return TokenUsage(
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cached_tokens=0,
            )
        details = getattr(usage, "prompt_tokens_details", None)

        cached_tokens = 0
        if details:
            cached_tokens = getattr(details, "cached_tokens", 0)
            if cached_tokens is None:
                cached_tokens = 0

        # A relay may leave a field out, which the SDK reads as None rather
        # than raising; zero then, as the other three adapters count it, so a
        # reply that was paid for is not lost over its accounting.
        return TokenUsage(
            input_tokens=usage.prompt_tokens or 0,
            output_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
            cached_tokens=cached_tokens,
        )

    @staticmethod
    def _get_response_format(
        response_format: str | None, json_schema: dict | None = None
    ):
        """Return Omit for None / "json" / a json_schema, and raise RuntimeError
        on anything else. The API parameter is never sent: both intents are
        enforced locally after the reply (ensure_schema_valid, ensure_valid_json),
        because ``json_object`` mode forces every assistant turn to be JSON and
        makes the model serialize its tool calls into the body."""
        if response_format in (None, "json") or json_schema is not None:
            return Omit()
        raise RuntimeError(
            f"unknown response_format intent {response_format!r} "
            "(only None / 'json' accepted)"
        )
