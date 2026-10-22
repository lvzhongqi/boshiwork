"""Node 4, extract_flow: the model reads the message flow out of the document
and writes the whole flow model .pv, submitted by fence.

Identity and structure modeling cards are fetched on demand; the model picks
one by an in-text marker, and acceptance checks both that the card was offered
and that the code implements it. ``@ENTRY`` markers name a principal's parallel
entry branches, counted against its ``entries=`` list. The submission is the
honest-run form: the scaffold ships one ``reached_<Role>`` event and query per
role, and only the model can say where in a role's body the run has succeeded,
so the checks keep the mechanical part (right role, not main, no trailing ``;``).

Artifacts beside the session: flow.pv (the submission with the probe stripped,
the only one downstream reads), flow_honest.pv (the submitted form),
checks.md / checks.json (acceptance results) and review/ for the independent
review — warning level, non-blocking, with a transcript.jsonl of its own. Plus
this step's own transcript.jsonl and rounds/.
"""

from __future__ import annotations

import json
from pathlib import Path

import orrery.checks.rules.flow  # noqa: F401  importing registers the checks
from orrery.agent.runner import Prompt, SubmitSpec, run_agent
from orrery.infra.llm.client import Effort
from orrery.agent.tools import flow_tools
from orrery.agent.tools.context import ToolContext
from orrery.agent.tools.modeling_tools import (
    identity_modeling_miss_from_messages, offered_identity_idioms_from_messages,
    offered_structure_idioms_from_messages,
)
from orrery.checks.registry import must_failures, run_checks
from orrery.checks.reviewer.checker import review_flow
from orrery.checks.rules.flow import FLOW_CHECK_NAMES
from orrery.infra.proverif.outcome import OutcomeKind, classify
from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.document.corpus import flow_text, inline_corpus
from orrery.modules.pvtext.knowledge import template_roles
from orrery.modules.pvtext.parse import (
    blank_comments,
    duplicate_destructor_declarations,
)
from orrery.modules.pvtext.probe import strip_probe
from orrery.agent.compose import localized, render_prompt, render_system, resume_user
from orrery.nodes.base import (
    GapRaised, Node, NodeError, RoundLog, RunEnv,
)
from orrery.nodes.flow.template import render_template, template_reference
from orrery.services.events import (
    ModelDelta, NodeProgress, PromptFiled, SessionUsage, check_sink,
)
from orrery.services.transcript.reader import TranscriptReader
from orrery.services.store.atomic import write_json, write_text
from orrery.services.transcript.resume import resume_messages
from orrery.services.transcript.writer import TranscriptWriter


def _fixed_lines(template: str) -> list[str]:
    """The lines the template keeps verbatim: channel declarations, the probe's
    queries, and the solver setting.

    The probe's ``event`` declarations are not among them: a declaration line
    and a call at the end of a body are the same text (``event reached_A().``),
    so a check by line would find the call and report the declaration present
    after the model deleted it. A query naming an undeclared event is caught as
    a typecheck error instead.
    """
    return [ln for ln in template.splitlines()
            if ln.startswith("free c:") or ln.startswith("free channel_")
            or ln.startswith("query event(reached_") or ln.startswith("set ")]


def load_flow_input(inp, where: str) -> str:
    """Read the supplied mother model off disk and return its text.

    ``inp`` is a path and nothing else: a model is text, so "a str is a path"
    and "a str is the model" cannot both hold. A wrong type or a missing file
    raises NodeError, tagged with ``where``.
    """
    if not isinstance(inp, (str, Path)):
        raise NodeError(f"{where} failed: the flow model input is a path to a "
                        f".pv file, not {type(inp).__name__}")
    p = Path(inp)
    if not p.is_file():
        raise NodeError(f"{where} failed: flow model path does not exist: {p}")
    return p.read_text(encoding="utf-8")


#: The one node this step may report a gap against: principals.json is the only
#: upstream artifact it consumes, and a gap report names a concrete missing name
#: in an artifact. Held inside the structural bound by tests/contracts.
GAP_TARGETS = ("extract_principals",)


def build_prompt(*, corpus: str, protocol: str, knowledge: dict, template: str,
                 step_messages: str = "", lang: str = "en") -> Prompt:
    """This node's one request. No I/O and no LLM — the prompt preview calls
    it to render exactly what a run sends.

    The corpus is a separate leading system block, shown at the {{ document }}
    placeholder of main.sys.md. It is byte-identical with the document readers'
    block, but the prefix cache does not span this node and them: tools sit
    ahead of the system blocks, and this node's carry the primitive catalog and
    report_gap. The block pays for itself across this session's own rounds.
    """
    return Prompt(
        system=render_system(__file__, localized("main.sys.md", lang),
                              cut_after=["document"], document=corpus),
        user=render_prompt(
            __file__, localized("main.user.md", lang), protocol=protocol,
            knowledge_json=json.dumps(knowledge, ensure_ascii=False, indent=2),
            template=template, reference=template_reference(knowledge),
            step_messages=step_messages),
        tools=tuple(flow_tools(GAP_TARGETS)),
        submit=SubmitSpec(kind="fence", fence_lang="proverif"),
        label="extract_flow",
    )


def _declarations(pv: str) -> list[str]:
    """The model's top-level declarations, split on the terminating period.

    Comments are blanked first so a `fun` or `reduc` inside one cannot be read
    as a declaration. Process-body fragments come out of the split too and are
    harmless: neither pattern matches them.
    """
    return [chunk + "." for chunk in blank_comments(pv).split(".")]


async def _write_models(submitted: str, *, roles: list[str],
                        runner: ProVerifRunner, out: Path, flow_pv: Path) -> str:
    """Write flow_honest.pv as submitted and flow.pv with the probe stripped;
    return the stripped text.

    The stripped text goes through ProVerif before it is written. Removal is
    three exact rewrites that cannot break a file that parsed, so a syntax
    error here is a framework bug and is raised as RuntimeError rather than
    reported as a finding against an accepted model. The return value feeds the
    independent review, which has to see the model without the probe.
    """
    honest = submitted if submitted.endswith("\n") else submitted + "\n"
    write_text(out / "flow_honest.pv", honest)
    flow = strip_probe(honest)
    outcome = classify(await runner.run(flow, log_to=out / "flow_stripped"))
    if outcome.kind is OutcomeKind.SYNTAX_ERROR:
        raise RuntimeError(
            "framework bug: the flow model does not parse once the honest-run "
            "probe is removed, though the submitted form passed its checks. "
            "The removal introduced the error: "
            + "; ".join(outcome.errors or ["no detail"]))
    write_text(flow_pv, flow)
    return flow


def _write_checks(out, results) -> None:
    """The acceptance result, twice: ``checks.md`` for a person and
    ``checks.json`` for a program.

    The same facts either way. The markdown carries the findings; the json
    carries one boolean per check, for the scoring pass that reports this step
    as two gates and cannot parse prose.
    """
    write_text(out / "checks.md", "\n".join(
        f"- [{r.level}] {r.name}: {'pass' if r.passed else 'FAIL'}"
        + (("\n  " + "\n  ".join(r.findings)) if r.findings else "")
        for r in results) + "\n")
    write_json(out / "checks.json", {r.name: bool(r.passed) for r in results})


class FlowNode(Node):
    """The extract_flow step: write flow.pv from the document, or accept a
    supplied mother model through the same checks."""
    needs_solver = True

    name = "extract_flow"
    short = "flow"
    task = (
        "Read the message flow from the document and write the complete "
        "ProVerif flow model on the scaffold")
    model_driven = True
    gap_targets = GAP_TARGETS
    depends_on = ("extract_principals",)
    # The one step that writes protocol semantics into ProVerif text, and the
    # one whose mistakes are invisible: a model that is wrong but typechecks
    # still produces verdicts that look fine. Left unset the model spends no
    # thinking tokens here, so the rung is stated; one below the top, where the
    # reasoning is substantive rather than padded.
    effort = Effort.HIGH

    def is_done(self, env: RunEnv) -> bool:
        return env.layout.has(self.name, "flow.pv")

    async def _supplied(self, env: RunEnv, knowledge: dict, checks, runner) -> None:
        """Put a mother model handed in from outside through this node's own
        acceptance test; nothing is written by a model.

        Every ``must`` check applies. The value/dependency comparison against
        principals.json runs at warn level, since a supplied model is the
        reference — checks/rules/flow.py lists the ways a correct one can
        disagree with it. There is no repair round to fall back on, so a must
        failure stops the run and names the check. The independent review does
        not run: it reconciles a written model against the document."""
        out = env.layout.node_dir(self.name)
        log = lambda tag: out / f"supplied_{tag}"          # noqa: E731
        pv = load_flow_input(env.flow_input, self.name)

        # The fixed scaffold is checked first, so a supplied model with the
        # wrong role/channel topology stops at that direct mismatch instead of
        # failing further in.
        results = await checks(pv, log, ["flow_fixed_parts"])
        if not must_failures(results):
            results += await checks(pv, log, [n for n in FLOW_CHECK_NAMES
                                              if n != "flow_fixed_parts"])
        problems = must_failures(results)
        _write_checks(out, results)
        if problems:
            raise NodeError(
                f"{self.name} failed: the supplied flow model does not pass "
                f"this node's own checks: " + "; ".join(problems))
        if env.bus is not None:
            env.bus.emit(NodeProgress(
                run=env.layout.run_name, node=self.name,
                text="flow.pv was supplied, so nothing was extracted from the document"))
        await _write_models(pv, roles=template_roles(knowledge), runner=runner,
                            out=out, flow_pv=env.layout.flow_pv)

    async def run(self, env: RunEnv) -> None:
        d = env.layout
        try:
            knowledge = json.loads(
                (d.node_dir("extract_principals") / "principals.json")
                .read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise NodeError(f"{self.name} failed: an upstream artifact is missing; {e}") from None

        template = render_template(protocol_name=env.protocol_id,
                                   knowledge=knowledge)
        fixed = _fixed_lines(template)
        pv_cfg = env.config["proverif"]
        runner = ProVerifRunner(executable=pv_cfg["executable"],
                                timeout_s=pv_cfg["timeout_s"])
        roles = template_roles(knowledge)
        checks_em = env.emitter(self.name)

        ctx: ToolContext | None = None

        async def _checks(pv: str, pv_log, names=FLOW_CHECK_NAMES) -> list:
            return await run_checks(names, {
                "pv": pv, "runner": runner, "pv_log": pv_log,
                "fixed_lines": fixed, "roles": roles,
                "principals": knowledge,
                "offered_identity_idioms": None if ctx is None else
                frozenset(ctx.offered_identity_idioms),
                "identity_modeling_miss": False if ctx is None else
                ctx.identity_modeling_miss,
                "offered_structure_idioms": None if ctx is None else
                frozenset(ctx.offered_structure_idioms),
            }, on=check_sink(checks_em))

        if env.flow_input is not None:
            await self._supplied(env, knowledge, _checks, runner)
            return

        if env.doc_set is None:
            raise NodeError(f"{self.name} failed: no document set upstream")

        prompt = build_prompt(
            corpus=inline_corpus(env.doc_set,
                                 env.config["document"]["inline_max_chars"],
                                 get_flow=True),
            protocol=env.protocol_id, knowledge=knowledge, template=template,
            step_messages=env.facts(self.name),
            lang=env.config.get("prompt_lang", "en"),
        )
        submit = prompt.submit
        transcript = d.node_transcript(self.name)
        resume = resume_messages(transcript)
        writer = TranscriptWriter(transcript)
        if resume is None:
            writer.meta(node=self.name,
                        model=env.config["llm"].get("model", "?"),
                        effort=self.effort)
            user = prompt.user
        else:
            user = resume_user(submit)

        ctx = ToolContext(
            node=self.name, doc_set=env.doc_set, artifacts_root=d.run_dir,
            upstream_nodes=env.upstream(self.name),
            tool_return_chars=env.config["agent"]["tool_return_chars"],
            prompt_lang=env.config.get("prompt_lang", "en"),
        )
        ctx.offered_identity_idioms.update(
            offered_identity_idioms_from_messages(resume))
        ctx.identity_modeling_miss = identity_modeling_miss_from_messages(resume)
        ctx.offered_structure_idioms.update(
            offered_structure_idioms_from_messages(resume))

        results_box: dict = {}
        rounds = RoundLog(d.node_dir(self.name))

        async def _accept(pv, _fences):
            rounds.begin(pv)             # text under test lands first, checks after
            # Constructor/destructor collision, caught before paying for a
            # ProVerif run. ProVerif answers it with "already defined", which
            # reads like a name clash, and a model told only that renames the
            # symbol and repeats the same structural mistake.
            if dups := duplicate_destructor_declarations(_declarations(pv)):
                problems = [
                    f"symbol(s) {dups} are declared with `fun` and also "
                    f"introduced as the outer destructor of a `reduc`; declare "
                    f"only the constructor with `fun` and introduce each "
                    f"destructor only through its reduction rule. Renaming the "
                    f"symbol does not fix it"]
                rounds.finish(problems)
                return problems
            rs = await _checks(pv, rounds.stem)
            results_box["last"] = rs
            problems = must_failures(rs)
            rounds.finish(problems)
            return problems

        result = await run_agent(
            env.llm(),
            # The corpus is block 0 of prompt.system — build_prompt says why the
            # split is there.
            system=prompt.system,
            user=user,
            tools=list(prompt.tools),
            ctx=ctx,
            submit=submit,
            accept=_accept,
            budget=env.budget(),
            writer=writer,
            resume_from=resume,
            effort=self.effort,
            emitter=env.emitter(self.name),
        )
        if result.status == "gap":
            raise GapRaised(result.gap, transcript, result.gap_tool_call_id)
        if result.status != "ok":
            raise NodeError(f"{self.name}: {result.status}: {result.failure}")

        out = d.node_dir(self.name)
        # The step's products under plain names; the per-round text sits one
        # level down in rounds/.
        flow_pv_text = await _write_models(result.submission, roles=roles,
                                           runner=runner, out=out,
                                           flow_pv=d.flow_pv)
        _write_checks(out, results_box.get("last", []))

        # Independent review: warning level, non-blocking, a separate call with
        # its own context and so its own transcript. `note` puts the step on the
        # ledger, since a call outside run_agent emits no round events. Its
        # reference for the message flow is the document itself — reconciling a
        # model against a distilled intermediate only shows they match.
        flow, flow_source = flow_text(env.doc_set)
        em = env.emitter(self.name)
        findings = await review_flow(
            # The stripped flow model, not the submission: a review handed the
            # honest-run probe reports the probe's own query as a finding.
            env.llm(), pv_text=flow_pv_text,
            knowledge=knowledge, flow_text=flow, flow_source=flow_source,
            writer=TranscriptWriter(out / "review" / "transcript.jsonl"),
            model=env.config["llm"].get("model", "?"),
            note=None if em is None else
            (lambda text: em(NodeProgress(run="", node=self.name, text=text))),
            # The same three reports every other step makes: where the prompt
            # went, the reply as it arrives, and (below) what it cost.
            on_prompt=None if em is None else
            (lambda path: em(PromptFiled(
                run="", node=self.name,
                path=str(path.relative_to(env.layout.run_dir)),
                chars=path.stat().st_size))),
            on_delta=None if em is None else
            (lambda kind, text: em(ModelDelta(
                run="", node=self.name, kind=kind, text=text))),
        )
        write_json(out / "review" / "review.json", findings)
        # The review is a bare LLM call outside run_agent, so nothing has
        # reported what it cost. Read it back off the session it just wrote.
        if em is not None:
            r_in, r_out = TranscriptReader(
                out / "review" / "transcript.jsonl").usage_total()
            em(SessionUsage(run="", node=self.name, input_tokens=r_in,
                            output_tokens=r_out))
