# infra/llm — interface layer and relay gateways

What this layer has to deal with, in three classes, plus everything measured
about the third-party relay endpoints this project has actually used.

Read the matching class before touching any backend under `remote/`, before
wiring up a relay gateway, and before investigating "I passed the parameter and
it had no effect".

**Class 1 · Interface adaptation** — translating the unified `invoke` intent into
each vendor's mechanism. Varies with the protocol. Absorbed by each adapter under
`remote/` separately — four of them, see 1.9.

**Class 2 · Gateway deviation** — measured behaviour where a relay gateway
disagrees with the official protocol. Varies with the gateway. Lives in this
document, plus the user's own `extra_headers` — never a backend file, and never
applied for the user.

**Class 3 · Lost guarantees** — deviations that cannot be fixed on the request
side, only verified on the result side. Varies with nothing. Lives in
backend-independent validation (`chat/validation.py`), written once, always on.

**Nothing in class 2 is applied for you.** The client recognises no endpoint and
adds no header, whatever the url. Where this document says an endpoint needs a
header, that header goes in **your config**, under `llm.extra_headers`, beside
the url it belongs to. See "Where this knowledge lives" at the end for why.

Endpoints covered:

- **`api.bltcy.ai`** (bltcy / 柏拉图) — rebuilds requests: control parameters
  dropped, thinking unsigned, `input_tokens` drifts. Usable, but only with two
  headers set by hand, and never for claude over the OpenAI path.
- **`api.zzz-api.top` · `api.zhizengzeng.com`** (zhizengzeng / 智增增) — a real
  passthrough: every control parameter reaches the upstream, thinking keeps its
  signature, the request body is not rewritten, no headers needed. Prompt caching
  hits about a third of the time.

---

# Class 1 · Interface adaptation

`ChatLLMBase.invoke` (`llm.py`) states an intent and never a mechanism name.
The intent vocabulary:

- `tools=[FunctionTool]` — offer callable tools.
- `response_format="json"` — output valid JSON (no schema constraint).
- `json_schema=<dict>` — output JSON matching that schema exactly (implies json).
- none of them — free text.

Each intent has one translation per backend. Item by item:

## 1.1 FunctionTool: sending definitions, returning calls, replaying history

**Sending definitions**:

- **Shape** — OpenAI wants
  `{"type":"function","function":{name,description,parameters,strict}}`;
  Anthropic wants `{name, description, input_schema}`, flat rather than nested.
- **Code** — for OpenAI, `FunctionTool.to_dict()` produces it directly; for
  Anthropic, `claude.py::_convert_tools` maps it by hand and **does not** go
  through `to_dict()`.

**Returning calls**: the unified dict shape is fixed by
`RemoteChatOpenAICompatible._extract_tool_calls` —
`{id, type, name, arguments (raw string), arguments_json (parsed)}`.
`claude.py::_extract_tool_calls` fills the same shape from a `tool_use` block.
`state_tools` accepts only this shape, so switching backends changes nothing.

**Replaying history** (a multi-round tool loop sends assistant/tool messages back):

- **The assistant's tool calls** — OpenAI uses a `tool_calls` field on the
  message; Anthropic uses a `tool_use` block inside content.
- **Tool results** — OpenAI uses a separate `role:"tool"` message (with
  `tool_call_id`); Anthropic uses a `tool_result` block **merged into the
  adjacent user message**, and several in a row must go into the same one.
- **Empty assistant** — OpenAI allows `content:""`; Anthropic rejects empty
  content, so `claude.py` raises explicitly.

## 1.2 `response_format="json"`

- **Mechanism** — OpenAI has native JSON mode, `{"type":"json_object"}`,
  **deliberately not sent, see below**; Anthropic has **no such parameter**.
- **Implementation** — OpenAI relies on a prompt convention plus
  `ensure_valid_json` after the reply; for Anthropic the shape is required by the
  caller's `<output_format>` section, and `ensure_valid_json` runs before
  returning (`chat/validation.py` — clean up, then parse; a failure raises).
- **Strength** — both are a prompt convention plus after-the-fact verification.

**Measured finding (2026-08-13): `json_object` mode breaks tool rounds — never
send it in an agent loop.** The agent loop passes tools on every round, and JSON
mode constrains **every** assistant turn, including the evidence-gathering turns
that must emit `tool_calls`. On gpt-5.6-terra (bltcy), replaying a real
extract_skeleton request A/B: without `response_format` 3/3 rounds returned
standard `tool_calls`; with `{"type":"json_object"}` 2/3 rounds serialized the
intended tool calls into content instead (`{"number":"4"}{"pattern":"->",...}`),
which then fails schema validation as a phantom "submission". A short prompt does
not trigger it — only realistic long-context requests do, which is why simple
probes miss it. Gemini is honest about the same conflict: it rejects
tools+`response_mime_type` outright with a 400. All three backends therefore
enforce both JSON intents locally only (class 3), and `_get_response_format`
returns Omit for every legal intent.

## 1.3 `json_schema`: unifiable, and both vendors allow it alongside tools

Research conclusion (2026-08, from Anthropic's official documentation): **both
vendors have native structured outputs, a unified interface holds, and the
worry that "Claude does not allow tools + json schema" is unfounded.**

- **Mechanism** — OpenAI:
  `response_format: {"type":"json_schema", "json_schema":{name, strict:true, schema}}`.
  Anthropic: `output_config: {"format": {"type":"json_schema", "schema": ...}}`.
- **beta header** — not needed on either. On Anthropic it is GA, and the old
  top-level `output_format` parameter is deprecated.
- **Model requirement** — OpenAI: gpt-4o-2024-08-06+ / gpt-5.x. Anthropic:
  Claude 4.5+ (Opus 4.5/4.8/5, Sonnet 5, Haiku 4.5, Fable 5, ...).
- **Alongside tools** — yes on both. On OpenAI the schema constrains the final
  reply and tools are called as usual; on Anthropic the official docs show
  `output_config.format` together with strict tools.
- **SDK convenience layer** — OpenAI:
  `client.beta.chat.completions.parse`. Anthropic:
  `client.messages.parse(output_format=<PydanticModel>)`.
- **Effect** — OpenAI guarantees the first (final) message is valid JSON matching
  the schema; Anthropic guarantees the first text block is.

**Historical correction (already landed)**: claude.py once planned to force a
single schema tool via `tool_choice`. That was the pre-structured-outputs route
— it conflicts with the caller's own `tools` (forcing one tool means no other
can be called), and on the bltcy gateway `tool_choice` is silently dropped, so
it could not work at all. Today `json_schema` is not sent to the API at all:
`claude.py` (like the other two adapters) checks the reply locally with
`validation.py::ensure_schema_valid`, and `_invoke_once` sends `output_config`
only for `effort`.

**Schema dialects: both vendors support only a subset of JSON Schema; write to
the intersection**:

- Common requirement: objects must set `additionalProperties: false`, and every
  field must be listed in `required`;
- Anthropic explicitly does not support: recursive schemas, numeric constraints
  (`minimum`/`maximum`), length constraints (`minLength`/`maxLength`). The
  official SDK strips unsupported keywords and re-checks client-side;
- OpenAI supports `$ref` recursion; numeric and length constraints have likewise
  long been unsupported.
- The unified layer's position: write schemas to the intersection, and re-verify
  on the result side whether connected directly or not (class 3) — that pass
  catches whatever was stripped.

**Combinations and failure cases**:

- On the Anthropic side `output_config.format` (which governs output) and strict
  tools (which govern tool inputs, see 1.4) are two independent switches;
  neither implies the other;
- Incompatibilities: Anthropic's citations plus `output_config.format` gives a
  400; neither vendor's structured outputs work with assistant prefill
  (Anthropic 4.6+ forbids prefill anyway);
- With `stop_reason: "refusal"` the output need not match the schema, and a
  `max_tokens` truncation leaves it incomplete — so class 3's client-side
  validation is **always necessary**, native mechanism or not.
- A new schema costs a one-time compilation delay; the same schema is cached
  for 24h.

**SDK prerequisite**: `output_config` needs a recent anthropic SDK (upgraded
locally to 0.121.0, where the parameter is typed).

## 1.4 strict tools (a schema guarantee on tool inputs)

- **Where the switch is** — OpenAI: `function.strict: true`, nested. Anthropic:
  `strict: true` at the **top level** of the tool definition, beside
  name/input_schema.
- **Schema requirement** — both want `additionalProperties:false` plus every
  field `required`.

As it stands: whether `FunctionTool.to_dict()` (the OpenAI side) carries strict
is up to its implementation; `claude.py::_convert_tools` does not carry it.
That is not a bug — adding it is a small change aligning both ends. Through a
gateway the request body gets rewritten (see class 2), so strict is unreliable
on a relay: a tool handler must validate its own inputs (class 3).

## 1.5 Message and session shape differences (absorbed; listed for reference)

- **system**: OpenAI takes a message; Anthropic takes a top-level parameter
  (several SYSTEM messages are concatenated into one).
- **temperature**: OpenAI takes a `float`; Anthropic has a parameter of the same
  name, and `None` becomes `NOT_GIVEN`. Note Opus 4.7+ removed the sampling
  parameters (passing one gives a 400), so connecting directly to a new model
  needs the parameter trimmed per model — not handled.
- **usage**: Anthropic's `input_tokens` excludes the cache read and write parts,
  and `_build_usage` adds them back to get the total input; OpenAI's
  `prompt_tokens` is already the total. `ChatTokenUsage` means "total input".
- **prompt caching**: Anthropic uses `cache_control` breakpoints (one on system
  plus one rolling); OpenAI caches prefixes automatically with no parameter. The
  intent is unified as the `cache_system` kwarg, which only `claude.py` knows
  (it pops it before the call); the other adapters pass `**kwargs` straight to
  their SDK, so a caller must not send it to them.
- **stop/finish reason**: different vocabularies (`refusal`/`max_tokens` vs
  `content_filter`/`length`), absorbed by each `_check_*_reason`; only a uniform
  RuntimeError or warning goes upward.

## 1.6 Not yet unified (on the record, not bugs)

- **images**: no adapter builds an image block; every message is text (plus
  the provider's own thinking carrier). Not wired up on any backend.
- **thinking round-trip**: done (2026-08-14). `ChatMessage`/`ChatResponse`
  carry `thinking_blocks`, an opaque provider-native payload written and read
  only by the producing adapter; runner and transcript copy it through.
  claude.py sends `thinking={"type":"adaptive","display":"summarized"}` on the
  families that take the adaptive shape and replays the blocks verbatim under
  a signature gate (all `thinking` blocks signed → replay; any unsigned →
  drop whole). The gate reads a fact of the response itself, so official
  (signed, replay required) and relays (unsigned, replay meaningless) both
  come out right with no gateway vocabulary in code.
- **tool_choice**: added 2026-08 (`model.py::ToolChoice`, four levels
  AUTO/REQUIRED/TOOL/NONE plus a no-parallel flag; each backend has its own
  `_convert_tool_choice`). Corner cases absorbed while implementing it, so as
  not to hit them again:
  - When OpenAI is forced to a specific tool, `finish_reason` comes back as
    `"stop"` rather than `"tool_calls"` — so "was a tool called" is always
    decided from `tool_calls` itself;
  - The no-parallel flag sits in different places: OpenAI has top-level
    `parallel_tool_calls=False`, Anthropic has `disable_parallel_tool_use`
    inside the tool_choice object;
  - Anthropic's forcing levels (any/tool) are mutually exclusive with extended
    thinking on some models and platforms (Bedrock + Sonnet 5 requires thinking
    disabled); this layer does not send thinking, so it is unaffected for now;
  - Changing tool_choice on Anthropic invalidates the messages-level cache (the
    tools and system levels survive), so the plain default level is not sent at
    all, keeping the request byte-stable;
  - It is silently dropped on the bltcy gateway (measured on the Anthropic path;
    the OpenAI path was not tested) — the answer is two lines of defence:
    `validate_against` checks tool names locally before sending (the gateway
    does not 400 on an invalid name, so local is the only check), and
    `verify_response` re-checks afterwards whether the model obeyed (an explicit
    error if not; see class 3).
- **The base-class annotation** (`client.py::ChatClient.invoke`) is
  `tools: list[FunctionTool] | None`; an earlier `list[str]` was fixed.
- **`**kwargs` passed straight to the live call**: a caller can bypass the
  intent vocabulary and push mechanism parameters through (`seed` and
  `cache_system` already do). It should at least error on the intersection with
  a gateway profile's dropped set (see class 3).

## 1.7 Gemini adaptation notes (after gemini.py was rewritten, 2026-08)

The SDK is the new `google-genai` (the old `google-generativeai` is deprecated;
do not install it). Translating the unified intents:

- `tools` →
  `Tool(function_declarations=[FunctionDeclaration(parameters_json_schema=...)])`
  — takes native JSON Schema, no stripping needed.
- `tool_choice` → `ToolConfig.function_calling_config`: REQUIRED becomes `ANY`,
  TOOL becomes `ANY` plus a single-element allowlist, NONE becomes `NONE`,
  AUTO is not sent.
- `response_format="json"` → `response_mime_type="application/json"`.
- `json_schema` → the above plus `response_json_schema` (natively supported).
- url / extra_headers → `HttpOptions(base_url, headers)`; base_url strips `/v1`
  the same way claude does.

**Three hard differences from the other two** (the adapter absorbs them; callers
need to know the first two):

1. **tools and JSON output are mutually exclusive**: an official 400 ("Function
   calling with a response mime type ... is unsupported", relayed back by the
   bltcy gateway as measured). gemini.py therefore never asks the API for JSON
   (no `response_mime_type` / `response_json_schema`) and relies on the local
   check alone, the same way the other two adapters do since `json_schema`
   stopped being sent anywhere.
2. **No no-parallel switch**: `ToolChoice(disable_parallel=True)` raises
   `NotImplementedError` on gemini.
3. **function_call has no stable id**: the adapter synthesises the ids for the
   unified tool_calls; a TOOL replay is restored to a `function_response` via
   an id-to-name map (Gemini pairs by name).

Also: thinking is left to the model by default (pass `thinking_config` through
kwargs to turn it off, and note 2.5-pro does not allow budget=0); usage's
`thoughts_token_count` counts as output; finish_reason follows the official
vocabulary (STOP is normal, MAX_TOKENS warns, SAFETY/RECITATION/... all raise).

## 1.8 Per-model-generation facts (adaptation layer; expires every minor release)

These belong here rather than in any prompt: a prompt body is shared across
vendors, so anything true "because we are on model X" lives in this layer.
Snapshot taken 2026-08-13; verify before relying on a row.

- **Claude Sonnet 5 rejects non-default `temperature` / `top_p` / `top_k` with a
  400.** A blanket `temperature=0` errors out. Same family as the Opus 4.7+ note
  in 1.5.
- **Gemini 3.x asks for temperature / top_p / top_k to be removed from the
  generation config.** Same, and setting them causes repetition or degraded
  reasoning.
- **Prefill is unsupported on Claude 4.6+ and Gemini 3.7.** No longer an
  Anthropic-only caveat; 1.3 also notes it breaks structured outputs.
- **Claude 4.7+ rejects `budget_tokens`; use `effort`.** Thinking budget is
  controlled differently.
- **Gemini's `thinking_budget` became `thinking_level`**, default down from high
  to medium. Changes on migration; see also 1.7.
- **Claude Opus 5 self-verifies.** The vendor asks for "verify at the end"
  instructions to be dropped from prompts — a criteria block is fine, a closing
  checklist script is not.
- **Claude Opus 5 with thinking disabled can leak internal XML tags into visible
  output**, and "do not reason" instructions make it worse. This project extracts
  `<result>` blocks by regex, so thinking at low effort is safer than disabling
  it.
- **Claude Fable 5 has a `reasoning_extraction` refusal category.** Asking a
  model to restate its own internal reasoning can trigger it; quoting a source
  document does not.
- **Gemini 3.x and GPT-5.6 default to more concise output; Claude Opus 5 defaults
  longer**, and `effort` does not control visible length. Verbosity has to be
  stated explicitly, per vendor.

Migration discipline, on which all three vendors agree: establish a baseline
before touching any prompt; change the model id and parameters first and run the
existing evals; make one attributable change per round; keep one baseline per
vendor.

## 1.9 Four adapters, not three: the OpenAI backend split (2026-08-17)

"OpenAI compatible" used to mean one thing, because OpenAI's protocol *was* the
universal protocol. It no longer is, and the adapter layer now says so:

- `claude.py` — `RemoteChatClaude`, Anthropic `/v1/messages`, serves Anthropic.
- `gemini.py` — `RemoteChatGemini`, Google `generateContent`, serves Google.
- `openai.py` — `RemoteChatOpenAI`, OpenAI `/v1/responses`, serves OpenAI.
- `openai_compatible.py` — `RemoteChatOpenAICompatible`,
  `/v1/chat/completions`, serves everyone else.

**The naming is by audience, not by age.** Chat Completions is the older API and
the most widely spoken one; calling it "legacy" would imply a migration that is
never going to happen, since DeepSeek, GLM, Grok, Qwen, vLLM, Ollama and every
relay implement it and nothing else.

**Why it had to split.** Reasoning models broke the assumption that one protocol
serves everyone: a reasoning model's intermediate state must be replayed across
tool rounds, and that state is vendor-private. All three vendors invented their
own carrier within a year of each other —

- **Anthropic** — signed `thinking` blocks must go back; otherwise the request is
  rejected on the official endpoint.
- **Google** — `thought_signature` on the `functionCall` part must go back;
  otherwise 400 (measured, Gemini 3).
- **OpenAI** — `reasoning` items with `encrypted_content` must go back;
  otherwise the model reasons from scratch each round.

Chat Completions has nowhere to put any of them, which is why OpenAI started a
second API rather than extending the first, and why `remote-openai-compatible`
can never gain the capability by being improved. All three land in
`ChatResponse.thinking_blocks`, whose contract ("written and read by the same
adapter, copied through verbatim by everyone else") was designed for exactly
this and needed no change to absorb the third case.

**Config**: `remote-openai` was **deleted, not aliased**. It named one protocol
and now names two with different capabilities, so any silent choice would route
an existing config somewhere it was never pointed — a config saying
`backend: remote-openai, model: deepseek-chat` still parses and still runs.
The factory raises a `ValueError` naming both successors instead. Choose
`remote-openai-responses` for OpenAI models (required for gpt-5.5+ in an agent
loop) and `remote-openai-compatible` for everything else.

---

---

# Class 2 · Gateway deviations (measured)

A gateway speaks one of the three official wire formats (OpenAI, Anthropic,
Gemini) — there is no fourth protocol — so **this class never needs
"gateway-version translation code"**. Deviations take only two forms: something
extra the request must carry (a header, a URL shape), and parameters that are
sent in vain. The first is injected through the generic `extra_headers` config;
the second is handled by class 3. **The settled solution is at the end of this
section.**

## bltcy · api.bltcy.ai

Tested 2026-08-10 in two rounds: caching and dropped-parameter first pass
(`claude-opus-5` / `claude-sonnet-4-6`); a full parameter-passthrough probe plus
a claude-over-openai-path follow-up (`gpt-5.5` / `claude-sonnet-4-6`). From the
response headers, the gateway software is of the new-api family:

```
x-new-api-version: v1.0.0-rc.21
x-oneapi-request-id: ...
server: nginx/1.24.0 (Ubuntu)  via: 1.1 Caddy
```

### How to decide

To find out whether a parameter really reached the upstream, **do not look at
model behaviour** — a model cooperating of its own accord gives false positives.
Look instead at input the official API must reject: **send a value the official
API is certain to 400 on; if the gateway returns 200, the parameter never
reached the upstream.**

Example: `tool_choice: {"type": "tool", "name": "no_such_tool"}` names a tool
that is not in `tools`, which the official API must 400 on. Measured: normal
text came back, so it is being dropped.

The measurements also turned up a third outcome: **hanging**. Some invalid
values and parameter combinations a channel does not support neither 400 nor get
dropped, but hang the gateway for 120s+ (probably multi-channel retries). So
never send an invalid value in production — our translation layer only produces
valid shapes, which avoids this naturally.

### Both protocol paths work

```
/v1/chat/completions   OpenAI-compatible format, every model (gpt / claude / gemini / grok / deepseek)
/v1/messages           Anthropic native format, returns a standard message structure
```

The Anthropic native endpoint authenticates with `x-api-key`, same as official.

### base_url must have /v1 stripped

The url in config is for the OpenAI SDK and must carry `/v1` (the SDK appends
`/chat/completions`). The anthropic SDK appends `/v1/messages` itself, so a
base_url that also carries `/v1` requests `/v1/v1/messages` and gets a 404. The
two SDKs want different base_url shapes for the same relay. (Generalised in
`claude.py::_normalize_base_url`; harmless when connected directly.)

### Item one · the openai.py side (`/v1/chat/completions`, running gpt / deepseek / grok / gemini)

Measured on the GPT channel (gpt-5.5):

- **`tool_choice`** — an invalid tool name got **the upstream's official 400**
  ("Tool choice 'no_such_tool' not found"). **Passed through**; `verify_response`
  is only insurance.
- **`response_format: json_object`** — works: JSON comes out even with no "json"
  in the prompt (the official "must contain json" check did not fire).
  **Usable**; the missing request-side check says the upstream is not the official
  API either.
- **`response_format: json_schema`** — works, and the output matched the schema
  exactly; but an invalid schema (missing additionalProperties) did not 400.
  **Usable**; strict checking is doubtful, so local re-verification is necessary
  (class 3).
- **`temperature`** — =99 does not error (the official range is 0-2 and must 400).
  Swallowed or clamped; do not rely on it.
- **An invalid `response_format` type** — **hangs 120s+**, reproduced twice.
  Do not send invalid values; `_get_response_format` only produces valid ones,
  so this is safe by construction.

**What openai.py has to do for this gateway: nothing.** Every control parameter
works on the GPT channel; the existing `_raise_if_api_error` (which parses the
error body the gateway stuffs into a 200 response) is the whole of the historical
adaptation. The one outstanding item is class 3's result-side JSON validation —
which should be on for any channel and is not gateway-specific.

**One prohibition: do not run claude models over this path** (the old usage).
Measured with `claude-sonnet-4-6` over `/v1/chat/completions`: `json_schema` has
no effect (prose comes out), and `json_object` and `tool_choice` both hang
120s+. The truth behind the old note "response_format has no effect" is a
**channel difference** — passthrough behaviour differs by upstream channel, and
the GPT channel is good while the claude-compatible channel is bad. Always run
claude over the native path.

### Item two · the claude.py side (`/v1/messages`, running the claude family)

Measured with `claude-sonnet-4-6`:

- **`tool_choice`** — an invalid tool name and an invalid type both gave 200.
  **Dropped**; `ToolChoice.verify_response` is the only defence.
- **`output_config` (json_schema)** — an invalid format gave 200; a functional
  test produced prose. **Dropped**; `json_schema` is **unusable** on this
  gateway's claude path — `ensure_schema_valid` rejects it explicitly. For a
  schema, the only route is `response_format="json"` plus describing the schema
  in the prompt.
- **`thinking: {"type":"disabled"}`** — (first pass) thinking blocks still came
  back after explicitly disabling it. Dropped; cannot be turned off.
- **`temperature`** — =5 does not error (the official range is 0-1 and must 400).
  Not checked; may be swallowed or clamped.
- **`max_tokens`** — see the section below (re-measured 2026-08-12 with
  `claude-opus-5`, non-streaming). Large values fail often, but mixed in with
  channel outages, so no clean threshold could be established.
- **Unknown top-level parameters** — no error. The gateway strips unknown keys
  before forwarding.
- **Upstream identity** — in a functional test the model called itself "Kiro, an
  AI-driven development environment". The upstream is a reconstructed channel
  (probably an AWS Kiro channel), which corroborates the request-body rewriting,
  the fluctuating input_tokens, and thinking without a signature.
- **Baseline** — occasional 120s+ timeouts. The channel is unstable;
  `_TIMEOUT=300` stays.

`tools` itself passes through and works; only the control parameters are affected.

### Large `max_tokens`: fails often, but no threshold found

One round of measurements on 2026-08-12 (`claude-opus-5`, non-streaming, 75s
client timeout), in chronological order:

```
16384  OK 2.9s      32000  OK 2.9s       64000  timeout 75s   128000 timeout 75s
89600  NotFound 39s 48000  timeout 75s   40000  500 error 55s
16384  OK 3.0s      32000  400 error 51s 16384  500 error 26s
```

The first row looks like "the threshold is between 32000 and 64000", but the
last row refutes it: **the same `max_tokens=16384` succeeded and then 500'd**,
which means the channel itself is going down (same root cause as "thinking has
no signature" and "input_tokens fluctuates": the upstream is a multi-channel
reconstruction). So only one conclusion stands: **a large `max_tokens` fails
noticeably more often on this gateway, but the failures are mixed in with
channel outages and no clean threshold can be separated out.**

For comparison: the official endpoint returned `max_tokens=89600` normally at
the same moment, in 1.8s.

claude.py's value (70% of the cap, so 89600 for opus-5) follows the official
protocol and does not bend for this gateway — the settled position of this
section is that gateway quirks stay out of backend files. To produce large
outputs on this gateway, fix the channel first, or temporarily lower
`_MAX_TOKENS_RATIO`.

**What claude.py has to do for this gateway: nothing. What the user has to do:
set two request headers**, or prompt caching here stays at zero (the conditions
are detailed below). Copy them into config:

```yaml
llm:
  url: "https://api.bltcy.ai/v1"
  extra_headers:
    anthropic-beta: "prompt-caching-2024-07-31"   # missing -> the gateway rebuilds the request and loses cache_control
    user-agent: "curl/8.7.1"                      # the SDK's default UA is routed to a channel that does not pass parameters through
```

These two used to be added for you, by a preset table keyed on the url's
hostname. **They are not any more** (2026-08-17, see "Where this knowledge lives"
at the end of this document). The table was first demoted to a warning and then
deleted outright — `factory.py` no longer contains it, inspects no hostname and
adds no header. Nothing reaches the wire that the config did not ask for.

Every other deviation (tool_choice / output_config / thinking being dropped) is
caught or explicitly reported by class 3's always-on validation, and claude.py
itself contains no gateway-specific code.

### Item three · the gemini.py side (`/v1beta/models/...:generateContent`, Gemini native format)

Measured 2026-08-10 with `gemini-2.5-flash` (`/v1beta/models` lists 852 models):

- **`toolConfig`** (the tool_choice equivalent) — an invalid allowlist got
  **the upstream's official 400**. **Passed through.**
- **Forcing a tool call** (mode=ANY plus an allowlist) — functionCall came back
  normally. Works.
- **`responseJsonSchema`** — output matched the schema. Works.
- **tools plus JSON output together** — the official 400 was relayed back
  verbatim. The gateway passes the official restriction through faithfully
  (this is Gemini's own exclusion, see 1.7).
- **Channel stability** — `gemini-2.5-pro` timed out / 404'd for a while, flash
  was stable. Model availability varies with the channel; hit `/v1beta/models`
  before switching models.

**What gemini.py has to do for this gateway: nothing.** The native path passes
things through as well as a direct connection does (every error is the upstream's
own, relayed verbatim), and the preset table needs no gemini entry. Multi-round
tool replay, forced calls, and json_schema have all been verified end to end
through the production chain. Old configs that ran gemini over the
OpenAI-compatible path still work, but the native path carries more information
(complete usage, a full finish_reason vocabulary) and is worth migrating to.

### prompt caching: both conditions must hold

Miss either one and `cache_creation_input_tokens` and `cache_read_input_tokens`
stay at 0.

**(1) Send the `anthropic-beta` header.** Without it the gateway takes the
rebuild path and loses `cache_control`. It only checks that the header is
present and never validates the value: `x` works exactly as well as the official
`prompt-caching-2024-07-31`.

**(2) Override `user-agent`.** With the anthropic SDK's default UA
(`Anthropic/Python` plus a string of `x-stainless-*`) not even a cache write
happens; switch to `curl/8.7.1` and the same request starts writing immediately.
The gateway routes by client type, and the official-SDK route does not pass
`cache_control` through.

This one was found by printing the actual request body from an httpx event hook:
`cache_control` was plainly in the body the SDK sent (`['cache_control', 'text',
'type']`) and the `anthropic-beta` header was there too, yet usage was all
zeros; changing only the UA hit the cache.

**The payoff.** With both conditions met, the same request sent 8 times (a
system prompt of about 4700 tokens):

```
3 hits, 2 writes, 3 at full price
effective input cost 0.61x (1.00 = no caching)
```

At 1.25x for a write and 0.1x for a read, break-even is a 21.7% hit rate; the
measured rate was 37.5%, so it is worth turning on.

**Why the hit rate does not go higher.** For an identical request body,
`input_tokens` fluctuates between 3318 and 4671, and the full-price runs are
clearly on the low side. It looks like the gateway has several upstream channels
and only some of them pass `cache_control` through. Nothing we can control.

### Response-side differences

The thinking block **carries no `signature`**. An official thinking block always
does, and it is used to check the integrity of multi-round thinking. Its absence
means the gateway rebuilds the response rather than passing it through.

Consequence: the official requirement that "a multi-round tool loop must send
thinking back verbatim" cannot be satisfied here — and for the same reason has
no effect.

### The request body gets rewritten

Sending an identical request body twice gives different `input_tokens` (2493 and
2387 as measured). The gateway injects content of varying length in between.
The inference: **any mechanism that depends on the request content arriving
exactly cannot be trusted on this relay**, including cache prefix matching and
including strict mode (on both the OpenAI and Anthropic sides). The later
functional test where the model called itself Kiro corroborates this: the
upstream channel injects content of its own.

## zhizengzeng · api.zzz-api.top (overseas) / api.zhizengzeng.com (mainland)

Tested 2026-08-17 with `claude-sonnet-5` / `gpt-5.6-sol` /
`gemini-3.1-pro-preview`, plus `glm-4.5-flash` as the free smoke test. Both
hostnames take the same key and list the same 828 models; treat them as one
gateway with two entry points.

**This one really does pass through** — it is the opposite case to bltcy, and
worth stating plainly, because the code needed for it is nothing at all:

- **An invalid control parameter** — bltcy returns 200 (dropped); zhizengzeng
  returns **the upstream's own 400** on all four paths tested.
- **The thinking block's `signature`** — absent on bltcy (response rebuilt);
  **present** on zhizengzeng (924 / 1624 chars).
- **`input_tokens` for an identical body** — bltcy fluctuates by ~100 (body
  rewritten); zhizengzeng gives 4054–4090 against the official 4068
  (**not** rewritten).
- **Request headers needed** — bltcy needs two (beta + UA); zhizengzeng needs
  **none**.

The four invalid-value probes, following the "How to decide" rule above — every
one came back as the upstream's own error text, so every one of these parameters
reaches the real API:

```
/v1/messages          tool_choice -> a tool not in tools          400
/v1/messages          output_config.effort: "nonsense"            400 "Input should be 'low', 'medium', 'high', 'xhigh' or 'max'"
/v1/chat/completions  tool_choice -> a function not in tools      400 "no function named 'no_such_tool'"
/v1beta/...           thinkingConfig.thinkingLevel: "NONSENSE"    400, Google's own protobuf-path message
```

All three native paths are live and authenticate the official way (`x-api-key`,
`Authorization: Bearer`, `x-goog-api-key`): `/v1/messages`,
`/v1/chat/completions`, `/v1beta/models/...:generateContent`. `/v1/responses`
is live too. Single-round text, `response_format="json"` with a local schema
check, tools under `tool_choice=REQUIRED`, and `effort` all pass on all three
backends.

The **multi-round tool loop** — the shape the pipeline actually runs — passes on
claude.py and fails on gemini.py, and neither result is about this gateway:

```
remote-claude  claude-sonnet-5        round1 tool_call -> tool_result -> round2 answer   OK, max_tokens=48000
remote-gemini  gemini-3.1-pro-preview round2 400 "Function call is missing a thought_signature"
remote-gemini  gemini-3-pro-preview   same
remote-gemini  gemini-2.5-flash       round1 400 "Thinking level is not supported for this model"
```

Note the claude line in passing: `max_tokens=48000` (the default 600s timeout)
was accepted without complaint, which is the value bltcy fails on. The three
gemini lines were our own adapter's gaps against model versions it predates, not
the gateway's doing; they are fixed, and the sub-section below is kept for the
reasoning.

**What any backend has to do for this gateway: nothing, and neither does the
user.** No headers are needed at all here: caching writes and reads on the SDK's
own user-agent with no `anthropic-beta` header, which is exactly the condition
bltcy fails.

### Prompt caching: it works, but only about a third of the time

Same 4066-token system prefix, sent twice per run, three runs on
api.zzz-api.top, against the official endpoint as the control:

```
official        write 4066 -> read 4066          (hit every time)
zzz-api.top     w,w | r,w | w,r                  2 reads / 6 calls = 33%
zhizengzeng.com w  -> read 1450 + write 4063     partial
```

Break-even is a 21.7% hit rate (write 1.25x, read 0.1x), so leave caching on.
The misses are channel rotation, not a lost `cache_control`: a hit reads the
whole prefix (5513 tokens reported) rather than a fragment, which is what a
gateway that had dropped `cache_control` could never produce. Nothing we can
control, and the same root cause as bltcy's 37.5% — a pool of upstream accounts
with a cache each.

Also note the cache counters are not to be trusted for accounting: a hit reports
`input_tokens` 5515 where the official endpoint reports 4068 for the same body,
and a request with no system prompt at all once reported `cache_read` 1450.
The *text* arrives intact (that is what the 4054–4090 range says); it is the
usage arithmetic that is loose.

### Never use the `-thinking` model ids

The list carries `claude-sonnet-5-thinking`, `claude-opus-5-thinking` and so on.
They are the relay convention for "turn thinking on by model name", and they are
wrong for this family twice over:

```
/v1/messages          claude-sonnet-5-thinking   400 "原生claude格式,不需要加-thinking"
/v1/chat/completions  claude-sonnet-5-thinking   400 "thinking.type.enabled is not supported for this model.
                                                     Use thinking.type.adaptive and output_config.effort"
```

The suffix maps to the legacy `thinking: {type: enabled}` shape, which the
sonnet-5 family removed. Send the plain model id and let `effort` do the work —
which it does: on a hard prompt at `effort=xhigh` the relay returned a signed
thinking block with 235 output tokens against the official endpoint's 227 for
the same body. (On a trivial prompt both endpoints often think nothing at all;
that is `adaptive` deciding, not the relay dropping the parameter. Judge this
one on a prompt hard enough that thinking is certain.)

### gemini.py was behind its model versions — fixed 2026-08-17

Found by the probes above, but **our bug, not the gateway's**: in both cases the
gateway relayed Google's own error and the request genuinely never carried what
Google asked for. Both are fixed in gemini.py; recorded here because the next
model generation will pose the same question.

**Gemini 3 requires `thought_signature` to be replayed.** A round-1 reply's
`functionCall` part comes back paired with a `thoughtSignature` (669–1132 bytes,
confirmed on the raw wire), and round 2 must send it back on the same part.
`_convert_messages` rebuilt the part from name and args only, so round 2 400'd
with "Function call is missing a thought_signature in functionCall parts".
Fixed by carrying the signatures in `ChatResponse.thinking_blocks` — the same
provider-native opaque carrier claude.py uses, base64 text because the
transcript writer puts the field through `json.dumps` — and reattaching them in
`_convert_messages`. The runner and transcript already copy that field through
verbatim, so nothing outside this adapter changed.

Worth naming the asymmetry: on Anthropic, `thinking` and `thinking_blocks` are
two views of one thing (readable summary, signed original). On Gemini they are
unrelated — `thinking` is thought-part text, `thinking_blocks` is an opaque
signature attached to *other* parts. Same field, same contract ("only the
producing adapter reads it"), different content.

**`effort` was Gemini-3-only without saying so.** `_EFFORT` maps a rung to
`thinking_level`, which the 2.5 family does not have (it takes
`thinking_budget`), so any call with `effort` set 400'd on `gemini-2.5-*` with
"Thinking level is not supported for this model". Fixed by gating on
`_supports_thinking_level` and dropping the knob with one warning otherwise —
which is what `ChatClient.invoke` already promises for a backend that lacks a
knob. Deliberately **not** fixed by converting a rung into a `thinking_budget`
token count: the module's own comment refuses to invent numbers nobody measured,
and that reasoning did not change.

Verified after the fix, through the production chain (round1 tool_call →
tool_result → round2 answer): `gemini-3.1-pro-preview`, `gemini-3-pro-preview`
and `gemini-2.5-flash` all pass, the last one logging the dropped-effort warning.

One caveat that is the gateway's and not ours: `gemini-3-pro-preview` returned
**"Corrupted thought signature"** once, then passed 6 for 6 on a re-run across
both hostnames. A signature is bound to the context that issued it, so a round-2
request landing on a different upstream account than round 1 cannot validate it.
Same root cause as the caching hit rate above — channel rotation — and the same
answer: nothing we can do on this side, and it is a retry, not a bug.

### GPT 5.5+ cannot combine function tools with reasoning on this path

Not a gateway deviation — the upstream's own restriction, relayed verbatim —
but it lands on `remote-openai` and so belongs here:

```
Function tools with reasoning_effort are not supported for gpt-5.6-sol in
/v1/chat/completions. To use function tools, use /v1/responses or set
reasoning_effort to 'none'.
```

It is OpenAI's own, not this relay's: the same message is reported against the
official endpoint all over the ecosystem (litellm #33221, LibreChat #14231 /
#14355, crush #2913, pipecat #4043, ruby_llm #785).

The boundary, measured id by id with an identical body:

```
                      effort unset   effort=low   effort=none
gpt-4o / 5 / 5.1 / 5.2 / 5.4  OK         —            —
gpt-5.5                       OK        400          OK
gpt-5.6-sol / terra / luna   400        400          OK
```

So there are two separate facts, and the second one is easy to overstate:

1. **From gpt-5.5 on, `tools` + a non-`none` `reasoning_effort` is a 400.** This
   is the one that bites us: openai.py sends `reasoning_effort` exactly when the
   caller passes `effort`, and the agent loop passes `tools` every round, so any
   node with an effort rung fails.
2. **The gpt-5.6 family additionally defaults to a non-`none` effort**, so it
   400s even with the parameter absent. gpt-5.5 and earlier are fine as long as
   no rung is set.

Note what `reasoning_effort: "none"` does and does not do: tool calling still
works (verified, the call comes back correctly) — you simply get no reasoning,
`reasoning_tokens=0`. On `/v1/chat/completions` it is tools **or** reasoning,
never both, which is precisely why OpenAI's own error points at `/v1/responses`.
The same request there works, returning the function call with
`reasoning.effort=high` accepted.

Consequence for us — **resolved 2026-08-17 by splitting the backend in two**
(see the section below). Chat Completions still cannot combine tools with
reasoning and never will; `remote-openai-responses` goes around it. Verified
through the production chain on this gateway, the same request on both:

```
remote-openai-compatible   tools + effort=high   400
remote-openai-responses    tools + effort=high   OK, tool_calls=['get_weather']
```

### Which hostname

Measured back to back, api.zhizengzeng.com is slightly faster from here
(`/models` 2.0s vs 2.2s; the per-call spread across the probe is larger than the
difference between the two). They behave identically on every functional test,
so pick either; the mainland host is the safer default without a proxy.


## What a backend author needs from class 2

If you are changing code under `remote/` rather than picking an endpoint, these
three are the whole of it:

- **A gateway speaks one of the three official wire formats.** There is no
  fourth protocol, so this project contains no "gateway translation" code and
  no gateway subclasses.
- **Nothing is added to a request on a user's behalf.** What goes on the wire is
  what the config says; a known-endpoint measurement produces at most a warning.
- **Anything a gateway silently drops is caught on the result side**, by class
  3's always-on validation — which is on for direct connections too.

---

# Class 3 · Lost guarantees and result-side validation

Class 2's "silently dropped parameters" have no request-side answer — the bytes
you send cannot change what the gateway does. The only reliable response is to
**verify on the result side that the promise was kept**. This validation is
backend-independent and is **on for direct connections too**: when the official
API really enforced the constraint, validation passes at zero cost; when
anything in the middle swallowed the parameter, it turns a silent wrong into an
explicit error. It is not a gateway patch, it is "trust nothing in the middle
about the output format" — the same principle as this project's explicit-failure
rule.

Intent by intent:

**`response_format="json"`** — lost when the gateway drops `response_format`, and
Anthropic has no such parameter anyway. Result-side: `clean_json` plus parse,
raising on failure. Status: `validation.py::ensure_valid_json`, **wired into both
backends** (2026-08).

**`json_schema`** — lost when the gateway drops the parameter, when the SDK strips
unsupported keywords, or on refusal or truncation. Result-side: full local
`jsonschema` validation, including the stripped constraints. Status:
`validation.py::ensure_schema_valid`, **wired into both backends** (2026-08).

**strict tools / tool inputs** — lost because the request body is rewritten, so
strict is unreliable. Result-side: the tool handler validates its own inputs
rather than relying on API-level schema enforcement. Status: a convention,
enforced on the `state_tools` side.

**`tool_choice`** — dropped by the gateway, after which the model does as it
likes. Result-side: `ToolChoice.verify_response` — REQUIRED must produce a call,
TOOL must call the named tool, NONE must produce none. Status: implemented
(`model.py`, wired into both backends).

**`thinking` control** — dropped outright by the gateway, **with no result-side
fallback**. No verification needed after all: the parameter is purely additive
(a summary for the trace), so a drop degrades to "no text" — today's behaviour —
never to a wrong result. The replay side self-protects via the signature gate
(unsigned blocks are never sent back). Status: settled 2026-08-14; no capability
declaration needed.

Two kinds of declaration, not to be confused:

- **With a fallback** (`response_format`, `json_schema`, `tool_choice`): let it
  go quietly to result-side validation, with no need to error just because the
  gateway declares something — erroring would close off a route that works. Note
  that `tool_choice`'s fallback is **detective**: by the time a drop is found,
  one call has already been paid for; the only guarantee is that a wrong result
  will not be used;
- **Without a fallback but purely additive** (`thinking` control): nothing can
  be verified on the result side, but nothing needs to be — the parameter only
  adds trace text, so a silent drop degrades to the no-thinking behaviour and
  never to a wrong result. Sent quietly, and the replay side self-protects via
  the signature gate (2026-08-14). If a future control parameter is both
  unverifiable *and* result-changing, that is when a capability declaration
  (raise on use) becomes the answer.

---

---

# What to test when connecting a new gateway

Work through class 2's method item by item:

1. Whether each of the two protocol paths works, and which authentication it takes
2. The base_url shape (does `/v1` need stripping, is there an extra path prefix)
3. Whether the model name needs a prefix or a date suffix
4. Whether the control parameters `tool_choice` / `response_format` /
   `output_config` / `thinking` pass through. Note there are three outcomes:
   400 (passed through) / 200 (dropped) / **hang** — a hanging channel has to be
   caught by a hard client-side timeout
5. **Test each parameter per model channel**: passthrough behaviour differs by
   upstream channel (on the bltcy gateway the GPT channel passes tool_choice
   through while the claude channel drops it), and a conclusion from one channel
   does not carry to another
6. Whether `cache_control` passes through, and whether a particular header or UA
   is needed
7. Whether the response's usage fields are complete, and whether thinking has a
   signature
8. Whether `input_tokens` is stable when the same request body is sent twice;
   and along the way, use a functional test to make the model state its own
   identity, to see whether the upstream is a reconstructed channel

---

## Where this knowledge lives, and where it does not (settled 2026-08-18)

**The code knows nothing about any endpoint.** `factory.py` inspects no
hostname, adds no header, checks for no relay. Whatever reaches the wire is what
the config asked for — `extra_headers` is the only route, and it is passed
through verbatim.

So the division is:

- What an endpoint needs, and how it was established — **this document**.
- The headers themselves, for a run that uses that endpoint — **that run's
  config**, beside the url they belong to.
- Adapting to protocol shape (`/v1` stripping, tool-call shapes) — the backend
  files, general rather than per-endpoint.
- Catching what an endpoint silently dropped — `validation.py`, always on,
  direct connections included.

Two earlier arrangements were tried and are recorded here because the reasoning
matters more than the outcome. First the headers were **merged in automatically**
by a hostname-keyed preset table, so a user configured only url / api_key /
model; that put two headers on the wire that the config never mentioned and the
user could not switch off, one of them a user-agent claiming to be curl. Then
the table was kept but **demoted to a warning** — which is the incoherent middle:
if the code recognises the host well enough to advise, it recognises it, and a
general client has no business naming a commercial vendor at all.

What settles it: **a general client should not be able to name a commercial
vendor**, and what goes on the wire has to be what the config says — the same
rule that makes an empty `api_key` an error rather than a silent fall back to an
environment variable. A run's config is the record of what that run did.

The cost, stated plainly: someone pointing at a relay has to read this document
and copy two lines into their config. That is a real cost, paid so that the
client stays honest about what it sends.

**Why there is no gateway subclass, profile or wrapper layer:**

- **There is nothing to put in them.** A subclass or profile presupposes
  "gateway-specific logic that needs code to carry it"; the measurements
  dissolved that premise — the request-side difference is two headers
  (configuration values), and the guarantee-side difference is validation that
  should be on anyway. Building a type for an empty set is a liability.
- **The industry does not build a "gateway x backend" matrix either:** LiteLLM
  has a declarative provider-capability table plus `drop_params` (data, not
  classes); the Vercel AI SDK has `wrapLanguageModel` middleware (a decorator);
  OpenRouter does the parameter adaptation on the gateway side. Our end state
  saves one more layer than LiteLLM: not even a capability table is needed,
  because "validate the result" replaces "predict the capability" — a prediction
  goes stale when the gateway switches channels, validation is always right.
- **The real cost of the cartesian product is not the number of classes, it is
  the surface to strip before open-sourcing:** N gateway subclasses = N places to
  delete; as it stands = 0 lines of code to delete.
