# Why the prompt rules are what they are

**This file states no rules.** The rules are in `../SKILL.md`; everything here is the
reasoning behind them, written as description rather than instruction. A sentence in this
file that sounds like a rule is a restatement — the rule itself, and its current wording,
is in SKILL.md.

Worth reading when a rule needs its justification, when deviating from one, or when
deciding whether a rule still applies. The reason is the part that transfers: where a
reason does not apply to the prompt in front of you, that rule is not guidance for that
prompt, and the better version wins with the divergence noted.

Two things that used to live here have moved to where they are consumed: the
per-model-generation facts are in `orrery/infra/llm/README.md` §1.8 (they are adaptation
layer, and half of them were already there), and the open measurement questions are in
`TODO.md` under P3.

Snapshot: the argument below was assembled 2026-08-13 from the three vendors' documentation
of that date. The semantic-layer reasoning has been stable across model generations; any
statement about a specific model's behaviour expires quickly. Sources are in
`research.md`.

---

## 1. Why one prompt set serves every vendor

Prompt content splits into three layers with completely different portability:

- **Semantic** —— what to do, criteria, reasons, examples, output shape.
  **Ports fully.** All three vendors wrote the same guidance independently.
- **Structural** —— block tags, section order, where long material sits.
  **Ports**, though tag syntax preferences differ.
- **Adaptation** —— effort / thinking / verbosity, temperature, prefill,
  per-model patches. **Does not port at all**; changes every minor release.

So the `.md` body carries semantic and structural content and one copy serves all
vendors; anything that exists "because we are on vendor X" sinks into `infra/llm/`.
Switching models then costs a parameter profile, a few lines of model patch, and one
baseline per vendor — not a rewritten prompt set.

The apparent counter-evidence — public studies showing over 30% drops when a prompt moves
between models — is about prompts *tuned* for one model. That transfers overfitting. A
prompt following the shared consensus transfers principles. The two must be discussed
separately.

Whether one prompt set really does serve all three is answered by measuring each vendor
separately. That is a project-level activity, not part of writing a prompt.

## 2. Why a contradiction is the most expensive defect

One thing stated two inconsistent ways costs more than any other prompt error. Models
spend extra reasoning tokens reconciling the conflict, and current models follow text
literally, so whichever statement sits downstream wins — unpredictably.

OpenAI's Prompt Optimizer exists to fix three failure modes, and two of them are this:
instructions that contradict each other, and output-format specs that are missing or
vague. (The third is few-shot examples disagreeing with the instructions.)

The place this project produces conflicts is a field enumeration in `<rules>` versus a
schema template in `<output_format>`. Vocabularies shared across prompts work the same
way: the type whitelist is the live case, stated by `init_knowledge` and `flow` and
defined in the pipeline nodes' own docstrings.

## 3. Why some steps stay and others go

All three vendors converged in 2026 on "give the goal and the criteria, not the
decomposition". OpenAI published internal numbers: more concise system prompts raised
eval scores by roughly 10–15% while cutting total tokens 41–66%, with one core technique
— state each instruction exactly once. Anthropic tells migrators that instruction sets
built for older models are often too prescriptive and should be deleted rather than
rewritten. Google says verbose prompt engineering built for older models gets
over-analyzed by newer ones.

The same source gives the corollary: reasoning models do not need to be told to think
step by step, and prescribing a decomposition (least-to-most and friends) constrains one
the model would have done better.

But this is not unconditional. Low-resource DSLs, strict output contracts and hard domain
constraints are where scaffolding still pays (§9). That is why the skill splits steps
into three kinds rather than applying one verdict: an output contract is not teaching,
and DSL scaffolding has measurements behind it.

## 4. Why examples are 0–3 here, not the official 3–5

Official guidance says 3–5. Public measurements put the peak for code tasks between 5 and
25 with a decline above that, and a neural-architecture generation task found n=3 optimal
with failure rates reaching 99.8% at n=6. So the optimum is task-dependent and must be
measured.

This project defaults lower deliberately: an example here is a protocol fragment, and more
of them either repeat each other, adding tokens and no information, or get copied as a
template onto the real protocol.

## 5. Why order is stable-first, volatile-last

Two independent forces point the same way.

**Prefix cache.** The key is compared byte by byte from offset zero and breaks at the
first difference, so per-call text placed early invalidates everything after it. The
extraction stage runs at roughly a 92% hit rate because the corpus block is
byte-identical across all four nodes.

**Attention.** Long material belongs at the top and the ask at the generation point.
Anthropic measured about a 30% improvement from putting the question last in complex
multi-document settings; Google recommends a bridging sentence to anchor the model to the
supplied material. OpenAI's advice to put context late inside a developer message is not
a contradiction — that is single-message organisation, where "context" means supplementary
material rather than a large corpus.

Note what this does and does not rule out. The corpus is protocol-specific and still
belongs at the top, because all four extraction nodes see the same bytes and so does every
later run on the same protocol. What costs the cached prefix is a run id, a timestamp, a
scenario name, or this call's artifacts sitting in a system block.

## 6. Why quotes come before judgement

Three benefits: the model has to attach its answer to specific text; the engineering layer
can parse the quotes and store them for audit; where the document contradicts itself the
model has to commit to which sentence it followed.

The ordering is stated in the prompt because nothing else guarantees it. API structured
outputs are unused here — schemas are validated locally — so generation order comes from
the prompt or from nowhere. It is stated once, in `<task>`, and deliberately left out of
`<success_criteria>`: an ordering written twice can drift into two orderings.

Quotes are incompatible with strict JSON mode, which truncates the block. That is the
narrow reason; the broader one is *Let Me Speak Freely?* (EMNLP 2024 Industry): the
stricter the format constraint, the more reasoning tasks degrade. Classification tasks go
the other way. Hence the split — strict schemas for pure extraction, free text plus local
parsing where semantic judgement is involved, and managing the order by hand as the price.

## 7. Why length is a trigger, not a budget

Context is used non-uniformly by every current model, and reliability falls as input grows
(*Lost in the Middle*, TACL 2024; Chroma's *Context Rot*, 2025, across 18 models including
GPT-4.1, Claude 4 and Gemini 2.5). A million-token window does not mean reliable reasoning
over a million tokens.

Neither result gives a number worth encoding as a limit, which is why "shorter is better"
here is a review trigger rather than a budget.

## 8. Why positive form, and why a prohibition needs three parts

Google's whitepaper has a section titled "Instructions over Constraints"; Anthropic says
to state what to do rather than what not to do; OpenAI asks for criteria instead of
ALWAYS / NEVER, reserving absolute wording for real invariants.

Two mechanisms. Negation is harder for language models — there is a systematic affirmation
bias with benchmarks built for it (*This is not a Dataset*) and parallel findings in
vision-language models. And a prohibition fences off one region while leaving the rest
undefined; a positive statement names the landing point.

The reason attached to a prohibition is not decoration. Anthropic states that models
generalise from explanations, which makes the "why" an active payload.

There is an informative counter-case: public reports find negative phrasing ("do not miss
X") improves defect detection in code review. So a prohibition's value is in *suppressing
something the model is about to do*, not in *defining what to do*. The two uses do not
conflict.

Stacked ALL-CAPS is the separate failure: `CRITICAL: You MUST` over-triggers on current
models, and the vendor fix is to return the wording to normal.

## 9. Why every qualifier gets classified

This is the most expensive new risk, and most public guides have not caught up.

Current models follow text far more literally, so the dominant risk moved from ALL-CAPS
over-triggering to **a mild qualifier acting as a hard gate**. Anthropic's own example
matches this project's shape: a code-review prompt saying "report only high-severity
issues" is obeyed to the letter — the model still investigates just as deeply, it just
stops reporting what falls below the stated bar. Recall drops, and that is compliance, not
degradation. The official fix is to split discovery from filtering and tell the model that
its job in the discovery phase is coverage.

The live case here: `init_knowledge`'s `When in doubt, be conservative` carries
`The one exception is item 0 of the consistency self-check` for exactly this reason.
Silent under-extraction is the symptom to watch for.

## 10. Why every prompt is self-contained — the NSPK incident

A sentence pointing at another prompt is a hidden dependency: it assumes both prompts act
on the same text in sequence, and it breaks silently the moment the call structure
changes.

> `injectors/authentication.md` once used "the criterion is the same as for secrecy" in
> place of the full honest-peer criterion. Under serial injection the secrecy step had
> already inserted the guard, so it never showed. Once the two goal classes were injected
> independently from `scenario.pv`, the referenced content was no longer visible, the
> guard disappeared, and NSPK's `auth_a_to_b` returned a false `false` twice in a row.

`test_every_prompt_is_self_contained` catches jinja `include` and nothing else. The only
defence against a semantic reference is not writing one.

The same logic covers a prompt promising something the framework does not do ("changes
outside this scope are rejected"): it teaches the model a rule nothing enforces.

## 11. Why ProVerif gets syntax scaffolding

ProVerif is a low-resource DSL — little training data, unusual syntax — and this is the
real exception to §3.

- *Enhancing Code Generation for Low-Resource Languages: No Silver Bullet* (arXiv
  2501.19085, 6 models × R/Racket): in-context learning "always has a positive effect, of
  varying magnitude" on mid-to-large models.
- A survey of low-resource and domain-specific code generation (arXiv 2410.03981) finds
  grammar prompting — putting syntax rules and skeletons into the prompt — measurably
  narrows the gap without retraining.

So removing a scaffolding block is worth measuring rather than reasoning about, and the
direction of the prior is "keep".

Two blocks in `flow/prompts/main.sys.md` sit on the line between ProVerif syntax and
ordinary programming knowledge, and are the standing candidates for an ablation, one block
at a time so the effect is attributable:

- the five-step rhythm of a receive state (receive → destructure → check → construct →
  send);
- the four-way split of where a value comes from (already in scope / round-tripped / first
  introduced with `new` / derived with `let`).

Roughly fifteen lines together.

## 12. Why diagnostics name the specific object

*How Many Tries Does It Take? Iterative Self-Repair in LLM Code Generation* (arXiv
2604.10508, 7 models) measured repair rate against feedback specificity:

- Names a specific undefined name —— ~77% repair rate.
- Plain syntax error —— ~66%.
- Assertion-style (result is wrong, location unknown) —— ~45%.

A finding that says "typecheck failed" and nothing else puts the model in the bottom band.
The same paper found self-repair beats independent resampling on both cost and quality
(93.3% at 112K tokens vs 90.9% at 231K), and that 8B-class models repair effectively from
specific feedback — the old "weak models cannot self-repair" result does not hold.

Repair rounds show sharply diminishing returns: two rounds capture 76–95% of the
achievable gain, with the first round largest and rounds 3–4 near zero. That is where
`max_repairs` comes from.

Anthropic's *Writing effective tools for agents* is the source for the tool-description
rules: descriptions enter the model's context and steer calling behaviour, so they are a
formal part of the prompt; parameter names carry semantics; and error text that gives a
concrete executable next step outperforms a raw code or traceback.

## 13. Why model quirks stay out of the prompt body

A prompt body is one copy shared across vendors (§1), so a fact that holds only on model X
would make that copy vendor-specific — and those facts expire every minor release, while
the prompt does not. The list of them lives in `orrery/infra/llm/README.md` §1.8, next to
the code that acts on it and next to the vendor-protocol notes half of it duplicated.

One entry there is easy to misapply, so it is worth naming: Claude Opus 5 self-verifies,
and the vendor asks for "verify at the end" instructions to be removed. That is about
closing procedures, not criteria — a block stating what is true of a finished product
survives; a numbered "now go back and check these five items" script is what goes.

## 14. Weak models and node-to-model fit

The goal is a method solid enough that a general-purpose model can carry it. Public
engineering reports agree that smaller models want more explicit, more structured
instructions and tighter schemas, and that frontier prompts often assume capabilities a
small model lacks. But a prompt tuned for one model is overfitting (§1), so the path is
structural explicitness plus targeted examples against observed failures — all of which is
harmless or helpful on strong models.

Node-to-model fit, which decides where a smaller model could be tried: structured
extraction (entities, init_knowledge, skeleton) is generally within reach; the base-model
node (long-context synthesis plus DSL generation) and the scenario stage's semantic
judgement are not. That is a config decision and stays out of the prompts.

---

## Sources

`research.md` carries the full argument and every link: the three-layer portability model,
the outcome-first turn, the low-resource DSL evidence behind §11, the repair-rate numbers
behind §12, and the weak-model guidance behind §14.

The three open measurement questions this argument leaves unresolved — the two scaffolding
blocks in §11, `init_knowledge`'s four-segment `description` field, and whether one prompt
set really serves all three vendors — are tracked in `TODO.md` under P3.
