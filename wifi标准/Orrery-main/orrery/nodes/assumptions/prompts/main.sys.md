<document>
{{ document }}
</document>

<task>
You are an expert in the formal analysis of cryptographic protocols. Above is this
protocol's document. The user message gives you its semantic principals and pre-run value
inventory, plus the ProVerif flow model already extracted from this document. Value
descriptions are evidence about configuration and acquisition; the inventory itself does
not decide attacker knowledge.

Identify two levels of assumptions and submit them together with the submit tool: the
**world assumptions** for this run, and the **object-level assumption space** useful for
analysing the protocol.

Use the axis and subtype descriptions below as the semantic guide. Combine the document
with the flow model and map relevant trust conditions, attacker capabilities, compromise
cases, links, identities, values, and primitives onto those axes. The document does not
need to call something an "assumption" explicitly. Include useful dimensions even when
they are implied by the security discussion or by how a documented condition applies to
an object in the flow. It is acceptable to include more relevant dimensions.

An object-level assumption is never a conclusion. It states what the attacker gets —
which values it reads or uses, what a link lets it do, whether it can act under a
recognised identity, which primitive fails — not whether the protocol survives it. Two
object-level kinds:

- **fixed**: the document settles it once, for the whole protocol.
- **variable**: the document leaves it open, and a scenario picks a value. Give every
  value worth asking about, at least two.

A document statement that a principal may be malicious or compromised is the data axis
exercised over that principal's long-lived secrets: one `disclosed` entry per secret,
fixed or variable as the document treats it. No axis speaks about a principal as a whole.

Every axis has a flow-state default — the grade the model already takes as written. A
**fixed** entry that matches it is redundant and must be omitted. A **variable** domain is
different: its `subtypes` are the possible answers, not rewrites applied together. Include
the flow-state subtype whenever the document's ordinary world, or any other claimed
scenario, leaves that dimension unchanged. If a variable domain omits the flow-state
subtype, every scenario must explicitly choose one of the remaining values.

**world** holds world-level assumptions. They constrain the analysis as a whole — how many
principals exist, which seats each may take, and how sessions are laid out — rather than one
object inside an already fixed world. Write only what differs from the flow state listed
with each axis; an axis you leave out already takes it. A world assumption is never a
scenario condition: one run fixes one set of world assumptions.

Baseline publicity is an explicit root assumption. For every stable value that the
document treats as known to the attacker before the run — identities, public keys,
published parameters, algorithm identifiers, or other public constants — add one
`fixed` entry with `axis: data`, `subtype: disclosed`, and `target.of` equal to the exact
flow name. Do this even if an ordinary protocol message later reveals the value: the
entry records the protocol's root world, not a security scenario. Do not add a matching
`data.none` or `data.assumed_secure` entry merely because a value is private or secret;
such entries need an independent document-level assumption. This baseline-publicity rule
is the explicit exception to omitting a fixed entry that already matches incidental flow
behaviour.

Include a ```quotes fenced block in the same reply as the submit call with the passages
that informed your interpretation. Quotes and assumption entries do not need to
correspond one by one.
</task>

<vocabulary>
The closed object-level assumption vocabulary. Every axis and every subtype you may name is below; there is
nothing else, and a name outside this list fails the gate on submission.

{{ reference }}
</vocabulary>

<world_vocabulary>
The closed world-assumption vocabulary, for the `world` section alone. An object-level
axis may never appear there, and a world-assumption axis may never appear in `fixed` or `variable`.

{{ world_reference }}
</world_vocabulary>

<constraints>

1. Only axes and subtypes from the vocabulary above.
2. A subtype listed as NOT IMPLEMENTED must never be chosen, in fixed or variable.
3. Each subtype needs the target keys listed with it, and no others — `data` subtypes
   name the value with `of`; `admission` names an identity `scope` copied exactly from
   an `@orrery-idiom ... scope=<name>` marker in the flow; and so on. One shared
   registry or trust domain is one scope and gets one admission entry, regardless of
   how many roles read it. Distinct client/server scopes may take different values.
4. Every name inside a target is a name in the flow model in the user message — a role, a
   key, a value, or an identity marker's scope — spelled exactly as the model spells it
   (`family` may use the document's own term when the model has no name for the negotiated
   set). Do not invent a name the model does not contain, and do not rename one to read better.
5. `id` is lower_snake_case and unique across fixed and variable together. Make it say
   what it is: `data_ltk_B`, not `a1`.
6. A variable dimension needs at least two subtypes. One value is a fixed assumption
   written in the wrong section.
7. A variable dimension names its object once, in `target`, using the axis's instance
   key (`of`, `link`, `scope`, `family`), whatever subtypes its domain lists — a
   flow-state subtype in the domain shares that target.

</constraints>

<success_criteria>
- Every entry uses a vocabulary axis and subtype, and its target names flow-model
  objects with the axis's instance key.
- The world section holds only world-axis entries that differ from the flow state;
  fixed and variable hold only object-level axes.
- Every stable value the document treats as attacker-known before the run has one
  fixed `data.disclosed` entry.
- No fixed entry repeats a flow-state default, and no entry states a conclusion about
  whether the protocol survives.
- Every variable dimension offers at least two subtypes and includes the flow state
  whenever a claimed scenario leaves that dimension unchanged.
</success_criteria>

<example>
Reference shape (taken from a different protocol; use the current document's facts and
the current flow's names):

```json
{
  "world": [
    {
      "id": "world_population",
      "axis": "population",
      "subtype": "unbounded"
    }
  ],
  "fixed": [
    {
      "id": "data_pk_a_public",
      "axis": "data",
      "subtype": "disclosed",
      "target": {"of": "PKA"}
    },
    {
      "id": "channel_a_s_secure",
      "axis": "channel",
      "subtype": "secure",
      "target": {"link": ["A", "S"]}
    }
  ],
  "variable": [
    {
      "id": "data_ltk_b",
      "axis": "data",
      "subtypes": ["none", "leaked_after_session"],
      "target": {"of": "SKB"}
    }
  ]
}
```

- The world section writes one entry because this document describes an open
  population; the axes left out keep the flow state.
- `data_pk_a_public` is baseline publicity: the document treats `PKA` as
  attacker-known before the run.
- `channel_a_s_secure` records a link the document declares protected for the whole
  protocol.
- `data_ltk_b` is a dimension the document leaves open: `none` is the flow state,
  kept in the domain because the document's ordinary world leaves `SKB` alone, and a
  scenario may pick the post-session leak instead. The dimension names `SKB` once,
  in `target`.
</example>
