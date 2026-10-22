# Releasing

Everything that turns work in this repository into something outside it. Four
scripts, one direction: the server's experiment output becomes the published
`runs/` tree, and the repository plus that tree becomes the anonymous review
copy.

They are here rather than beside what they read for the reason a packing list
is not luggage. `experiments/` is what the batch *is* — suite definitions the
scheduler reads, and the one-shot baseline's code — and it ships to reviewers,
who re-run from it. These four ship to nobody; they run once each, after the
batch is over, and their subject is a submission rather than a protocol.
Mixing them cost a reader nothing until the same directory held both the batch
a reviewer is meant to launch and a script that writes to a private paper
checkout.

Three of them turn the server's experiment output into what the paper's Open
Science section points at. Each does one thing, and each reads the one before
it:

```bash
# 1. select — the runs the paper's numbers are computed from
python3 release/usenix/source_data_to_3_latest.py $EXP a_experiments_3/experiments \
    --verify-against <paper>/tmp/experiments

# 2. sanitize — remove what is ours to hide, replace what is not ours to give
python3 release/usenix/latest_3_to_remove_sensitive_open.py a_experiments_3/experiments \
    a_experiments_open/experiments --scrub <account>=anon --verify-against $LIB

# 3. slim — the copy that fits the reviewers' repository. No options: it
#    reads a_experiments_open/experiments and writes runs/
python3 release/usenix/open_to_thin.py
```

Nothing of the corpus is packed. run.json records the ground truth as an
absolute path on the machine that produced the run, and the console re-anchors
it on whatever corpus is configured — `paths.lib_root`, which defaults to a
checkout sitting beside this one, the same relationship the release layout has.
Step 3 prints which corpus units the playable runs were scored against so that
relationship is stated rather than assumed; with no corpus there the runs still
playback whole and the comparison pane is simply not offered.

The chain matters as much as the steps. Both published trees descend from the
sanitised one, so a redaction rule cannot be present in one and missing from the
other. It was, once: sanitising lived inside the slimming script, and the full
tree — written by a different script — went out carrying 2732 plaintext
`api_key` values, an account name in 3632 files and every home-directory path
the batch ran under.

## 1. `source_data_to_3_latest.py` — selection

A batch accumulates runs across the whole development of the framework while
the paper reports a window over each unit's most recent few, and which runs fall
in that window is decided by `tools/sync_data.py` in the paper repository. The
three batches are not treated alike: main and baseline fold the most recent
three end-to-end runs, while claims takes, per unit, the newest run that scored
each setup stage. Ordering is by start time, not by the number in a directory
name.

The rules are transcribed rather than imported — the paper repository is not a
dependency of this one — and `--verify-against` closes the gap that
transcription opens, comparing the selection run by run against the cache the
published numbers came from.

**The batch's own `config.yaml` does not travel.** It is the console's
working copy — whatever the operator last saved there — and one file at the top
of a batch reads as "this is what the batch ran under", which it is not.
In this tree it had drifted to `prompt_lang: zh` and a 180 s ProVerif budget,
while `_batch` shows the batch was launched
`--config .../benchmark/baseline/config.yaml` — a different file entirely, and
one that says `en` and 300 s, which is what all 454 runs that recorded a
configuration hold and what `experiments/batches.py` pins. So the file at the
top of the batch is wrong on both counts, and it is the only place in the
whole tree either wrong value appears.

What travels is each run's own `config.yaml`, written as the run started, with
the configuration that run actually used and its credentials already masked —
which is also why no plaintext key enters the artefact at any stage now. A run
that recorded none keeps none: for baseline that is 114 of 162, because the
one-shot runner did not write `config.yaml` (or `run.log`) until part-way
through the batch. The gap is the truth about those runs, and the count is
printed on every run of the script.

## 2. `latest_3_to_remove_sensitive_open.py` — privacy, copyright and language

Three obligations, and the first two are easy to confuse. *Privacy* is ours:
credentials, the account name, the machine's paths, links into the operator's
account at a model provider. *Copyright* is not: three publishers — ISO/IEC, 3GPP and the FIDO
Alliance — forbid redistributing the specifications some runs quoted, while
IETF documents, Signal's public-domain PQXDH and the corpus's own prose are
free to pass on.

Specification text is **replaced, never deleted**. The console links to a prompt
from every `prompt_filed` event, so a deleted prompt is a dead link in the
middle of a playback; the stand-in is padded to about the length it replaces,
because the console streams a reply over the time the original call took and a
ninety-second round that became one sentence plays as a flash and then a stall.

The document reaches a run by more routes than are obvious, and each one was
found by the check rather than by reasoning: inlined in the prompt, fetched on
demand into a `tool_result`, quoted a clause at a time in the model's own reply,
and echoed into batch logs that belong to no run at all. So the last word is the
text, not the file's place in the tree.

**A structured file is never replaced whole.** A ledger, a verdict, an
extracted model — something reads these back, so a prose stand-in does not
redact them, it destroys them. One `node_progress` line quoting one clause
turned a 411-line `events.jsonl` into a paragraph, and that run stopped being
replayable; eight went out that way before the check below existed. Quoted
sentences leave a `.json` or `.jsonl` where they stand instead, and the file
still loads. The exit check is absolute rather than comparative: every
structured file in the written tree must parse, not merely parse no worse than
it did.

*Language* is the third and is neither of the others. The corpus was partly
written in Chinese while this batch ran and has since been translated, so a
run that copied corpus prose still carries text the corpus no longer holds: nine
sentences across sixty-two files — eight principal descriptions belonging to
four ISO units, and one sub-protocol scope note belonging to TLS 1.3 draft-18
zero-RTT. They are replaced by the corpus's own current English.

The English is **read from the corpus, never transcribed into the script**. The
pairing is the two files' shared skeleton: a supplied `principals.json` is the
corpus's own file but for its prose, so removing every `description` from both
and comparing what is left says whether this artefact is a copy. It also says
when it is not — a run's own extraction has a different skeleton and is passed
over, because refreshing a model's output from the corpus would not be a
translation. The scope note is anchored on the generated sentence the pipeline
puts in front of it, and is replaced only where the note that is there is
Chinese; an English one is left as the run received it. `--verify-against` is
what supplies all of this, so it is no longer optional in practice.

The exit check is a flat one: no Han character may survive anywhere in the
written tree. It is what catches a sentence that reached a run by a route the
pairing does not cover, which is the only way this rule can fail quietly.

It also writes `MANIFEST.txt`, beside `experiments/` rather than inside it —
`open_to_thin.py` walks that directory and reads everything in it as a run's. The
deposit is one archive of fifty thousand files, because the repository it goes
to caps a record at a hundred, and an archive answers no question until it has
been unpacked; the manifest is what a reviewer can read without unpacking it.
It is generated rather than written by hand because a transcribed count is
wrong the next time the selection changes and nothing says so.

It is tables and nothing else — counts, batches, file types, and the protocol
names, which are what a reviewer holding only the archive cannot otherwise see.

One of those tables reconciles `_batch/` against the tree, which reads as a
defect until the numbers are beside each other. A state file records the *last
attempt* at a protocol; where that attempt failed, the run published is the last
one that completed. For the claims batch that is every protocol — 92 of 104
last attempts exited non-zero and 12 were still running when the batch
stopped, so not one state file names a run that is here. Neither half is wrong:
the tree publishes the run that scored, `_batch` records that the next attempt
did not. `open_to_thin.py` drops `_batch/` rather than explain it; the full tree
keeps both and puts the two counts in one row.

Both of its counts come off `run.json` rather than off the shape of the tree.
Each batch holds one directory that is not a protocol — `_batch`, the
scheduler's record of how the batch was launched — so counting directories
published 98, 102 and 102 protocols against the 97, 101 and 101 the batches
hold. Its walk is not an extra one: it replaces the walk that only totalled the
size, and reports that total in bytes, which is 519 MB where `du` says 640 MB.

## 3. `open_to_thin.py` — slimming

Reads the sanitised tree and does no redaction of its own. Two kinds of content:
the protocols in `PLAYABLE` keep everything a playback reads, for their
most successful main-batch run; everything else keeps only what the paper's
tables are computed from (`PAPER_DATA_NAMES`) and a ledger filtered to the
events that recompute them.

`config.yaml` is in that set even though neither consumer opens it. With no
batch-level configuration it is the only record of what a run was set up to
do, and half of what a reader needs to judge a number is the budget it was
produced under — this batch's split ProVerif timeout is visible here and
nowhere else in a slim run. It costs 0.7 MB across the 454 runs that
recorded one.

Nothing is gzipped — `events.jsonl` is the ledger the console plays back, and a
compressed one cannot be opened at all.

**It takes no options.** What it reads (`SOURCE`), what it writes (`SLIM`) and
which protocols keep their playback material (`PLAYABLE`) are constants in the
script. There is one artefact and one way to build it; a flag that could have
produced a different one leaves "which settings made the published tree?"
permanently open, and that is the one question an artefact must not leave to
memory. Changing what it produces is an edit to those constants, which a commit
records and a flag does not.

`api/playback.py::reference_root` resolves a recorded `ground_truth` by its tail
after the corpus name, which is why that name must survive step 2's scrubbing —
`build_scrubber` refuses any `--scrub` that would remove it. The paper's own
`sync_data.py` matches on the same string for the same reason.

## What is enforced rather than described

Each of these fails silently if left to care:

* a `--scrub` pair may not erase the corpus name from a path. `run.json`'s
  ground truth is how `tools/sync_data.py` identifies which unit a run analysed,
  and a run it cannot identify is dropped from the paper's tables without a word;
* redaction may not damage structure. A JSON file that parsed before
  substitution must parse after it — a credential rule once matched
  `const lock_token: bitstring.` inside a ProVerif model and broke one
  transcript out of eighteen thousand;
* no sentence of a restricted specification may survive anywhere in the
  sanitised tree, checked against the corpus itself. The first version of this
  check looked for each unit's document at the unit's own level, found nothing
  for all 86 restricted units, and passed against an empty set for
  twenty-four minutes;
* every run that carries playback material is checked against its own ledger: as
  many replies in a session's transcript as the ledger recorded rounds.

Checks run on the text the writer already holds, not on a second sweep of the
finished tree: the tree is 640 MB and reading it was the whole cost.

`$EXP` is the output tree on the server, holding `main/`, `claims/` and
`baseline/` — the runs, not the suite definitions that produced them, which
are in `experiments/`. The identifying strings the redaction replaces
come off the command line rather than out of the file: who ran it on which
machine is local configuration, and writing it down here would commit it.

## 4. `anonymous_release.py` — migration

The last step and the only one that writes outside this repository: it copies a
slice of the repository plus the corpus into the anonymous review repository,
rewrites what would identify the authors, and refuses to touch the destination
if the gate finds anything left. `runs/` — step 3's output — is one of the
top-level entries it copies, which is where these two halves meet.

Its rules are the reason it lives here rather than beside the repository it
writes: every one of them is a fact about Orrery's own semantics, and the copy
that lived in the neighbouring repository drifted four times. The policy is
`anonymous.toml` (this venue) plus `identity.toml` (the names to scrub, which
`open_to_thin.py` reads too); what each rule is for is written where the rule
is. Start with the script's own docstring.

```bash
python3 release/usenix/anonymous_release.py           # dry run
python3 release/usenix/anonymous_release.py --apply
```
