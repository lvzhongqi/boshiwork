"""Unified chat interface: the message and tool types, plus the backend protocol
every adapter implements.

``thinking`` on ChatMessage and ChatResponse is optional trace text, None when
the backend or gateway drops it; ``thinking_blocks`` is the provider-native
opaque payload behind it, read back only by the adapter that produced it.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Called once per streamed fragment as ``on_delta(kind, text)``, where kind is
#: ``"thinking"`` or ``"text"``. A sink runs inside the adapter's read loop, so
#: blocking there stalls the download; anything it raises the adapter catches.
#: Fragments are droppable: the complete reply comes back in the ChatResponse.
OnDelta = Callable[[str, str], None]


def feed(sink: "OnDelta | None", kind: str, text: str | None) -> None:
    """Hand one fragment to the sink, swallowing anything it raises.

    Adapters call this from inside the read loop, where a raising sink would
    otherwise take down a reply the model produced fine. Empty fragments and a
    None sink are dropped here, so no adapter checks for them.
    """
    if sink is None or not text:
        return
    try:
        sink(kind, text)
    except Exception:                     # noqa: BLE001 — see the docstring
        logging.getLogger(__name__).debug("delta sink raised; fragment dropped",
                                          exc_info=True)


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ChatMessage:
    role: Role
    # A SYSTEM message may carry a list of blocks instead of one string: one
    # prompt split where a prefix-cache breakpoint belongs. Backends without
    # block-level caching join them with a blank line, so the split never
    # changes the visible prompt. Every other role carries a plain string.
    content: str | list[str] = ""
    # On an ASSISTANT message, the tool calls the model made (same shape as
    # ChatResponse.tool_calls), for replay in a multi-round loop.
    tool_calls: list[dict] | None = None
    # A TOOL message pairs with the assistant tool_call that started it, which
    # the OpenAI protocol requires.
    tool_call_id: str | None = None
    # An ASSISTANT message's thinking text, for reading traces back. Replaying
    # history goes through thinking_blocks; adapters never send this field.
    thinking: str | None = None
    # Provider-native opaque payload behind the thinking text (module
    # docstring). Only the adapter that produced it reads it back.
    thinking_blocks: list[dict] | None = None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # The part served from cache, billed at 0.1x.
    cached_tokens: int = 0
    # Tokens written to cache, billed at 1.25x. Separate from cached_tokens
    # because only the two together say whether caching paid off.
    cache_creation_tokens: int = 0


@dataclass
class ChatResponse:
    content: str
    usage: TokenUsage
    tool_calls: list[dict] = field(default_factory=list)
    # The model's thinking text; None when the backend or gateway does not
    # provide it. The trace layer writes it out verbatim.
    thinking: str | None = None
    # Provider-native opaque payload behind the thinking text (module
    # docstring). None on backends whose protocol returns nothing replayable
    # (OpenAI Chat Completions) and when a gateway strips the blocks.
    thinking_blocks: list[dict] | None = None


@dataclass
class FunctionParameter:
    """One parameter's definition, in the subset of JSON Schema that every
    provider supports."""

    type: str | list[str]
    description: str | None = None
    enum: list[str] | None = None
    pattern: str | None = None
    items: dict[str, Any] | None = None  # for array type
    properties: dict[str, "FunctionParameter"] | None = None  # for object type
    required: list[str] | None = None  # for object type
    additionalProperties: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.description is not None:
            result["description"] = self.description
        if self.enum is not None:
            result["enum"] = self.enum
        if self.pattern is not None:
            result["pattern"] = self.pattern
        if self.items is not None:
            result["items"] = self.items
        if self.properties is not None:
            result["properties"] = {k: v.to_dict() for k, v in self.properties.items()}
        if self.required is not None:
            result["required"] = self.required
        if isinstance(self.type, str) and self.type == "object":
            result["additionalProperties"] = self.additionalProperties
        return result


@dataclass
class FunctionTool:
    """One function tool: name, description, JSON Schema arguments, and the
    strict flag."""

    name: str
    description: str
    # Either the provider-independent parameter tree or a JSON Schema dict
    # already in hand (a node's submission schema is authored as a dict).
    # ``schema()`` is the one place that difference is absorbed, so no backend
    # ever sees it.
    parameters: FunctionParameter | dict
    strict: bool = True

    def schema(self) -> dict[str, Any]:
        return (self.parameters if isinstance(self.parameters, dict)
                else self.parameters.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema(),
                "strict": self.strict,
            },
        }


class Effort(str, Enum):
    """How much reasoning one call is worth: an ordinal rung that belongs to no
    provider, which each adapter maps to its own knob. A provider with a coarser
    scale saturates at its top rung and logs the first time it does, since
    flattening VERY_HIGH and MAX into one setting is a fact about the experiment.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
    MAX = "max"


class ToolChoiceMode(str, Enum):
    """The four settings of tool_choice, provider independent."""

    AUTO = "auto"          # the model decides (the default, same as not sending it)
    REQUIRED = "required"  # this round must call at least one tool
    TOOL = "tool"          # this round must call the named tool
    NONE = "none"          # no tools this round, text output only


@dataclass(frozen=True)
class ToolChoice:
    """Provider-independent tool_choice intent: whether this round must call a
    tool, and which one. Each backend translates it to its own wire shape and
    calls both checks here, ``validate_against`` before sending and
    ``verify_response`` after the reply, since some gateways return no 400 for an
    unknown tool name and others drop tool_choice without saying so.
    """

    mode: ToolChoiceMode = ToolChoiceMode.AUTO
    tool_name: str | None = None
    # Forbid calling several tools in parallel in one round. Allowed by default,
    # which is also both providers' default.
    disable_parallel: bool = False

    def __post_init__(self):
        if self.mode is ToolChoiceMode.TOOL and not self.tool_name:
            raise ValueError("ToolChoice(mode=TOOL) requires tool_name")
        if self.mode is not ToolChoiceMode.TOOL and self.tool_name is not None:
            raise ValueError(
                f"tool_name is only meaningful with mode=TOOL, got mode={self.mode.value}"
            )

    @classmethod
    def required(cls, *, disable_parallel: bool = False) -> "ToolChoice":
        return cls(ToolChoiceMode.REQUIRED, disable_parallel=disable_parallel)

    @classmethod
    def tool(cls, name: str, *, disable_parallel: bool = False) -> "ToolChoice":
        return cls(
            ToolChoiceMode.TOOL, tool_name=name, disable_parallel=disable_parallel
        )

    @classmethod
    def none(cls) -> "ToolChoice":
        return cls(ToolChoiceMode.NONE)

    def validate_against(self, tools: list[FunctionTool] | None) -> None:
        """Before sending: a forcing setting needs a tool menu, and the named
        tool must be on it. Raises ValueError otherwise."""
        if self.mode in (ToolChoiceMode.REQUIRED, ToolChoiceMode.TOOL) and not tools:
            raise ValueError(
                f"tool_choice={self.mode.value} but this call supplied no tools"
            )
        if self.mode is ToolChoiceMode.TOOL:
            names = {t.name for t in tools}
            if self.tool_name not in names:
                raise ValueError(
                    f"tool_choice names {self.tool_name!r}, which is not in tools; "
                    f"available: {sorted(names)}"
                )

    def verify_response(self, tool_calls: list[dict]) -> None:
        """After the reply: raise RuntimeError unless the model obeyed the
        setting. Disobedience means it never took effect, usually because a
        relay gateway dropped tool_choice."""
        called = [tc.get("name") for tc in tool_calls]
        hint = ("likely cause: a relay gateway dropped tool_choice on the way "
                "out, so the model never received the constraint")
        if self.mode is ToolChoiceMode.REQUIRED and not tool_calls:
            raise RuntimeError(f"tool_choice=required but the model called no tool; {hint}")
        if self.mode is ToolChoiceMode.TOOL and self.tool_name not in called:
            raise RuntimeError(
                f"tool_choice forced {self.tool_name!r} but the model called "
                f"{called or 'nothing'}; {hint}"
            )
        if self.mode is ToolChoiceMode.NONE and tool_calls:
            raise RuntimeError(f"tool_choice=none but the model still called tools: {called}; {hint}")


class ChatClient(ABC):
    """The unified call interface: callers state provider-independent intent and
    each adapter turns it into its own wire shape. ``response_format="json"``
    asks for valid JSON; ``json_schema`` validates the reply locally on every
    backend and is never sent to the API. Cancelling ``invoke``
    aborts the HTTP request and lets ``CancelledError`` propagate.
    """

    @abstractmethod
    async def invoke(
        self,
        messages: list[ChatMessage],
        tools: list[FunctionTool] | None = None,
        tool_choice: ToolChoice | None = None,
        # None = do not send the parameter, taking the model's own default. The
        # newest model families reject it outright, so a caller wanting a
        # specific temperature passes it per call; it is never a global setting.
        temperature: float | None = None,
        response_format: str | None = None,
        json_schema: dict | None = None,
        effort: "Effort | None" = None,
        on_delta: OnDelta | None = None,
        **kwargs,
    ) -> ChatResponse:
        ...


class RemoteChatClient(ChatClient, ABC):
    def __init__(self, model_name: str, api_key: str):
        super().__init__()
        self.model_name = model_name
        self.api_key = api_key
