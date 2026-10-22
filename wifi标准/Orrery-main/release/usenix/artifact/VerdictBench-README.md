# VerdictBench

VerdictBench is Orrery's benchmark: the protocol corpus it is evaluated against,
and the ground truth every run is scored on.

## Layout

The top level is flat — five categories, 101 protocols across 26 families:

| | |
|---|---|
| `academic/` | 8 — the classic academic protocols: NSPK, NSSK, Denning-Sacco, Neuman-Stubblebine, Otway-Rees, Kao-Chow, Yahalom, wide-mouth-frog |
| `rfc/` | 6 — IETF standards: EDHOC (draft-08, draft-12), IKEv2, OAuth 2.0 (draft22), TLS 1.3 (draft18, draft20) |
| `ISO/` | 84 — ISO/IEC 9798 (entity authentication) and 11770 (key management), one directory per part |
| `3gpp/` | 1 — 5G-AKA, from TS 33.501 |
| `informal/` | 2 — FIDO UAF and Signal PQXDH |

Under a category is one directory per protocol, and it holds the question and
its answer:

| | |
|---|---|
| `source/main/` | the document that was analysed |
| `source/refs/` | the documents it cites, as the run read them |
| `annotations/` | section tags, references, subprotocol map |
| `claims/` | the question: which goal is claimed under which assumptions (`claims.json`, `assumptions.json`, `properties.json`) |
| `flow/` | the reference model: `flow.pv`, `principals.json` |
| `formal/proverif/` | the reference ProVerif models |
| `results/` | the ground truth: `results.json` per claim, `cases_results.json` per scenario |

A standard covering several mechanisms splits them into
`subprotocols/<name>/`, each with its own `claims/`, `flow/`, `formal/` and
`results/`; the document and its annotations stay above them, shared.

## What is not here

**The specifications of ISO/IEC, 3GPP and FIDO.** All three forbid
redistribution: the ISO copies are watermarked *"Committee member copy: Do not
reproduce"*, TS 33.501's copyright page extends its restriction "to reproduction
in all media", and FIDO grants nothing. So under `ISO/*/source/`,
`3gpp/*/source/` and `informal/FIDO/*/source/` only each directory's own
`README.md` remains, recording the notice the decision rests on; where a quoted
passage sits inside a file that has to ship, the passage is replaced by
`[withheld: third-party specification text]`.

Everything *derived* from those documents does ship — annotations, claims,
models, verdicts — so their results stay checkable, and their recorded runs
under `runs/` show the pipeline working on them. The 15 protocols whose sources
are freely redistributable — the academic ones, the IETF drafts and RFCs, and
Signal's public-domain PQXDH — are where end-to-end reproduction is
demonstrated.

**PDFs.** Where a document exists as both a PDF and a converted `.md` or `.txt`,
only the text form ships; that is the form the pipeline parses.
