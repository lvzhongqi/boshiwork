# The experiments

This directory holds the three batches the paper reports, the runner that
executes them, and the read-only entry point that rebuilds the paper's tables
from published runs.

| | what it is |
| --- | --- |
| `batches.py` | **what each batch means**, as config overrides. Code |
| `protocols.yaml` | **which protocols**: the catalog, and the selection every batch runs. Data |
| `config.example.yaml` | **this machine**: one credential, the corpus, where output goes, how many at once. Copied to `config.yaml` on first use |
| `batch/` | the runner: one entry point, the process scheduler, and one file per batch kind |
| `oneshot/` | the monolithic one-shot baseline the pipeline is measured against, driven by `batch/baseline.py` |
| `reproduce.py` | reads `../runs/` and VerdictBench, and writes the paper's results |

Each batch writes its runs to `work_root` on the machine that ran it; the
published selection of those runs is `runs/` at the top of this repository.

## Reproduce the paper results

```bash
python -m experiments.reproduce
```

A pure file read, offline. It writes six outputs to `reproduced/`:
reviewer-friendly `results.md`, paper-ready `results.tex` and `measured.tex`,
`results.csv`, `results.json`, and the appendix body `dataset_rows.tex`. The
default is the paper's mean over the latest three main runs per analysis unit;
`--help` lists the path and aggregation overrides.

## Run a batch

Fill in `config.yaml` — one credential — and then:

```bash
python -m experiments.batch run main
python -m experiments.batch run claims
python -m experiments.batch run baseline
```

| batch | what it is |
| --- | --- |
| `main` | the full node pipeline, extraction through cross-check |
| `claims` | claims extraction, measured on its own |
| `baseline` | the one-shot control group |

Three commands take a batch — `run`, `status`, `stop` — and one argument, its
name. `batches.py::RUNNERS` decides which runner executes which.

`batch/README.md` has the rest: what each command does, and how
`protocols.yaml` chooses the protocols.
