"""The one-shot baseline: one prompt per scenario, straight to a .pv with its
queries, then ProVerif and the same aggregation the pipeline uses.

    PYTHONPATH=. python -m experiments.oneshot.runner \
        --dir <corpus>/academic/NSPK --name NSPK

There are no tools and no repair turn: a scenario whose reply carries no
parseable model is recorded with all goals ``unknown``. Failures of this script
itself — missing config, unreadable corpus — still raise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from orrery.infra.llm.client import ChatMessage, Effort, Role
from orrery.infra.llm.factory import build_chat_client
from orrery.infra.proverif.outcome import OutcomeKind, classify
from orrery.infra.proverif.runner import ProVerifRunner
from orrery.modules.document import DocumentLoaderService, ProtocolSource
from orrery.modules.document.corpus import inline_corpus
from orrery.modules.libschema.io import load_assumptions, load_claims, load_properties
from orrery.modules.libschema.resolve import expand_assignments
from orrery.modules.pvtext.parse import queries as pv_queries
from orrery.modules.pvtext.parse import query_owners
from orrery.modules.pvtext.edits import replace_queries
from orrery.modules.pvtext.probe import remove_probe
from orrery.modules.verdicts.split import combine
from orrery.nodes.apply.realizers import subtype_is_noop
from orrery.nodes.cross_check.node import compare
from orrery.nodes.solve.node import PRECISE
from orrery.pipeline.config import (
    MissingConfigError, ensure_config, load_config,
)
from orrery.services.store.layout import RunLayout
from orrery.version import VOCAB_VERSION

from experiments.oneshot import probe
from experiments.oneshot.prompt import build_prompt, scenario_json
from experiments.oneshot.reference import modeling_rules_reference

_EFFORTS = {e.value: e for e in Effort}


class _Tee:
    """Write a stream to the terminal and the run-local log together."""

    def __init__(self, terminal, log) -> None:
        self.terminal = terminal
        self.log = log

    def write(self, text: str) -> int:
        self.terminal.write(text)
        self.log.write(text)
        return len(text)

    def flush(self) -> None:
        self.terminal.flush()
        self.log.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.terminal, "isatty", lambda: False)())


@contextmanager
def _tee_stdio(path: Path):
    """Mirror stdout and stderr into the run's own log while the batch still
    sees them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as log:
        with redirect_stdout(_Tee(sys.stdout, log)), \
                redirect_stderr(_Tee(sys.stderr, log)):
            yield


_FENCE_RE = re.compile(r"```(\w*)[ \t]*\n(.*?)```", re.S)
# Some relays swallow the first token of a long reply, turning "```proverif\n…"
# into "proverif\n…".
_HEADLESS_RE = re.compile(r"\A\s*`{0,2}proverif[ \t]*\n(.*?)```", re.S)


def extract_pv(content: str) -> str:
    """The single ``proverif`` block in the reply, stripped.

    Raises SubmissionError when the reply carries no such block or more than one.
    """
    blocks = [body for lang, body in _FENCE_RE.findall(content or "")
              if lang == "proverif"]
    if len(blocks) == 1:
        return blocks[0].strip()
    if not blocks:
        m = _HEADLESS_RE.match(content or "")
        if m:
            return m.group(1).strip()
        raise SubmissionError("the reply carries no ```proverif block")
    raise SubmissionError(
        f"the reply carries {len(blocks)} ```proverif blocks; exactly one whole "
        f".pv was asked for")


class SubmissionError(Exception):
    """The one reply was not a single complete model."""


def split_verdicts(verdicts, goal_ids: list[str]) -> tuple[dict, list[str]]:
    """``{goal_id: "true"|"false"|"unknown"}`` plus notes explaining every
    ``unknown`` that came from the split rather than from ProVerif.

    Attribution goes through the pipeline's ``query_owners``. A query naming
    zero or several goals is recorded as a note and leaves its goal unknown.
    """
    per_goal: dict[str, list[str]] = {g: [] for g in goal_ids}
    notes: list[str] = []
    for v in verdicts:
        owners = query_owners(v.query, goal_ids)
        if len(owners) == 1:
            per_goal[owners[0]].append(v.verdict)
        elif not owners:
            notes.append(f"query names no goal id: {v.query}")
        else:
            notes.append(f"query names {len(owners)} goal ids {owners}: {v.query}")
    out = {}
    for g in goal_ids:
        if per_goal[g]:
            out[g] = combine(per_goal[g])
        else:
            out[g] = "unknown"
            notes.append(f"no verdict for goal {g}")
    return out, notes


class InstrumentationError(RuntimeError):
    """A .pv this script derived from the submitted model fails to parse while
    the submitted model itself did — a bug here, not a baseline failure."""


async def _run(pv_runner, text: str, log_to: Path, what: str):
    out = classify(await pv_runner.run(text, log_to=log_to))
    if out.kind is OutcomeKind.SYNTAX_ERROR:
        raise InstrumentationError(
            f"the {what} form does not parse while the submitted model did: "
            f"{'; '.join(out.errors) or 'no line-level error'} -- see {log_to}.pv")
    return out


async def _retry_cannot_be_proved(*, pv_runner, out_dir: Path, pv: str,
                                  goal_ids: list[str], verdicts: dict,
                                  raw_verdicts, timeout_s: int) -> tuple[dict, list[str], dict]:
    """Re-solve each ``cannot_be_proved`` goal alone under preciseActions and
    return the updated verdicts, notes and per-goal evidence.

    A solver retry only: the LLM is never called and the model text is unchanged.
    Goals unknown for a missing or unattributable query are skipped.
    """
    undecided = sorted({owner
                        for v in raw_verdicts if v.verdict == "cannot_be_proved"
                        for owner in query_owners(v.query, goal_ids)
                        if verdicts.get(owner) == "unknown"})
    notes, evidence = [], {}
    for gid in undecided:
        mine = [q for q in pv_queries(pv) if query_owners(q, goal_ids) == [gid]]
        if not mine:
            continue
        raw = await pv_runner.run(
            PRECISE + replace_queries(pv, mine),
            log_to=out_dir / f"proverif_precise_{gid}",
            timeout_s=timeout_s)
        out = classify(raw)
        retried = "unknown"
        retry_notes: list[str] = []
        if out.kind is OutcomeKind.OK and out.verdicts:
            got, retry_notes = split_verdicts(out.verdicts, [gid])
            retried = got[gid]
            if retried != "unknown":
                verdicts[gid] = retried
        evidence[gid] = {
            "outcome": out.kind.value,
            "verdict": retried,
            "duration_s": round(raw.duration_s, 1),
        }
        notes.append(
            f"goal {gid}: cannot_be_proved triggered a preciseActions retry; "
            f"{retried}")
        notes.extend(f"goal {gid} preciseActions: {n}" for n in retry_notes)
    return verdicts, notes, evidence


async def measure(*, pv_runner, out_dir: Path, pv: str, submitted,
                  goal_ids: list[str], precise_retry: bool,
                  precise_retry_timeout_s: int) -> dict:
    """The goal verdicts, probe reachability and vacuity check for a model that
    has already cleared the syntax gate.

    ``submitted`` is that gate's ProVerif outcome and carries the probe answers.
    Goal verdicts come from a second solve of ``remove_probe`` of the same
    text, always: the probe run carries ``reconstructTrace = false`` (the
    probe setting instrument() adds), under which a falsifiable goal reads
    ``cannot_be_proved``, so its verdicts are never reused as goal verdicts.
    """
    place = probe.placement(pv)
    reach = probe.read_reach(submitted.verdicts, place)

    clean = remove_probe(pv)
    # ProVerif writes its own log copy only when it is actually called, so the
    # model the goal verdicts came from is saved here under one fixed name.
    (out_dir / "model.pv").write_text(clean, encoding="utf-8")
    goals = await _run(pv_runner, clean, out_dir / "proverif_clean", "probe-free")
    verdicts, notes = split_verdicts(goals.verdicts, goal_ids)
    precise_retries = {}
    if precise_retry and goals.kind is OutcomeKind.OK:
        verdicts, retry_notes, precise_retries = await _retry_cannot_be_proved(
            pv_runner=pv_runner, out_dir=out_dir, pv=clean,
            goal_ids=goal_ids, verdicts=verdicts,
            raw_verdicts=goals.verdicts,
            timeout_s=precise_retry_timeout_s)
        notes += retry_notes
    if goals is not submitted and goals.kind is not OutcomeKind.OK:
        notes.append(f"probe-free run outcome: {goals.kind.value}")

    ends = probe.end_events(clean, goal_ids)
    vacuous: dict[str, bool] = {}
    if ends:
        vac = await _run(pv_runner, probe.vacuity_form(pv, ends),
                         out_dir / "proverif_vacuity", "vacuity")
        vacuous = probe.read_vacuity(vac.verdicts, ends)
    notes += [f"goal {g}: `end_{g}` is unreachable, so its query was proved on "
              f"no trace at all" for g, dead in sorted(vacuous.items()) if dead]
    notes += [f"role {r} was marked but ProVerif returned no verdict for its probe"
              for r in reach["no_verdict"]]
    notes += place["problems"]

    return {"queries": pv_queries(clean), "verdicts": verdicts,
            "precise_retries": precise_retries,
            "probe": place, "reach": reach, "vacuous": vacuous, "notes": notes}


async def run_scenario(*, llm, pv_runner, out_dir: Path, corpus: str,
                       protocol: str, world_json: str,
                       name: str,
                       scenario, properties_json: str, goal_ids: list[str],
                       modeling_rules: str,
                       effort: Effort,
                       precise_retry: bool,
                       precise_retry_timeout_s: int,
                       lang: str = "en") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    system, user = build_prompt(
        corpus=corpus, protocol=protocol, world_json=world_json,
        scenario_name=name, scenario_json=scenario_json(scenario),
        properties_json=properties_json, goal_ids=goal_ids,
        modeling_rules=modeling_rules, lang=lang)
    (out_dir / "00_prompt.md").write_text(
        "\n\n---\n\n".join([*system, user]), encoding="utf-8")

    messages = [ChatMessage(Role.SYSTEM, system), ChatMessage(Role.USER, user)]
    usage = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}
    started = time.monotonic()

    resp = await llm.invoke(messages, effort=effort)
    usage["input_tokens"] = resp.usage.input_tokens
    usage["output_tokens"] = resp.usage.output_tokens
    usage["cached_tokens"] = resp.usage.cached_tokens
    (out_dir / "reply.md").write_text(resp.content or "", encoding="utf-8")

    try:
        pv = probe.instrument(extract_pv(resp.content))
    except SubmissionError as e:
        problems = [str(e)]
    else:
        raw = await pv_runner.run(pv, log_to=out_dir / "proverif_submitted")
        outcome = classify(raw)
        if outcome.kind is not OutcomeKind.SYNTAX_ERROR:
            measured = await measure(
                pv_runner=pv_runner, out_dir=out_dir, pv=pv,
                submitted=outcome, goal_ids=goal_ids,
                precise_retry=precise_retry,
                precise_retry_timeout_s=precise_retry_timeout_s)
            notes = measured.pop("notes")
            if outcome.kind is not OutcomeKind.OK:
                notes.append(f"proverif outcome: {outcome.kind.value}")
            result = {
                "scenario": name, "status": "ok",
                "outcome": outcome.kind.value,
                **measured,
                "notes": notes,
                "usage": usage,
                "duration_s": round(time.monotonic() - started, 1),
            }
            (out_dir / "verdict.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        problems = outcome.errors or ["proverif reported a syntax error"]

    result = {
        "scenario": name, "status": "failed",
        "outcome": "no_model",
        "queries": [],
        "verdicts": {g: "unknown" for g in goal_ids},
        "probe": {"roles": [], "marked": [], "problems": []},
        "reach": {"per_role": {}, "all": False, "no_verdict": []},
        "vacuous": {},
        "precise_retries": {},
        "notes": ["the one-shot submission did not produce a parseable model",
                  *problems],
        "usage": usage,
        "duration_s": round(time.monotonic() - started, 1),
    }
    (out_dir / "verdict.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def aggregate(claims, alias, world_by_name, by_name, protocol_id) -> tuple[dict, dict]:
    """The ``cases_results.json`` and ``results.json`` documents, under the same
    three-valued conjunction nodes/aggregate uses: all true → true, else any
    false → false, else unknown."""
    cases, results = [], []
    for c in claims.claims:
        by_scenario, verdicts = [], []
        seen: set[str] = set()
        for ref in c.scenarios:
            name = alias[ref]
            if name in seen:
                continue
            seen.add(name)
            v = by_name[name]["verdicts"].get(c.property, "unknown")
            by_scenario.append({
                "scenario": [{"id": p.ref_id, "subtype": p.subtype}
                             for p in world_by_name[name].points],
                "verdict": v,
            })
            verdicts.append((name, v))
        cases.append({"id": c.property, "by_scenario": by_scenario})

        if all(v == "true" for _, v in verdicts):
            results.append({"id": c.property, "verdict": "true"})
        elif any(v == "false" for _, v in verdicts):
            bad = [n for n, v in verdicts if v == "false"]
            results.append({"id": c.property, "verdict": "false",
                            "description": f"does not hold in scenarios: {bad}"})
        else:
            unk = [n for n, v in verdicts if v == "unknown"]
            results.append({"id": c.property, "verdict": "unknown",
                            "description": f"undecided: no verdict for scenarios {unk}"})
    return ({"vocab_version": VOCAB_VERSION, "cases": cases},
            {"vocab_version": VOCAB_VERSION, "protocol_id": protocol_id,
             "results": results})


async def run(args) -> int:
    # A host handing the config in as a dict (the batch runner, whose file
    # carries a key of its own the engine refuses) wins over --config.
    layer = getattr(args, "config_layer", None)
    cfg = load_config(layer if layer is not None
                      else (args.config or ensure_config()),
                      overrides=_overrides(args, args.overrides))
    protocol_dir = Path(args.dir).resolve()
    root = protocol_dir / "subprotocols" / args.subprotocol if args.subprotocol else protocol_dir
    protocol = args.name or root.name

    layout = RunLayout(Path(args.out).resolve(), protocol,
                       args.run_name or protocol)
    out_root = layout.run_dir
    out_root.mkdir(parents=True, exist_ok=True)
    # Only the recorded snapshot is masked; the live cfg keeps its credential.
    layout.write_config(cfg)
    with _tee_stdio(out_root / "run.log"):
        return await _run_body(
            args, cfg, protocol_dir, root, protocol, out_root)


async def _run_body(args, cfg: dict, protocol_dir: Path, root: Path,
                    protocol: str, out_root: Path) -> int:

    lang = prompt_lang(cfg)
    assumptions = load_assumptions(root / "claims" / "assumptions.json")
    properties = load_properties(root / "claims" / "properties.json")
    claims = load_claims(root / "claims" / "claims.json", assumptions)

    source = ProtocolSource.from_directory(protocol_dir, target_name=args.subprotocol)
    doc_set = await DocumentLoaderService().load(source)
    corpus = inline_corpus(doc_set, int(cfg["document"]["inline_max_chars"]))

    worlds, alias = expand_assignments(claims, assumptions, subtype_is_noop)
    world_by_name = dict(worlds)
    goals_by_scenario: dict[str, list[str]] = {n: [] for n, _ in worlds}
    for c in claims.claims:
        for ref in c.scenarios:
            name = alias[ref]
            if c.property not in goals_by_scenario[name]:
                goals_by_scenario[name].append(c.property)

    llm = build_chat_client(cfg["llm"])
    pv_runner = ProVerifRunner(
        executable=cfg["proverif"]["executable"],
        timeout_s=int(cfg["proverif"]["timeout_s"]))
    effort = _EFFORTS[args.effort]
    world_json = json.dumps(
        [entry.to_json() for entry in assumptions.world],
        ensure_ascii=False, indent=2)
    print(f"[oneshot] {protocol}: {len(worlds)} scenario(s), "
          f"model={cfg['llm']['model']}, effort={effort.value}")

    sem = asyncio.Semaphore(int(
        cfg["pipeline"]["max_scenarios_concurrency"]))

    async def one(name, scenario):
        saved = out_root / "scenarios" / name / "verdict.json"
        if saved.is_file():
            result = json.loads(saved.read_text(encoding="utf-8"))
            print(f"[oneshot]   {name}: already finished, reused")
            return result
        gids = goals_by_scenario[name]
        goals = [properties.by_id(g) for g in gids]
        props = [goal.to_json() for goal in goals]
        async with sem:
            r = await run_scenario(
                llm=llm, pv_runner=pv_runner, out_dir=out_root / "scenarios" / name,
                corpus=corpus, protocol=protocol, world_json=world_json,
                name=name, scenario=scenario,
                properties_json=json.dumps(props, ensure_ascii=False, indent=2),
                goal_ids=gids, effort=effort,
                precise_retry=bool(cfg["solve"]["precise_actions_retry"]),
                precise_retry_timeout_s=int(
                    cfg["solve"]["precise_retry_timeout_s"]),
                modeling_rules=modeling_rules_reference(
                    world=assumptions.world, scenario=scenario,
                    goals=goals, lang=lang),
                lang=lang)
        reach = r["reach"]["per_role"]
        print(f"[oneshot]   {name}: {r['status']} ({r['outcome']}), "
              f"{r['duration_s']}s, "
              f"reach={sum(reach.values())}/{len(reach)}, "
              f"vacuous={sorted(g for g, d in r['vacuous'].items() if d)}, "
              + ", ".join(f"{k}={v}" for k, v in r["verdicts"].items()))
        return r

    started = time.monotonic()
    per_scenario = await asyncio.gather(*(one(n, s) for n, s in worlds))
    by_name = {r["scenario"]: r for r in per_scenario}

    cases_doc, results_doc = aggregate(claims, alias, world_by_name, by_name, protocol)
    (out_root / "cases_results.json").write_text(
        json.dumps(cases_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "results.json").write_text(
        json.dumps(results_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    usage = {k: sum(r["usage"][k] for r in per_scenario)
             for k in ("input_tokens", "output_tokens", "cached_tokens")}
    meta = {
        "experiment": "oneshot",
        "protocol": protocol,
        "protocol_dir": str(root),
        "subprotocol": args.subprotocol,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.monotonic() - started, 1),
        "model": cfg["llm"]["model"],
        "backend": cfg["llm"]["backend"],
        "effort": effort.value,
        "lang": lang,
        "usage": usage,
        "scenarios": [{k: r[k] for k in
                       ("scenario", "status", "outcome",
                        "probe", "reach", "vacuous", "precise_retries", "notes")}
                      for r in per_scenario],
    }

    gt = root if (root / "results").exists() else None
    if gt is not None:
        # This baseline asks the corpus's own claims, so both sides of the
        # comparison speak in the corpus's vocabulary.
        vocab = tuple(json.loads((root / "claims" / f"{kind}.json")
                                 .read_text(encoding="utf-8"))
                      for kind in ("assumptions", "properties"))
        report = compare(
            results_doc, cases_doc,
            json.loads((gt / "results" / "results.json").read_text(encoding="utf-8")),
            json.loads((gt / "results" / "cases_results.json").read_text(encoding="utf-8")),
            ours_vocab=vocab, gt_vocab=vocab)
        (out_root / "crosscheck.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        # report["results"] is the per-property table, not a count.
        prop_matched = sum(1 for r in report["results"] if r["match"])
        meta["crosscheck"] = {
            "results_total": report["results_total"],
            "results_matched": prop_matched,
            "cases_compared": report["cases_compared"],
            "cases_matched": report["cases_matched"],
            "acc": report["acc"],
        }
        print(f"[oneshot] vs ground truth: "
              f"properties {prop_matched}/{report['results_total']}, "
              f"cells {report['cases_matched']}/{report['cases_compared']} "
              f"(acc={report['acc']})")
        for m in report["results_mismatches"]:
            print(f"[oneshot]   property mismatch: {m['id']} "
                  f"ours={m['ours']} expected={m['expected']}")
        for m in report["cases_mismatches"]:
            cells = ", ".join(f"{p['id']}={p['subtype']}" for p in m["scenario"])
            print(f"[oneshot]   cell mismatch: {m['id']} [{cells}] "
                  f"ours={m['ours']} expected={m['expected']}")
    else:
        print(f"[oneshot] no ground truth under {root}/results — comparison skipped")

    (out_root / "run.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[oneshot] wrote {out_root}")
    return 0


def prompt_lang(cfg: dict) -> str:
    """The prompt language, from the same ``prompt_lang`` config key every node
    reads. Anything other than ``en`` or ``zh`` raises ValueError instead of
    falling back, so a run never quietly uses a language nobody configured."""
    lang = cfg.get("prompt_lang", "en")
    if lang not in ("en", "zh"):
        raise ValueError(
            f"[oneshot] prompt_lang must be 'en' or 'zh'; the config says "
            f"{lang!r}")
    return lang


def _overrides(args, extra: dict | None) -> dict:
    """Config overrides: ``extra`` from the calling batch runner, with this
    command line's ``--backend`` and ``--model`` layered on top."""
    out = dict(extra or {})
    llm = {k: v for k, v in (("backend", args.backend), ("model", args.model))
           if v is not None}
    if llm:
        out.setdefault("llm", {}).update(llm)
    return out


def main(argv=None, overrides: dict | None = None,
         config: dict | None = None) -> int:
    """``config`` is the user layer as a mapping, for a host that has already
    read the file (the batch runner); given, ``--config`` is not consulted."""
    p = argparse.ArgumentParser(
        prog="experiments.oneshot.runner",
        description="One prompt per scenario, straight to a ProVerif model with "
                    "its queries; the one-shot baseline for the node pipeline.")
    p.add_argument("--dir", required=True, help="the protocol directory in the corpus")
    p.add_argument("--name", default=None, help="protocol name (default: the directory's)")
    p.add_argument("--subprotocol", default=None)
    p.add_argument("--config", action="append", default=None, metavar="FILE",
                   help="config file (default: the checkout's config.yaml). "
                        "Repeatable: each one is merged over the last, which is "
                        "how a batch adds its own few lines to the file that "
                        "holds the credential")
    p.add_argument("--out", default="experiments/oneshot/runs")
    p.add_argument("--run-name", default=None, help="run directory name (default: the protocol's)")
    p.add_argument("--effort", default="high", choices=sorted(_EFFORTS))
    p.add_argument("--backend", default=None, help="override llm.backend")
    p.add_argument("--model", default=None, help="override llm.model")
    args = p.parse_args(argv)
    args.overrides = overrides
    args.config_layer = config
    try:
        return asyncio.run(run(args))
    except MissingConfigError as e:
        # An unfilled config is an answer, not a crash: print the one sentence
        # naming the missing key instead of a stack trace.
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
