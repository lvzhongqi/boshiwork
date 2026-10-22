# Orrery — experimental data

Every run behind the paper's tables, in full: the ProVerif models the pipeline
wrote, the prompts it sent to the model, the replies it got back, the checks
each step ran, and a log that lets the console replay the run.

568 runs, 101 protocols, 3 batches. `MANIFEST.txt` lists the counts and the
protocol names.

The code and the protocol corpus are in the repository:

> https://anonymous.4open.science/r/Orrery-F56D

## Layout

Runs sit at `experiments/<batch>/<protocol>/<run>/`.

| batch | what it ran | |
|---|---|---|
| `main` | the whole pipeline, from reading the document to a verdict per scenario | 101 protocols, 303 runs |
| `claims` | claim extraction only | 101 protocols, 103 runs |
| `baseline` | the one-shot baseline | 97 protocols, 162 runs |

A run directory holds:

| | |
|---|---|
| `NN_<node>/` | one directory per pipeline step, numbered in the order it ran. Inside: that step's prompt, the model transcript, the checks it ran, and what it produced (`flow.pv`, JSON, and so on) |
| `events.jsonl` | the log the console replays |
| `stages.jsonl` | what each step was given, and what it returned |
| `run.json` | which protocol this run analysed, and which corpus entry it was scored against |
| `config.yaml` | the settings this run used. The API key is masked |
| `eval/` | how the run scored against the corpus ground truth |
| `run.log`, `work.md` | the run log, and the run's own working notes |

## Replaying a run

The console replays any run here from its log. This works offline. You do not
need an API key, and you do not need ProVerif.

Point `playback_root` at **one batch directory**, not at `experiments/`. The
console looks for `<playback_root>/<protocol>/<run>/`, so one level too high
finds nothing. Use an absolute path.

```yaml
paths:
  playback_root: /absolute/path/to/orrery_experiments_results/experiments/main
  lib_root: /absolute/path/to/VerdictBench
```

Then run `orrery` and open the console. The same path can be typed into the
**run root** box at the top of the launch panel instead, which saves it to the
config; `work_root` is a different setting, for where live runs are written.
With `lib_root` set, you can also compare each run against the corpus's
reference model and ground truth.

## What we removed

**Anything that says who we are.** Home directory paths, API keys, machine
names, account names, our own names. None of it appears anywhere in these files.

**The encrypted blob the API returns with each thinking block.** This is not
the model's reasoning. Next to the reasoning text, the API sends back a few
kilobytes of ciphertext (`thinking_blocks[].encrypted_content`) that it uses
only to continue the same session. We replaced each one with a short marker.
The model's reasoning and its replies are all still here.

**Specification text we may not republish.** ISO/IEC, 3GPP and the
FIDO Alliance forbid redistributing their specifications, and some prompts and
model replies quote them. We replaced each quoted passage with a marker saying
what stood there. The files still load, and those runs still show their
verdicts.

We removed nothing else. Every model, every verdict and every log is here.
