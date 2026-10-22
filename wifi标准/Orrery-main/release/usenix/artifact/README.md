# Orrery

Orrery is an agent framework that turns a cryptographic protocol specification
into formal code automatically and analyses it, so a security question asked
against a document is answered by a machine-checked ProVerif verdict.

## Layout

| | |
|---|---|
| `orrery/` | the engine, and the web console |
| `experiments/` | the batch runner, the baseline, and the table reproducer |
| `VerdictBench/` | the protocol corpus, 101 units |
| `runs/` | the recorded runs behind the paper |
| `config.example.yaml` | the annotated configuration reference |

## Getting started

### Prerequisites

* Python 3.11+ — 3.12.13 is what the reported runs used. Every dependency is
  pinned to an exact version in `pyproject.toml`, so the install below
  reproduces that environment.
* ProVerif **2.05**, and an API key — for running the pipeline for real.
  Replaying a recorded run and rebuilding the paper's tables work on the files
  shipped here alone.

### Install

```bash
pip install -e .
```

### 1. Run it in the browser

```bash
orrery
```

The console opens at `http://127.0.0.1:8000`. Pick a protocol, press start, and
watch the pipeline work.

It starts in **recorded mode**, which replays finished runs from their own logs
— seven protocols are shipped complete enough to replay, step by step, exactly
as they happened.

The full set of runs is archived on Zenodo, DOI `10.5281/zenodo.22149340`. The
record is restricted for review; the link below carries its access token, so it
opens and downloads without a Zenodo account and does not expire.

```
https://zenodo.org/records/22149340?token=eyJhbGciOiJIUzUxMiJ9.eyJpZCI6IjFmMDVlYjY5LWM4MzMtNGRiZS1iZjhkLWExNDc3OTRlNTRhYSIsImRhdGEiOnt9LCJyYW5kb20iOiIyMWVlYjRiN2U2OWUxZWU1ZjQ5NThkNGVkMWQwY2JlNCJ9.FDEkqXYkqvZoRONLwZGMieOfU5QHnYjNmkasr4cDN7wC53XnMhG-6H9ISr5FJwqA9IQQAOosrYwdN-AxChfOdg
```

To replay those, point the console at a single batch directory inside it —
`…/experiments/main`, not `…/experiments`. Either type that path into the **run
root** box at the top of the launch panel and press scan, which saves it, or set
it in `config.yaml`:

```yaml
paths:
  playback_root: /absolute/path/to/experiments/main
```

`paths.work_root` is a different setting — it is where **live** mode writes new
runs.

To run the pipeline for real, flip the switch in the top-left corner to
**live**, and fill in your API key and the path to your ProVerif binary in the
Config panel on the left. The launch panel then offers two ways in:

* **corpus** — browse to the `VerdictBench/` folder shipped here and pick a
  protocol. The academic, IETF and Signal units carry their document and run
  end to end; the ISO/IEC, 3GPP and FIDO units need a licensed copy of the
  specification under their own `source/` (see `VerdictBench/README.md`);
* **my document** — point at a protocol specification of your own, a folder or a
  single file, and run it end to end.

### 2. Reproduce the paper's tables — offline

```bash
python -m experiments.reproduce
```

Reads `VerdictBench/` and `runs/` and writes Markdown, LaTeX, CSV and JSON
views to `reproduced/`: `reproduced/results.md` is the one to read,
`reproduced/measured.tex` holds the macros the paper consumes. It is a pure file
read, offline.

### 3. Run one protocol

Needs the API key and the ProVerif path from step 1.

```bash
orrery run --name NSPK --dir VerdictBench/academic/NSPK
```

It prints the run directory before it starts, one Ctrl-C stops it cleanly, and
the run is then open in the console like any other. `orrery run --help` lists
what can be pinned or supplied per run.

### 4. Run a batch

A batch is one named experiment over the whole corpus. The batch runner has **its
own** config, `experiments/config.yaml`, created from
`experiments/config.example.yaml` on first use; fill in the same two things.

```bash
python -m experiments.batch run main        # the full pipeline
python -m experiments.batch run claims      # claims extraction alone
python -m experiments.batch run baseline    # the one-shot control
```

`status` and `stop` are the other two commands, with the same argument. The
published runs used ProVerif 2.05 and `gpt-5.6-sol`; the batch prints the
version and the model it found as it starts, so your own numbers are labelled
with what produced them. `experiments/README.md` and
`experiments/batch/README.md` carry the rest.

## What is not included

1. **The full experiment data.** For size, this repository ships only what a
   reproduction reads: each run's event log, its verdicts, and how they scored
   against the corpus. The per-step artifacts — the ProVerif models the pipeline
   wrote, the prompts, the model replies and the solver output — are here for the
   seven replayable protocols only. Every run is archived in full in the Zenodo
   record above, [`10.5281/zenodo.22149340`](https://zenodo.org/records/22149340?token=eyJhbGciOiJIUzUxMiJ9.eyJpZCI6IjFmMDVlYjY5LWM4MzMtNGRiZS1iZjhkLWExNDc3OTRlNTRhYSIsImRhdGEiOnt9LCJyYW5kb20iOiIyMWVlYjRiN2U2OWUxZWU1ZjQ5NThkNGVkMWQwY2JlNCJ9.FDEkqXYkqvZoRONLwZGMieOfU5QHnYjNmkasr4cDN7wC53XnMhG-6H9ISr5FJwqA9IQQAOosrYwdN-AxChfOdg).
2. **Third-party specification text.** ISO/IEC, 3GPP and the FIDO Alliance
   forbid redistributing their specifications, and that lands in two different
   ways. The documents are simply absent: under `VerdictBench/ISO/*/source/`,
   `3gpp/*/source/` and `informal/FIDO/*/source/` only each directory's own
   `README.md` is left, recording what the document is and the notice the
   decision rests on. Where their text instead sits inside a file that has to
   ship — a prompt, a model reply, a sub-protocol's scope note — the passage
   alone is replaced by the marker `[withheld: third-party specification text]`
   and the file still loads. Those units keep their annotations, models and
   verdicts, so their results stay checkable and their recorded runs show the
   pipeline working on them. A redaction does make a run harder to follow, and
   end-to-end reproduction from a document is demonstrated on the other
   protocols. See `VerdictBench/README.md`.
