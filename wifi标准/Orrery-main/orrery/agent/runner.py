"""The agent executor: runs one model-driven task to an exit. No domain logic,
shared by every node. One round = send messages, the model replies, any tool
calls run and their results go back; the exits are ok, failed, gave_up and gap.
The product arrives as a submit tool call, bare JSON, a fenced block or free
text (SubmitSpec.kind); under the last three the bare reply is the product.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from orrery.agent.budget import LoopBudget
from orrery.agent.compose import RepairContext, diagnosis
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.expert_tools import FixPlan
from orrery.agent.tools.gap_tools import GapReport
from orrery.agent.tools.registry import ToolDef, dispatch, to_function_tools
from orrery.infra.llm.client import (
    ChatClient, ChatMessage, FunctionTool, Role, TokenUsage, ToolChoice,
)
from orrery.infra.llm.validation import OutputFormatViolation
from orrery.services.transcript.writer import (
    TranscriptWriter, current_session,
)


#: The submission tool's name. A node's own tool list may not use it; the
#: collision is checked when the loop starts.
SUBMIT_TOOL = "submit"

_FINALIZATION_PROMPT = (
    "Final submission round. No evidence-gathering tools are available. "
    "Submit the best complete artifact using the evidence already collected, "
    "or use an available terminal exit if the task cannot be completed."
)


@dataclass(frozen=True)
class GiveUpSpec:
    """A task's second exit: a tool for "this cannot be done", beside the tool
    that delivers the product. Two separate tools keep the two outcomes
    exclusive at the protocol level."""

    name: str                       # the tool's name; must not collide with the node's own tools
    description: str                # when to call it, in the model's terms
    schema: dict                    # its parameters: what the caller needs in order to act on the refusal


@dataclass(frozen=True)
class SubmitSpec:
    kind: Literal["tool", "json", "fence", "text"]   # text: free text is the reply (the expert's long session)
    # kind=tool: the tool's parameters, enforced by the provider and re-checked
    # here. kind=json: a shape template shown in the prompt, not an API constraint.
    schema: dict | None = None
    fence_lang: str = ""            # when kind=fence, prefer the fence tagged with this language
    give_up: GiveUpSpec | None = None   # kind=tool only: the second exit, for a task that cannot be done


@dataclass(frozen=True)
class Prompt:
    """One request as it opens: everything run_agent needs to send it, and
    everything the prompt preview needs to render it. A node builds one with no
    I/O and no LLM, so the preview renders the exact bytes a run sends. The
    delivery format and the task-ending tools are added on the way out by
    sent_blocks / sent_tools."""
    system: list[str]         # cache blocks, in the order they are sent
    user: str                 # the opening user message
    tools: tuple = ()         # the node's own tools (ToolDef), terminal ones excluded
    submit: SubmitSpec = field(default_factory=lambda: SubmitSpec(kind="text"))
    label: str = ""           # names this request in the preview's file listing


@dataclass
class AgentResult:
    status: Literal["ok", "failed", "gap", "fix", "gave_up"]
    submission: dict | str | None = None    # json → dict; fence → str
    gave_up: dict | None = None             # the give-up tool's arguments, when status=gave_up
    gap: GapReport | None = None
    gap_tool_call_id: str | None = None     # pairs the tool_result when a rejection is resumed
    fix: FixPlan | None = None              # the expert's propose_fix (a terminal tool, like gap)
    fix_tool_call_id: str | None = None
    rounds_used: int = 0
    tool_calls_used: int = 0
    repairs_used: int = 0
    # What this call cost, summed over its rounds; the per-round figures stay
    # in the transcript.
    usage: TokenUsage = field(default_factory=TokenUsage)
    failure: str = ""                       # one-line reason when status=failed
    # Every fence in the submitting message (lang → content, last one wins per
    # lang), for the parts of a product that travel outside the call.
    fences: dict[str, str] = field(default_factory=dict)


# The accept callback takes (submission, fences) and returns the list of
# problems; an empty list means accepted. It may be async.
AcceptFn = Callable[[dict | str, dict], object]


async def run_agent(
    llm: ChatClient,
    *,
    system: str | list[str],    # a list is one prompt split at cache-breakpoint boundaries
    user: str,
    tools: list[ToolDef],
    ctx: ToolContext,
    submit: SubmitSpec,
    accept: AcceptFn,
    budget: LoopBudget,
    writer: TranscriptWriter,
    resume_from: list[ChatMessage] | None = None,
    effort: str | None = None,      # this task's reasoning level; None takes the provider default
    emitter=None,                   # optional fn(Event); round / tool / check events are only sent when given
) -> AgentResult:
    """Run one task to an exit and return its AgentResult.

    Passing ``resume_from`` continues a session: ``user`` is appended to the old
    message list and ``system`` is ignored, since that session already has one.
    ``effort`` applies to every round of the task, repair rounds included."""
    # What the session was told reaches the transcript only once the service
    # has taken it. The transcript is what a resume replays, so a message
    # recorded before the call survives a failure that call is bound to
    # repeat: an over-long request 400s, the node carries on in the same
    # directory (RunEnv.plan returns "carry" for unfinished work), resume
    # replays the same bytes, and the session is dead for good with no way out
    # but editing the file by hand. Held here instead and settled as soon as
    # the call is answered, interrupted, or the loop leaves on its own — only
    # a call the service refused is discarded, prompt files already on disk
    # notwithstanding. The system prompt is held the same way: recorded on its
    # own it restores to a session with no task, and the node would then send
    # "continue from the progress above" to a model that was never told what
    # the work is. Held together, a refused opening call leaves a transcript
    # that restores to nothing, and the node starts afresh.
    pending_system: str | None = None
    if resume_from is not None:
        messages = list(resume_from)
    else:
        # The submission format goes into the prompt itself: a gateway can
        # silently drop the json_schema API parameter, and a model that never
        # saw the schema is left guessing field names.
        blocks = sent_blocks(system, submit)
        messages = [ChatMessage(Role.SYSTEM,
                                blocks if len(blocks) > 1 else blocks[0])]
        pending_system = "\n\n".join(blocks)
    unsent: list[str] = []

    def say(text: str) -> None:
        """Put one user message into the session; the record waits for a reply."""
        messages.append(ChatMessage(Role.USER, text))
        unsent.append(text)

    def settle() -> None:
        """The service took the request: what it carried is now on the record,
        the system prompt first. Idempotent, so every way out may call it."""
        nonlocal pending_system
        if pending_system is not None:
            writer.system(pending_system)
            pending_system = None
        for text in unsent:
            writer.user(text)
        unsent.clear()

    def discard() -> None:
        """The service refused the request: nothing it carried is history."""
        nonlocal pending_system
        pending_system = None
        unsent.clear()

    say(user)

    def _filed(path, round_no: int, how: str = "") -> None:
        """Emit PromptFiled for a prompt that has just reached disk. The file's
        own name is the payload: its slot is claimed against the directory as
        it is written, so nothing downstream can reconstruct it."""
        if emitter is None:
            return
        from orrery.services.events.agent import PromptFiled
        text = path.read_text(encoding="utf-8", errors="replace")
        # Ledger paths are relative to the run directory. A context with no
        # root is a caller outside a run, and then the absolute path stands.
        root = ctx.artifacts_root
        rel = str(path.relative_to(root)) if root and path.is_relative_to(root) \
            else str(path)
        emitter(PromptFiled(run="", node=ctx.node, path=rel,
                            round_no=round_no, chars=len(text), how=how))

    fn_tools = sent_tools(tools, submit, where=ctx.node)
    terminal_names = {SUBMIT_TOOL}
    if submit.give_up is not None:
        terminal_names.add(submit.give_up.name)
    terminal_names.update(tool.name for tool in tools if tool.terminal)
    terminal_fn_tools = [tool for tool in fn_tools
                         if tool.name in terminal_names]
    if resume_from is None:
        # A readable copy of what this session was told, written before the
        # first call goes out, tool definitions included.
        _filed(writer.prompt(tools=fn_tools,
                             system=messages[0].content, user=user), 1)
    else:
        # A resume sends no system prompt, so the session keeps the opening
        # file it already has; this message is filed like any other round's.
        how = "a resumed session's first message"
        _filed(writer.round_prompt(user, how=how), 1, how)

    def _next_round(text: str, how: str = "") -> None:
        """File one framework message: one file per round, in the slot before
        that round's own files."""
        _filed(writer.round_prompt(text, how=how), result.rounds_used + 1, how)

    _AS_SUBMIT = "the rejected submit call's tool result"
    result = AgentResult(status="failed")
    last_submission_raw: str | None = None
    # Rounds that neither called a tool nor delivered. One is normal thinking
    # out loud; two in a row is a stuck loop and ends the task.
    silent_rounds = 0
    finalization_used = False

    # infra/llm takes a plain (kind, text) function, so the run / node address a
    # watcher needs is closed over rather than travelling with every fragment.
    delta_sink = None
    if emitter is not None:
        from orrery.services.events.agent import ModelDelta

        def delta_sink(kind: str, text: str) -> None:      # noqa: F811
            emitter(ModelDelta(run="", node=ctx.node, kind=kind, text=text))

    # Binds every model call below to this transcript, so nothing downstream of
    # invoke() needs that filename in its signature. Released in the finally.
    session = current_session.set(writer.path)
    try:
        while True:
            finalizing = False
            if (budget.max_rounds is not None
                    and result.rounds_used >= budget.max_rounds):
                # A pending tool result or repair diagnosis is framework
                # feedback the model has not answered yet: it gets one bounded
                # round with every evidence-gathering tool removed.
                pending_feedback = bool(messages) and messages[-1].role in {
                    Role.USER, Role.TOOL,
                }
                if finalization_used or not pending_feedback:
                    result.failure = f"budget exhausted: max_rounds={budget.max_rounds}"
                    return result
                finalization_used = True
                finalizing = True
                _next_round(_FINALIZATION_PROMPT,
                            "the terminal-only finalization round")
                say(_FINALIZATION_PROMPT)

            call_tools = fn_tools
            tool_choice = None
            if finalizing:
                call_tools = terminal_fn_tools
                if submit.kind == "tool":
                    if len(call_tools) == 1:
                        tool_choice = ToolChoice.tool(
                            call_tools[0].name, disable_parallel=True)
                    else:
                        tool_choice = ToolChoice.required(disable_parallel=True)
                elif call_tools:
                    # A fence/JSON submission is plain text, but report_gap may
                    # still be a legitimate terminal alternative.
                    tool_choice = ToolChoice(disable_parallel=True)
                else:
                    tool_choice = ToolChoice.none()
            # Wall clock for one round's model call, for the RoundStarted
            # below. Outside the adapter, so every backend and the
            # OutputFormatViolation path are timed by the same clock.
            t0 = time.perf_counter()
            try:
                resp = await llm.invoke(
                    messages,
                    tools=call_tools,
                    tool_choice=tool_choice,
                    # Validated locally after the reply, never sent to the API:
                    # map-shaped products have dynamic keys (entity names) that
                    # API structured outputs cannot express.
                    json_schema=submit.schema if submit.kind == "json" else None,
                    effort=effort,
                    on_delta=delta_sink,
                )
            except OutputFormatViolation as e:
                # The result-side schema check failed, which a model can repair,
                # so it costs one repair round; the diagnosis carries an excerpt.
                # The model did answer and was billed, so the request is settled.
                result.rounds_used += 1
                result.repairs_used += 1
                # The refused reply never enters the session, so the transcript
                # is the only place it survives; its tokens still count.
                took_ms = int((time.perf_counter() - t0) * 1000)
                settle()
                writer.rejected(getattr(e, "raw", ""), str(e),
                                getattr(e, "usage", None))
                _add_usage(result.usage, getattr(e, "usage", None) or TokenUsage())
                if emitter is not None:
                    from orrery.services.events.agent import RoundStarted
                    u = getattr(e, "usage", None) or TokenUsage()
                    emitter(RoundStarted(run="", node=ctx.node,
                                         round_no=result.rounds_used,
                                         input_tokens=u.input_tokens,
                                         output_tokens=u.output_tokens,
                                         cached_tokens=u.cached_tokens,
                                         duration_ms=took_ms))
                if result.repairs_used > budget.max_repairs:
                    result.failure = f"format still wrong after {budget.max_repairs} repair rounds: {e}"
                    return result
                msg = diagnosis(result.repairs_used, budget.max_repairs, [str(e)])
                _next_round(msg)
                say(msg)
                continue
            except asyncio.CancelledError:
                # An interrupt is not a refusal: the request was fine and is
                # replayed on resume, so it is settled below with the marker.
                raise
            except BaseException:
                # The service refused the call (an over-long request, a 4xx, a
                # network fault): whatever it carried is not replayed.
                discard()
                raise
            took_ms = int((time.perf_counter() - t0) * 1000)
            settle()
            result.rounds_used += 1
            _add_usage(result.usage, resp.usage)
            if emitter is not None:
                from orrery.services.events.agent import RoundStarted
                emitter(RoundStarted(run="", node=ctx.node,
                                     round_no=result.rounds_used,
                                     input_tokens=resp.usage.input_tokens,
                                     output_tokens=resp.usage.output_tokens,
                                     cached_tokens=resp.usage.cached_tokens,
                                     duration_ms=took_ms))
            writer.assistant(resp)
            messages.append(ChatMessage(
                Role.ASSISTANT, resp.content,
                tool_calls=resp.tool_calls or None, thinking=resp.thinking,
                thinking_blocks=resp.thinking_blocks,
            ))

            if resp.tool_calls:
                # A tool round's narration goes to the ledger, so a model that
                # has lost its way is visible without replaying its tool calls.
                if emitter is not None and (resp.content or "").strip():
                    from orrery.services.events.pipeline import NodeProgress
                    emitter(NodeProgress(run="", node=ctx.node,
                                         text=(resp.content or "").strip()[:160]))
                # max_tool_calls rations evidence gathering only; the
                # task-ending calls do not count against it.
                ending = {SUBMIT_TOOL} | (
                    {submit.give_up.name} if submit.give_up else set())
                gathering = [tc for tc in resp.tool_calls
                             if tc["name"] not in ending]
                # Both exits in one round contradict each other, so the whole
                # round is rejected; every call gets the diagnosis as its result
                # so no tool_use dangles.
                if len({tc["name"] for tc in resp.tool_calls
                        if tc["name"] in ending}) > 1:
                    problems = [
                        f"this round called both {SUBMIT_TOOL} and "
                        f"{submit.give_up.name}, which contradict each other: "
                        f"exactly one of them applies — decide which, and call "
                        f"only that one"]
                    _emit_check(emitter, ctx, problems, result.repairs_used + 1)
                    result.repairs_used += 1
                    if result.repairs_used > budget.max_repairs:
                        result.failure = (f"still calling both exits after "
                                          f"{budget.max_repairs} repair rounds")
                        return result
                    out = diagnosis(result.repairs_used, budget.max_repairs,
                                    problems)
                    _next_round(out, "the tool result of every call this round made")
                    for tc in resp.tool_calls:
                        writer.tool_result(tc["id"], tc["name"], out)
                        messages.append(ChatMessage(
                            Role.TOOL, out, tool_call_id=tc["id"]))
                    silent_rounds = 0
                    continue
                if (budget.max_tool_calls is not None
                        and result.tool_calls_used + len(gathering)
                        > budget.max_tool_calls):
                    result.failure = f"budget exhausted: max_tool_calls={budget.max_tool_calls}"
                    return result
                for tc in resp.tool_calls:
                    # Announced before anything is done with it: the terminal
                    # calls (submit, give_up, report_gap, propose_fix) each
                    # return out of this loop, so they get no ToolReturned.
                    if emitter is not None:
                        from orrery.services.events.agent import ToolCalled
                        emitter(ToolCalled(run="", node=ctx.node, tool=tc["name"],
                                           args_digest=_args_digest(tc)))
                    if (submit.give_up is not None
                            and tc["name"] == submit.give_up.name):
                        # The other exit. Its arguments get the same schema
                        # check a submission gets, but no node checks run on
                        # it: whether giving up is fatal is the node's call.
                        args, problems = _parse_tool_submission(
                            tc, submit.give_up.schema, submit.give_up.name)
                        if problems:
                            _emit_check(emitter, ctx, problems,
                                        result.repairs_used + 1)
                            result.repairs_used += 1
                            if result.repairs_used > budget.max_repairs:
                                result.failure = (
                                    f"{submit.give_up.name} still malformed after "
                                    f"{budget.max_repairs} repair rounds: {problems}")
                                return result
                            out = diagnosis(result.repairs_used,
                                            budget.max_repairs, problems)
                            _next_round(out, f"the {tc['name']} call's tool result")
                            writer.tool_result(tc["id"], tc["name"], out)
                            messages.append(ChatMessage(
                                Role.TOOL, out, tool_call_id=tc["id"]))
                            continue
                        writer.tool_result(tc["id"], tc["name"], _RECORDED)
                        result.status = "gave_up"
                        result.gave_up = args
                        return result
                    if submit.kind == "tool" and tc["name"] == SUBMIT_TOOL:
                        # A submission arriving as a tool call. Accepted ends
                        # the task; rejected becomes this call's tool_result,
                        # and every sibling call in the round still gets its
                        # own result, so no tool_use dangles.
                        payload, problems = _parse_tool_submission(tc, submit.schema)
                        # The submitting message's fences, so a product with a
                        # long free-text part can keep it out of the arguments.
                        result.fences = {lang or "": body.strip()
                                         for lang, body
                                         in _FENCE_RE.findall(resp.content or "")}
                        if not problems:
                            problems = accept(payload, result.fences)
                            if inspect.isawaitable(problems):
                                problems = await problems
                        _emit_check(emitter, ctx, problems, result.repairs_used + 1)
                        if not problems:
                            # Answer the call before leaving: a resume reads
                            # the transcript back, and an unanswered tool_use
                            # restores as a session killed mid-submission.
                            writer.tool_result(tc["id"], tc["name"], _ACCEPTED)
                            result.status = "ok"
                            result.submission = payload
                            return result
                        raw = tc.get("arguments")
                        if raw == last_submission_raw:
                            result.failure = "no progress: this submission is identical to the last one; stopping"
                            return result
                        last_submission_raw = raw
                        result.repairs_used += 1
                        if result.repairs_used > budget.max_repairs:
                            result.failure = (
                                f"not accepted after {budget.max_repairs} repair rounds; last problems: {problems}")
                            return result
                        out = diagnosis(result.repairs_used, budget.max_repairs,
                                        problems)
                        _next_round(out, _AS_SUBMIT)
                        writer.tool_result(tc["id"], tc["name"], out)
                        messages.append(ChatMessage(
                            Role.TOOL, out, tool_call_id=tc["id"],
                        ))
                        continue
                    result.tool_calls_used += 1
                    out = await dispatch(tools, ctx, tc)
                    if isinstance(out, GapReport):
                        result.status = "gap"
                        result.gap = out
                        result.gap_tool_call_id = tc["id"]
                        return result
                    if isinstance(out, FixPlan):
                        result.status = "fix"
                        result.fix = out
                        result.fix_tool_call_id = tc["id"]
                        return result
                    if emitter is not None:
                        from orrery.services.events.agent import ToolReturned
                        digest = " ".join(str(out).split())[:120]
                        emitter(ToolReturned(run="", node=ctx.node, tool=tc["name"],
                                             ok=not str(out).startswith("tool "),
                                             result_digest=digest))
                    writer.tool_result(tc["id"], tc["name"], out)
                    messages.append(ChatMessage(
                        Role.TOOL, out, tool_call_id=tc["id"],
                    ))
                silent_rounds = 0
                continue

            if submit.kind == "tool":
                # Nothing called and nothing delivered. Under kind='tool' this
                # is narration, and it costs a round and a nudge.
                silent_rounds += 1
                if silent_rounds > 1:
                    result.failure = ("two rounds in a row called no tool and did "
                                      "not submit; stopping")
                    return result
                if emitter is not None and (resp.content or "").strip():
                    from orrery.services.events.pipeline import NodeProgress
                    emitter(NodeProgress(run="", node=ctx.node,
                                         text=(resp.content or "").strip()[:160]))
                _next_round(_NO_SUBMIT_NUDGE)
                say(_NO_SUBMIT_NUDGE)
                continue

            # No tool call → this is a submission attempt.
            submission, problems = _parse_submission(resp.content, submit)
            result.fences = {lang or "": body.strip()
                             for lang, body in _FENCE_RE.findall(resp.content)}
            if not problems:
                problems = accept(submission, result.fences)
                if inspect.isawaitable(problems):
                    problems = await problems
            _emit_check(emitter, ctx, problems, result.repairs_used + 1)
            if not problems:
                result.status = "ok"
                result.submission = submission
                return result

            if resp.content == last_submission_raw:
                result.failure = "no progress: this submission is identical to the last one; stopping"
                return result
            last_submission_raw = resp.content

            result.repairs_used += 1
            if result.repairs_used > budget.max_repairs:
                result.failure = (
                    f"not accepted after {budget.max_repairs} repair rounds; last problems: {problems}"
                )
                return result
            msg = diagnosis(result.repairs_used, budget.max_repairs, problems)
            _next_round(msg)
            say(msg)
    except asyncio.CancelledError:
        settle()
        writer.interrupted("cancelled")
        raise
    finally:
        # A loop that leaves on its own (budget spent, no progress) may hold a
        # diagnosis the model never saw; it was sent nowhere, but it is what a
        # resumed session picks up from, so it is recorded like the rest.
        settle()
        current_session.reset(session)
        # Every way out reports what the call cost: a session that failed or
        # was interrupted was still paid for.
        if emitter is not None and (result.usage.input_tokens
                                    or result.usage.output_tokens):
            from orrery.services.events.agent import SessionUsage
            emitter(SessionUsage(
                run="", node=ctx.node,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cached_tokens=result.usage.cached_tokens,
                rounds=result.rounds_used))


def _add_usage(total: TokenUsage, one: TokenUsage) -> None:
    """Accumulate one round's usage into the call's total, in place."""
    total.input_tokens += one.input_tokens
    total.output_tokens += one.output_tokens
    total.total_tokens += one.total_tokens
    total.cached_tokens += one.cached_tokens
    total.cache_creation_tokens += one.cache_creation_tokens


def _args_digest(tc: dict, per_value: int = 40) -> str:
    """Ledger summary of a tool's arguments: each key truncated, newlines
    collapsed. Large text such as a whole pv keeps only its head."""
    args = tc.get("arguments_json")
    if not isinstance(args, dict):
        return str(tc.get("arguments"))[:per_value]
    parts = []
    for k, v in args.items():
        s = " ".join(str(v).split())
        parts.append(f"{k}={s[:per_value]}{'…' if len(s) > per_value else ''}")
    return ", ".join(parts)


# What the tool is and when to call it. The delivery protocol around it — what
# a reply with no tool call means — is stated once, in _submit_instructions.
_SUBMIT_DESCRIPTION = (
    "Deliver this step's finished product and end the task. Pass the whole "
    "product as this tool's arguments; its parameters are the product's shape. "
    "The framework runs the step's checks on what you pass: if they all hold "
    "the task is over, and if any fail this call returns the findings so you "
    "can correct them and call submit again. Call it as soon as the product is "
    "complete — there is no separate round for announcing that you are about to."
)

_ACCEPTED = "accepted: every check passed and the task is complete."

_RECORDED = "recorded: the task ends here and the framework takes it from you."

_NO_SUBMIT_NUDGE = (
    "That reply called no tool, so nothing was delivered. If the product is "
    "ready, call submit with it. If you still need evidence, call one of the "
    "reading tools."
)


def _terminal_tools(spec: SubmitSpec) -> list[FunctionTool]:
    """Every tool that ends the task: submit, plus the give-up tool if the
    task declared one."""
    tools = [_submit_tool(spec)]
    if spec.give_up is not None:
        tools.append(FunctionTool(
            name=spec.give_up.name,
            description=spec.give_up.description,
            parameters=spec.give_up.schema, strict=False))
    return tools


def _submit_tool(spec: SubmitSpec):
    if not spec.schema:
        raise ValueError("SubmitSpec(kind='tool') needs a schema: it is the "
                         "tool's parameters, and a tool with no parameters "
                         "cannot carry a product")
    return FunctionTool(name=SUBMIT_TOOL, description=_SUBMIT_DESCRIPTION,
                        parameters=spec.schema, strict=False)


def _parse_tool_submission(tc: dict, schema: dict,
                           name: str = SUBMIT_TOOL) -> tuple[dict | None, list]:
    """A task-ending tool call's arguments → (payload, problems). The provider
    has already parsed them into an object, so only the schema check is left.
    Shared by submit and give_up, so both are diagnosed the same way."""
    from orrery.infra.llm.validation import (
        OutputFormatViolation, check_against_schema,
    )
    args = tc.get("arguments_json")
    if not isinstance(args, dict):
        return None, [f"{name} was called with arguments that are not a JSON "
                      f"object: {str(tc.get('arguments'))[:300]}"]
    # A wrong closing tag on one parameter swallows the rest of the call into
    # its value, and the schema then reports a later parameter as missing.
    # Name the real fault instead of that misleading one.
    if (mark := _CALL_MARKUP_RE.search(json.dumps(args, ensure_ascii=False))):
        return None, [
            f"{name} was called with tool-call markup ({mark.group(0)}) inside a "
            f"parameter value, so one parameter absorbed the ones after it. "
            f"Every parameter closes with </parameter>, never with a tag named "
            f"after the parameter. Send the call again with each parameter "
            f"closed that way."]
    try:
        check_against_schema(args, schema, name,
                             json.dumps(args, ensure_ascii=False)[:300])
    except OutputFormatViolation as e:
        return None, [str(e)]
    return args, []


#: How much of one finding reaches the ledger: wide enough for the longest
#: message the checks produce, too narrow for an assembled file.
_FINDING_CHARS = 320


def _emit_check(emitter, ctx, problems, attempt: int) -> None:
    """Emit the ledger digest of one check attempt. RepairContext attachments
    (whole assembled files) stay out, and each finding is collapsed to one
    line, since a newline inside an event breaks work.md's rendering."""
    if emitter is None:
        return
    from orrery.services.events.checks import CheckReport
    emitter(CheckReport(run="", node=ctx.node, passed=not problems,
                        findings=[" ".join(str(x).split())[:_FINDING_CHARS]
                                  for x in (problems or [])
                                  if not isinstance(x, RepairContext)],
                        attempt=attempt))


def _submit_instructions(spec: SubmitSpec) -> str:
    if spec.kind == "tool":
        # The schema is not repeated here: it is the submit tool's own
        # parameters, which the provider renders for the model.
        other = ("" if spec.give_up is None else
                 f" When the task cannot be done at all, call "
                 f"`{spec.give_up.name}` instead of submit — the two are the "
                 f"only ways this task ends, and exactly one of them applies.")
        return ("<output_format>\nDeliver this step's product by calling the "
                "submit tool. A reply that calls no tool delivers nothing: it is "
                "read as thinking out loud and the task goes on, but two such "
                "replies in a row end the task with nothing delivered."
                + other + "\n</output_format>")
    if spec.kind == "text":
        return ("<output_format>\nThe reply that calls no tool is the answer to "
                "the user; write it in plain natural language.\n</output_format>")
    if spec.kind == "json":
        shape = ("\nThe reply must conform to this JSON Schema (field names "
                 "verbatim, no extra fields, no explanatory text):\n"
                 + json.dumps(spec.schema, ensure_ascii=False)) if spec.schema else ""
        return (
            "<output_format>\nAfter finishing, the reply that calls no tool must "
            "be exactly one JSON object and nothing else."
            + shape + "\n</output_format>"
        )
    return (
        "<output_format>\nAfter finishing, put the complete final file in one "
        f"```{spec.fence_lang} code block in the reply that calls no tool. That "
        "code block's content is the product.\n</output_format>"
    )


# The model receives the caller's system blocks and tools plus the delivery
# format and the task-ending tools. These two functions are that difference,
# exported so the prompt preview renders the same bytes a run sends.

def sent_blocks(system: str | list[str], submit: SubmitSpec) -> list[str]:
    """The system blocks as sent: the caller's blocks, with the delivery format
    appended to the last one."""
    blocks = [system] if isinstance(system, str) else list(system)
    blocks[-1] = blocks[-1] + "\n\n" + _submit_instructions(submit)
    return blocks


def sent_tools(tools: list[ToolDef], submit: SubmitSpec, *,
               where: str = "") -> list[FunctionTool]:
    """The tool list as sent: the caller's tools followed by the task-ending
    ones. Raises when a task-ending name is already taken — a shadowed submit
    would end the task by silently running the other tool."""
    fn_tools = to_function_tools(tools)
    if submit.kind == "tool":
        terminal = _terminal_tools(submit)
        taken = {t.name for t in fn_tools}
        clash = [t.name for t in terminal if t.name in taken]
        if clash:
            raise ValueError(
                f"node {where!r} already has a tool named {clash[0]!r}; the "
                f"task-ending tool would shadow it and ending the task would "
                f"silently run the other one")
        return fn_tools + terminal
    if submit.give_up is not None:
        raise ValueError(
            f"node {where!r}: give_up is a second tool, so it needs "
            f"kind='tool'; under {submit.kind!r} the model has no way to call it")
    return fn_tools


_FENCE_RE = re.compile(r"```(\w*)[ \t]*\n(.*?)```", re.S)
# Serialization artefacts that can only come from a broken tool call, never
# from protocol text or ProVerif code.
_CALL_MARKUP_RE = re.compile(r"</invoke>|<parameter name=")


def _parse_submission(
    content: str, spec: SubmitSpec
) -> tuple[dict | str | None, list[str]]:
    """Parse a submission. Returns (content, problems); a non-empty problem list
    means a repair round."""
    if spec.kind == "text":
        return content, ([] if content.strip() else ["reply is empty"])
    if spec.kind == "json":
        # The adapter already cleaned and validated it at the json_schema level,
        # so all that is left here is to parse.
        try:
            return json.loads(content), []
        except json.JSONDecodeError as e:
            return None, [f"submission is not valid JSON: {e.msg} (pos {e.pos})"]
    fences = _FENCE_RE.findall(content)
    if spec.fence_lang:
        tagged = [body for lang, body in fences if lang == spec.fence_lang]
        if len(tagged) > 1:
            return None, [
                f"reply has {len(tagged)} ```{spec.fence_lang} blocks; exactly one is "
                f"allowed — put the whole final file in a single block and resubmit"
            ]
        if tagged:
            return tagged[0].strip(), []
        # Some gateways drop the first token of a long reply, so
        # "```proverif\n..." arrives as "proverif\n...". Recovery is anchored to
        # the start and needs the tag word plus a closing fence.
        degraded = re.match(
            r"\s*`{0,2}" + re.escape(spec.fence_lang) + r"[ \t]*\n(.*?)```",
            content, re.S,
        )
        if degraded:
            return degraded.group(1).strip(), []
        # No untagged-block fallback when a language is specified: an
        # accompanying ```json block would be submitted as the artifact.
        return None, [
            f"submission must be inside a ```{spec.fence_lang} block; this reply has "
            f"no block with that tag"
        ]
    if fences:
        return fences[-1][1].strip(), []
    return None, [
        f"submission must be inside a ```{spec.fence_lang or ''} fenced block; this reply has no fence"
    ]
