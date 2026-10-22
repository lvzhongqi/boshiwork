"""Project the behaviour ledger (events.jsonl) into a readable work.md.

The ledger is the only source: nothing is inferred and no model is called.
Each node renders as a "round N: task / reply" dialogue; each scenario section
opens with its complete assumption assignment and closes with one verdict per
goal, joined to cross_check's cells by the assignment key rather than by name.
`generate` is a function the runner calls when a run ends, not a command.
"""

from __future__ import annotations

import json
from pathlib import Path

from orrery.pipeline.table import build_table
from orrery.services.events import KNOWN, parse_line
from orrery.services.store.atomic import read_jsonl_tolerant, write_text

#: node name -> the directory of its newest execution, refolded from the ledger
#: at the start of each generate(). Taken off the ledger, not the stage index,
#: so work.md can render from a ledger alone.
_dirs: dict[str, str] = {}

# One sentence per step, read off the node table; the console shows the same.
_NODE_TASKS = {n.name: n.task for n in build_table()}


def _flow_kind(flow: str) -> tuple[str, str]:
    """A flow name → (kind, what it names). Two spellings reach here: a unit
    from the envelope (``apply/03_lkr_from_start``, ``inject/Secrecy``) and,
    on a ledger with no ``unit`` field, the composite crammed into ``node``
    (``apply:03_lkr_from_start``)."""
    for sep in ("/", ":"):
        head, found, rest = flow.partition(sep)
        if found and rest:
            kind = head.split("_", 1)[-1]        # "08_apply" and "apply" alike
            return kind, rest
    return flow, ""


def _flow_task(flow: str) -> str:
    """The first round's task wording for a scenario-stage session."""
    kind, rest = _flow_kind(flow)
    if kind == "apply":
        # a point reads "03_lkr_from_start"; drop the ordering prefix
        return f"Apply assumption {rest.split('_', 1)[-1]} to the current model"
    if kind == "inject":
        return f"Inject probes and queries for the goals of {rest}"
    if flow == "apply":
        return "Rewrite this scenario's assumptions into the current model, in order"
    return _NODE_TASKS.get(flow, flow)


def generate(run_dir: str | Path) -> Path:
    """Read <run>/events.jsonl and run.json, write <run>/work.md, and return its
    path."""
    run_dir = Path(run_dir)
    events = [e for e in
              (parse_line(obj, KNOWN)
               for obj in read_jsonl_tolerant(run_dir / "events.jsonl"))
              if e is not None]
    meta = {}
    if (run_dir / "run.json").exists():
        meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    # Where each step's newest execution wrote, for sections that speak about a
    # step rather than one execution of it. Per-execution headings take theirs
    # off their own event, so a re-entered run says which attempt it is.
    global _dirs
    _dirs = {e.node: e.dir for e in events
             if type(e).__name__ == "NodeStarted" and e.dir}

    out = Path(run_dir) / "work.md"
    write_text(out, _render(events, meta))
    return out


# The dialogue renderer, shared by main-line nodes and scenario workflows.


def _clean(s, limit: int = 220) -> str:
    """One display line: whitespace collapsed (a stray newline or code fence
    inside an event breaks the whole page), truncated with an ellipsis."""
    s = " ".join(str(s).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


# Status words: an emoji (renders everywhere, terminal included) plus a colour
# span (HTML-capable markdown viewers pick it up, others strip it). Three marks
# across the whole page: ✅ passed, ≠ the answers differ from the corpus,
# 💥 a node crashed. A check that says no is a result, not a malfunction.
_PASS = '✅ <span style="color:#1a7f37">passed</span>'
_FAIL = '❌ <span style="color:#cf222e">FAILED</span>'

# A run's own outcome, read the same way.
_RUN_STATUS = {
    "ok": ("✅", "ok"),
    "check_failed": ("≠", "differs from the corpus"),
    "failed": ("💥", "failed — a node could not finish"),
    "interrupted": ("✋", "interrupted"),
}

# A verdict is a query's answer, not a judgement on the run: `false` is a
# healthy result, so verdicts get a coloured dot. Ticks and crosses stay for
# the things that can be right or wrong — a check, and agreement with truth.
_DOT = {"true": "🟢", "false": "🔴"}
_COLOUR = {"true": "#1a7f37", "false": "#cf222e"}


def _verdict(v: str) -> str:
    return (f'{_DOT.get(v, "⚪")} <span style="color:{_COLOUR.get(v, "#6e7781")}">'
            f'{v}</span>')


# Where an assignment's value came from.
_SOURCE = {
    "fixed": "fixed — every scenario carries it",
    "condition": "**this scenario's condition**",
    "default": "flow state (unmentioned)",
}


def _target(t) -> str:
    """An assumption target as one cell: `of=PKB`. A pair-valued
    field reads `A -> B`, the way the prompts write it."""
    if isinstance(t, dict):
        return ", ".join(
            f"{k}=" + (" -> ".join(str(x) for x in v)
                       if isinstance(v, (list, tuple)) else str(v))
            for k, v in sorted(t.items()))
    return "" if t is None else _clean(t, 60)


def _assignment_table(p, rows: list) -> None:
    """The assumption combination this scenario runs under — the complete
    assignment, fixed dimensions included, one row each."""
    p("**Assumptions in force** — the complete assignment this section runs under")
    p("")
    p("| assumption | axis | target | value | from |")
    p("|---|---|---|---|---|")
    for r in rows:
        p(f"| `{r.get('id') or '?'}` | {r.get('axis', '')} | {_target(r.get('target'))} "
          f"| `{r.get('subtype', '')}` | {_SOURCE.get(r.get('from'), r.get('from', ''))} |")
    p("")


def _verdict_table(p, verdicts: dict, graded: dict) -> None:
    """One goal per row, so a protocol with twenty goals stays readable. The
    ground-truth columns appear only when this run had ground truth."""
    show_gt = bool(graded)
    p("| goal | verdict |" + (" ground truth | agrees |" if show_gt else ""))
    p("|---|---|" + ("---|---|" if show_gt else ""))
    for goal, v in verdicts.items():
        row = f"| `{goal}` | {_verdict(v)} |"
        if show_gt:
            cell = graded.get(goal)
            if cell is None:
                row += " — | not in ground truth |"
            else:
                row += (f" {_verdict(cell['expected'])} | "
                        + ("✅ yes" if cell["match"] else "❌ **no**") + " |")
        p(row)
    p("")


def _tok(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


class _Usage:
    """The run's token bill, summed from the ledger's session_usage events.

    Bucketed the way the page is: one entry per node, every scenario-carrying
    session folded into the scenarios stage, plus a per-scenario tally. A
    ledger without those events sums to zero and prints nothing.
    """

    def __init__(self, events: list) -> None:
        self.by_node: dict[str, list[int]] = {}
        self.by_scenario: dict[str, list[int]] = {}
        self.total = [0, 0, 0]
        for ev in events:
            if type(ev).__name__ != "SessionUsage":
                continue
            row = [ev.input_tokens, ev.output_tokens, ev.cached_tokens]
            node = "scenarios" if ev.scenario is not None else (ev.node or "?")
            self._add(self.by_node.setdefault(node, [0, 0, 0]), row)
            if ev.scenario is not None:
                self._add(self.by_scenario.setdefault(ev.scenario, [0, 0, 0]), row)
            self._add(self.total, row)

    @staticmethod
    def _add(into: list[int], row: list[int]) -> None:
        for i, v in enumerate(row):
            into[i] += v

    @staticmethod
    def line(row: list[int] | None) -> str:
        """One display line, empty when nothing was recorded."""
        if not row or not (row[0] or row[1]):
            return ""
        cached = f", {_tok(row[2])} of it cached" if row[2] else ""
        return f"{_tok(row[0])} in / {_tok(row[1])} out{cached}"


class _Dialogue:
    """Buffer agent-domain events into per-round blocks: Task, Reply, Called,
    Framework, plus Checks on the round that submits. Only actions appear, not
    artifact content — the full text of every round is in transcript.jsonl.
    A tool return's summary becomes the next round's task, and round_no going
    back to 1 (apply opens a session per assumption) separates the sessions.
    """

    def __init__(self, p, first_task: str):
        self.p = p
        self.first_task = first_task
        self.round_no = 0            # 0 = no round started yet
        self.task: str | None = None  # fixed from accum when the round opens
        self.accum: str | None = None  # tool summaries for the next round's task
        self.reply: list[str] = []   # this round's tool calls
        self.narration: str | None = None
        self.framework: str | None = None

    def _flush_round(self, submitting: bool = False) -> None:
        """One round block: a header, then Task / Reply / Called / Framework as
        list items. Not submitting closes the block with its own blank line;
        submitting leaves that to on_check, which appends the Checks item."""
        if self.round_no == 0:
            return
        task = self.first_task if self.round_no == 1 else \
            (self.task or "[tool results] (this run's ledger has no result summaries)")
        self.p(f"**Round {self.round_no}**")
        self.p(f"- **Task**: {_clean(task)}")
        if self.reply:
            if self.narration:
                self.p(f"- **Reply**: {_clean(self.narration)}")
            self.p("- **Called**")
            for r in self.reply:
                self.p(f"  - `{_clean(r)}`")
        else:
            head = (_clean(self.narration) + " — ") if self.narration else ""
            self.p(f"- **Reply**: {head}"
                   + ("submitted for checks" if submitting else "(no action)"))
        if self.framework:
            self.p(f"- **Framework**: {_clean(self.framework, 300)}")
        if not submitting:
            self.p("")

    def on_round(self, ev) -> None:
        if ev.round_no == 1 and self.round_no >= 1:
            # A new session in the same bucket (apply's next assumption): flush
            # the previous round, then a blank line to separate them.
            self._flush_round()
            self.p("")
            self.accum = None
        else:
            self._flush_round()
        self.round_no = ev.round_no
        self.task = self.accum       # last round's tool results are this round's task
        self.accum = None
        self.reply = []
        self.narration = None
        self.framework = None

    def on_narration(self, text: str) -> None:
        self.narration = text

    def on_framework(self, text: str) -> None:
        self.framework = text

    def on_tool_called(self, ev) -> None:
        self.reply.append(f"{ev.tool}({ev.args_digest})")

    def on_tool_returned(self, ev) -> None:
        digest = getattr(ev, "result_digest", "") or ""
        piece = f"{ev.tool} → {digest}" if digest else f"{ev.tool} returned"
        self.accum = (self.accum + "; " + piece) if self.accum else \
            f"[tool results] {piece}"

    def on_check(self, ev) -> None:
        # The submitting round, then the framework's side of the exchange.
        self._flush_round(submitting=True)
        if ev.passed:
            self.p(f"- **Checks**: {_PASS}")
        else:
            self.p(f"- **Checks**: {_FAIL}, {len(ev.findings)} finding(s) sent back for repair:")
            for f in ev.findings:
                self.p(f"  - {_clean(f, 200)}")
        self.p("")
        self.round_no = 0
        self.task = None
        self.accum = ("[check diagnosis] "
                      + "; ".join(_clean(f, 80) for f in ev.findings[:3])) if ev.findings else None
        self.reply = []
        self.narration = None
        self.framework = None

    def close(self) -> None:
        self._flush_round()
        self.round_no = 0


def _assignment_key(rows: list):
    """An assignment's identity: the set of (assumption id, value) pairs.
    Ground truth is keyed the same way, which lets a cross-check cell find the
    scenario that produced it with no name matching in between."""
    return frozenset((r.get("id"), r.get("subtype")) for r in rows)


def _crosscheck_index(events: list) -> dict:
    """(goal, assignment key) → the compared cell. Empty for a run without
    ground truth, and then the ground-truth columns do not appear."""
    idx = {}
    for ev in events:
        if type(ev).__name__ != "CrossChecked":
            continue
        for c in ev.cells:
            key = frozenset((x.get("id"), x.get("subtype")) for x in c["scenario"])
            idx[(c["id"], key)] = c
    return idx


def _render(events: list, meta: dict) -> str:
    lines: list[str] = []
    p = lines.append
    usage = _Usage(events)
    # cross_check runs after the scenario stage, but this page is projected
    # once the run has ended, so its answers are already on the ledger.
    graded = _crosscheck_index(events)

    status = meta.get("status", "?")
    p(f"# {meta.get('protocol', '?')} / run {meta.get('run_name', '?')}"
      + (f"(sub-protocol {meta['subprotocol']})" if meta.get("subprotocol") else ""))
    span = _time_span(events)
    badge, word = _RUN_STATUS.get(status, ("⏳", status))
    p(f"**Status**: {badge} {word}" + (f" · {span}" if span else ""))
    if meta.get("ground_truth"):
        p(f"ground truth: {meta['ground_truth']}")
    p("")

    # Concurrent scenarios interleave by time in the ledger, so their events are
    # bucketed and presented one whole scenario at a time; the main timeline
    # carries only global events. RunStarted is the boundary between re-runs.
    buckets: dict[str, list] = {}
    for ev in events:
        if ev.scenario is not None:
            buckets.setdefault(ev.scenario, []).append(ev)

    attempt = 0
    flushed: set[int] = set()
    numbers: dict[str, int] = {}      # scenario label → its 08_NN presentation number
    dlg: _Dialogue | None = None

    def close_dlg() -> None:
        nonlocal dlg
        if dlg is not None:
            dlg.close()
            dlg = None

    for ev in events:
        t = type(ev).__name__
        if ev.scenario is not None:
            continue
        if t == "RunStarted":
            close_dlg()
            attempt += 1
            if attempt > 1:
                p(f"\n# Execution {attempt}"
                  + (f" (re-entered from {ev.from_node})" if ev.from_node else " (full re-run)"))
        elif t == "NodeStarted":
            close_dlg()
            p(f"## {ev.dir or ev.node}")
            p("")
            dlg = _Dialogue(p, _NODE_TASKS.get(ev.node, ev.node))
        elif t == "RoundStarted":
            if dlg is not None:
                dlg.on_round(ev)
        elif t == "ToolCalled":
            if dlg is not None:
                dlg.on_tool_called(ev)
        elif t == "ToolReturned":
            if dlg is not None:
                dlg.on_tool_returned(ev)
        elif t == "NodeProgress":
            if dlg is not None and dlg.round_no >= 1:
                dlg.on_narration(ev.text)     # inside a round: narration
            else:
                p(f"· {ev.text}")             # outside a round: a node information line
        elif t == "FrameworkAction":
            if dlg is not None:
                dlg.on_framework(ev.text)
        elif t == "CheckReport":
            if dlg is not None:
                dlg.on_check(ev)
        elif t == "CrossChecked":
            ok = sum(1 for c in ev.cells if c["match"])
            p(f"· {ok}/{len(ev.cells)} cell(s) agree with ground truth "
              f"— cell by cell in each scenario's verdict table above")
        elif t == "NodeFinished":
            close_dlg()
            # Every step that runs sessions per identity flushes at its own
            # boundary, so the root model's sessions land in the root model's
            # section rather than in the scenario stage that came after it.
            if ev.node in ("build_world", "build_root", "scenarios"):
                _flush_scenarios(p, buckets, flushed, numbers, before=ev.seq,
                                 usage=usage, graded=graded, node=ev.node)
            arts = ", ".join(f"`{a}`" for a in ev.artifacts) if ev.artifacts \
                else "no artifacts written"
            p("")
            if ev.status == "ok":
                p(f"✅ done — artifacts: {arts}")
            elif ev.status == "check_failed":
                # The node ran to the end and wrote its product; its check is
                # what says no, so this is not a crash.
                p(f"≠ done, differs from the corpus — artifacts: {arts}")
            else:
                p("💥 node failed — it could not finish; see the reason below")
            if spent := _Usage.line(usage.by_node.get(ev.node)):
                p(f"💰 tokens: {spent}")
            p("")
        elif t == "GapVerdict":
            close_dlg()
            word = "accepted, rolling back and re-running" if ev.accepted else "rejected"
            p(f"⚠ gap ruling: {word} ({ev.reason})")
        elif t == "Invalidated":
            close_dlg()
            names = ", ".join(ev.targets)
            p(f"↺ superseded: {names} — the step ran again into a directory "
              f"of its own; nothing here was renamed or overwritten")
        elif t == "Interrupted":
            close_dlg()
            p(f"✋ interrupted (scope={ev.scope})")
        elif t == "RunFailed":
            close_dlg()
            _flush_scenarios(p, buckets, flushed, numbers, before=ev.seq,
                             usage=usage, graded=graded)
            p("\n" + ("**differs from the corpus**" if ev.kind == "check"
                      else "**run failed**")
              + (f" at `{ev.where}`" if ev.where else "") + f": {ev.reason}")
        # RunFinished and AwaitingConfirm get no line of their own: the final
        # state is in the status at the top.
    close_dlg()
    _flush_scenarios(p, buckets, flushed, numbers, before=None, usage=usage,
                     graded=graded)

    _render_usage(p, usage)
    p("")
    p("---")
    p("Artifact paths are relative to this directory; the full text of every round is in transcript.jsonl under the matching node directory, "
      "with 00_prompt.md beside it holding what that session was told (tools, system prompt, task), "
      "and a step that runs outside a node's own loop names its own session file on the line that reports it.")
    return "\n".join(lines) + "\n"


def _flush_scenarios(p, buckets: dict[str, list], flushed: set[int],
                     numbers: dict[str, int], before: int | None,
                     usage: "_Usage", graded: dict,
                     node: str = "scenarios") -> None:
    """Emit the buffered per-identity events with seq earlier than ``before``
    (None means all of them), one whole identity at a time. Bucketing is two
    deep: by scenario, then by workflow within it, each workflow rendered as
    one continuous dialogue and numbered in presentation order — the true
    ordering stays in events.jsonl. ``node`` is the step whose NodeFinished is
    flushing, so a session renders under the step that actually ran it."""
    order = sorted(buckets)
    for label in order:
        pending = [e for e in buckets[label]
                   if e.seq not in flushed and (before is None or e.seq < before)]
        if not pending:
            continue
        # The step's own number, off its directory. A ledger written without
        # one has no number to show, and an empty prefix says so rather than
        # slicing the node's name in half.
        name = _dirs.get(node, "")
        stage = name.split("_", 1)[0] if name[:1].isdigit() else ""
        if node == "build_world":
            # One identity, one section, and it is not a scenario: it takes no
            # number from the scenarios' sequence.
            p(f"### {stage}_01 · World model" if stage else "### World model")
        elif node == "build_root":
            p(f"### {stage}_01 · Root model")
        else:
            if label not in numbers:
                numbers[label] = len(numbers) + 1
            p(f"### {stage}_{numbers[label]:02d} · Scenario {label}")
        p("")
        flows: dict[str, list] = {}
        info: list[str] = []
        finish = None
        assignment: list = []
        for ev in pending:
            flushed.add(ev.seq)
            t = type(ev).__name__
            if t == "ScenarioFinished":
                finish = ev
                continue
            if t == "ScenarioStarted":
                assignment = list(ev.assignment)   # empty when never recorded
                continue
            # The unit is the session's own address. A ledger with no `unit`
            # field carries the composite in `node` ("inject:<scenario>:<cell>"),
            # so the scenario still needs stripping out of it.
            short = ev.unit or (ev.node or "").replace(f":{label}", "", 1)
            if t == "NodeProgress" and short == "apply":
                # a stage summary line, not part of any session
                info.append(ev.text)
                continue
            flows.setdefault(short, []).append(ev)

        if assignment:
            _assignment_table(p, assignment)
        for line in info:
            p(f"· {_clean(line)}")
        if info:
            p("")
        for flow, fevs in flows.items():
            kind, rest = _flow_kind(flow)
            if kind == "apply" and rest:
                p(f"**Apply {rest}**")
            elif kind == "inject" and rest:
                p(f"**Inject family {rest}**")
            elif flow == "apply":
                p("**Apply**")
            else:
                p(f"**{flow}**")
            p("")
            dlg = _Dialogue(p, _flow_task(flow))
            for ev in fevs:
                t = type(ev).__name__
                if t == "RoundStarted":
                    dlg.on_round(ev)
                elif t == "ToolCalled":
                    dlg.on_tool_called(ev)
                elif t == "ToolReturned":
                    dlg.on_tool_returned(ev)
                elif t == "NodeProgress":
                    dlg.on_narration(ev.text)
                elif t == "FrameworkAction":
                    dlg.on_framework(ev.text)
                elif t == "CheckReport":
                    dlg.on_check(ev)
                elif t == "GapReported":
                    dlg.close()
                    p(f"⚠ gap reported -> {ev.target}: missing {ev.missing!r}")
            dlg.close()   # every dialogue path closes with its own blank line
        if finish is not None:
            # An assignment with no rows matches no cross-check cell, and the
            # table then drops its ground-truth columns.
            key = _assignment_key(assignment)
            cells = {g: graded[(g, key)] for g in finish.verdicts
                     if (g, key) in graded}
            combo = " · ".join(f"`{r.get('id')}={r.get('subtype')}`" for r in assignment)
            p("**Scenario verdict**" + (f" — under {combo}" if combo else ""))
            p("")
            if finish.verdicts:
                _verdict_table(p, finish.verdicts, cells)
            else:
                p("(none)")
                p("")
            if spent := _Usage.line(usage.by_scenario.get(label)):
                p(f"💰 tokens: {spent}")
            p("")


def _render_usage(p, usage: _Usage) -> None:
    """The token bill: one row per node in the order the nodes ran, then the
    run's own total, which is the number the API actually charged for."""
    if not (usage.total[0] or usage.total[1]):
        return
    p("")
    p("## Token usage")
    p("")
    p("| step | input | output | cached |")
    p("|---|---|---|---|")
    for node, row in usage.by_node.items():
        p(f"| {_dirs.get(node, node)} | {_tok(row[0])} | {_tok(row[1])} "
          f"| {_tok(row[2]) if row[2] else '-'} |")
    if len(usage.by_scenario) > 1:
        for label, row in sorted(usage.by_scenario.items()):
            p(f"| ⤷ {label} | {_tok(row[0])} | {_tok(row[1])} "
              f"| {_tok(row[2]) if row[2] else '-'} |")
    t = usage.total
    p(f"| **total** | **{_tok(t[0])}** | **{_tok(t[1])}** "
      f"| **{_tok(t[2]) if t[2] else '-'}** |")


def _time_span(events: list) -> str:
    stamped = [e.ts for e in events if e.ts]
    if not stamped:
        return ""
    return f"{stamped[0]} → {stamped[-1]}"
