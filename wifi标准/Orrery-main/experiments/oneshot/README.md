# The one-shot baseline

One prompt, one reply, straight to a ProVerif model with its queries. This is
the control group for the node pipeline: the same protocol, the same claims
files and the same ProVerif binary, with the pipeline's decomposition replaced
by a single `system + user` request.

The runner reads the document, `assumptions.json`, `properties.json` and
`claims.json`, then makes one independent call per selected scenario. Each call
receives the run-wide world, that scenario's complete assignment and its goals.
Output is one `.pv` per scenario, its verdicts, and a cell-by-cell comparison
against ground truth where the corpus carries one.

## Run it

```bash
PYTHONPATH=. python -m experiments.oneshot.runner --dir VerdictBench/academic/NSPK --name NSPK
```

A subprotocol, and a different model:

```bash
PYTHONPATH=. python -m experiments.oneshot.runner --dir VerdictBench/rfc/EDHOC/draft-08 --subprotocol symmetric --model claude-opus-5
```

| flag | default | what it does |
| --- | --- | --- |
| `--dir` | required | the protocol directory in the corpus |
| `--name` | the directory's name | protocol name |
| `--subprotocol` | — | one mechanism under `subprotocols/` |
| `--run-name` | the protocol's name | run directory name |
| `--config` | the checkout's `config.yaml` | config file; repeatable, each merged over the last |
| `--out` | `experiments/oneshot/runs` | where runs are written |
| `--effort` | `high` | reasoning effort, matching `extract_flow` |
| `--backend` | the config's | override `llm.backend` |
| `--model` | the config's | override `llm.model` |

One more setting comes from the selected Orrery config: how many scenarios run
at once, `pipeline.max_scenarios_concurrency`.

Re-entering the same `--run-name` keeps every scenario that already has a
`verdict.json` and runs the remaining ones.

## What it writes

```text
experiments/oneshot/runs/<protocol>/<run>/
├── run.json                 # model, effort, tokens, per-scenario status, comparison summary
├── results.json             # LIB format: one answer per property
├── cases_results.json       # LIB format: one cell per (property, scenario)
├── crosscheck.json          # the full compare() report, where the corpus ships ground truth
└── scenarios/<scenario>/
    ├── 00_prompt.md         # the bytes that were sent: two system blocks, then the user message
    ├── reply.md             # the single raw reply
    ├── proverif_submitted.* # the reply's own source, with its probe, and the solver's raw output
    ├── model.pv             # the same model with the probe removed — what the verdicts came from
    ├── proverif_clean.*     # that model's run, always: the probe run cannot answer goals
    ├── proverif_precise_<goal>.* # the bounded `preciseActions` retry a `cannot_be_proved` goal gets
    ├── proverif_vacuity.*   # the same model with only `query event(end_<goal>(…))` left
    └── verdict.json         # per-goal verdicts, probe placement, reachability, vacuity, notes, tokens
```

`verdict.json` records three ways a model fails ahead of being wrong:
`probe.problems` (a probe missing, or placed where it proves nothing), `reach`
(a role that stops before the end of its body) and `vacuous` (a goal whose
`end_` event happens on no trace, so ProVerif proved its query over nothing).
`experiments/reproduce.py` totals them as the `Syn` and `Reach` columns of the
baseline table.
