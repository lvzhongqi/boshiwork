<document>
{{ document }}
</document>

<task>
You are an expert in formal cryptographic-protocol analysis. The user gives you one
run-wide world, one complete scenario assignment, and the security goals asserted in
that scenario.

Write the final ProVerif model for exactly that world and scenario. Construct the
protocol flow from the document, realize the selected world and object assumptions, and
add every requested goal observation. Submit one complete, directly runnable `.pv` in
exactly one ```proverif block.

You have no tools. `<document>` is the entire available corpus; sections not present
there cannot be fetched.
</task>

<constraints>

<reference>
{{ primitives }}

A destructor (`adec`, `sdec`, `verify`, `aeadDecrypt`) appears only in its `reduc`; do
not also declare it with `fun`. For a document-specific transformation absent from the
list, declare a one-way `fun` with no `reduc`, unless an honest role must recover its
argument to continue.
</reference>

<construction>
Construct one final model in this order:

1. Build the document's honest protocol flow using the flow defaults below.
2. Apply each selected world rule once, in its listed order.
3. Apply every non-noop point in the complete scenario assignment, in its listed order.
4. Add the requested goal observations and honest-run probes.

A selected rule overrides a flow default only on the axis and target it names. It never
changes unrelated protocol behavior. The delivered file shows the final state directly;
do not first write a default construct that a selected rule replaces.
</construction>

<flow_defaults>
- Use the standard Dolev-Yao attacker. Never make it passive.
- Sessions are unbounded and role calls are replicated unless a selected world rule
  changes session multiplicity.
- Directed role-to-role channels are public unless a selected channel rule changes the
  named link. Send on `channel_<self>_<peer>` and receive on
  `channel_<peer>_<self>`; every send has a matching receive.
- Read the principals and their pre-run knowledge from the document. Create that
  knowledge in the main process and pass it through role parameters. Do not output a
  value to the attacker because the document calls it an identity, public key, or public
  parameter: publication is a `data.disclosed` point of the assignment below, not a flow
  default. The flow itself carries only documented messages and provisioning steps.
- A value the document derives from others — a public key from its secret key, a session
  key from its inputs — is bound once with a `let` over every source it derives from.
  Never create a derived value independently with `new`, `free`, or `const`.
- Only pre-run values a role needs when it starts belong in its parameters. What it
  receives, generates, or looks up during the run stays in the body.
- Preserve document-declared per-session peer inputs as variables. Add `peer <> self`
  only when the document states that restriction.
- Preserve semantic types for identities, nonces, keys, exponents, and similar atoms.
  Receive a message as `bitstring`, then open it layer by layer, matching the sender's
  field count, order, nesting, and types. Use a `[data, typeConverter]` conversion when
  one semantic value is the sole payload of a primitive expecting `bitstring`; tuples
  need no conversion.
- Use the document's names. Suffix received copies with `_recv`. Declare every name,
  type, function, and equation exactly once, and bind no name twice in one scope.
- Write exactly the checks the document requires. Use `else` only when the document
  defines failure behavior. A state-dependent check must genuinely depend on that state:
  its two sides can differ, and no check is identically true.
- Use exactly one identity/credential method per identity scope, and write that method's
  `(* @orrery-idiom <id>/v<n> scope=<scope> *)` marker where it says. Use the applicable
  time-variant method for each time-varying parameter, and the structure method for a
  party the document lets several independent exchanges enter. Take all three from the
  libraries in the selected rules; invent none of them.
- The protocol has a sender that can start the honest run: one role's first channel
  action is `out`, with no preceding `in`. Represent a repeatable post-setup subflow with
  replication when the document says it may repeat.
- Each role definition ends at its final branch with `.`. The main process ends at its
  closing parenthesis, with no trailing `0` or `.`.
</flow_defaults>

<selected_rules>
The rules below are selected from the mainline registries for this exact request and are
authoritative for their named axis, target, or goal. Their references to an existing
model, anchors, edit JSON, tools, or submission envelopes describe the mainline
transport only: do not output those forms. Realize the stated semantics and ProVerif
pattern directly in the final file.

A rule's `<applies_to>` lists every target it covers. The rule text describes one target,
so apply it separately to each listed one; no listed target may be skipped and no value
outside the list may change.

Where a subtype ships alternative writings, each writing carries the value lifetime that
selects it. Read that lifetime off the model you write: a value drawn by a `new` inside a
role definition is `per_session`, because role bodies run replicated; a role parameter, a
`free`, a `const`, or a main-process `new` is `long_lived`. Each target takes the writing
its own lifetime selects, and no other.

{{ modeling_rules }}
</selected_rules>

<goal_attribution>
- Realize every goal with its selected goal rule.
- Every query must contain verbatim the id of its one owner goal, through the event,
  witness, or other name introduced for that query.
- A query names exactly one goal id. Every requested goal has at least one query.
</goal_attribution>

<honest_run_probe>
For every protocol role `X`, declare `event reached_X().`, add
`query event(reached_X()).`, and call `event reached_X()` in that role after its last
protocol action and every required check. Nothing follows the event in its branch: no
`;` and no further statement. Other branches end with `0`. Never call a role's probe
from the main process or another role.

The honest-success path may be an `else` branch. Follow the document's behavior, not the
last textual branch.
</honest_run_probe>

</constraints>

<success_criteria>
- The result is one complete `.pv` that ProVerif accepts without syntax or type errors.
- Its flow matches the document, and its final world and object assumptions equal the
  supplied scenario.
- Every documented message, field, and check is modeled, and sender and receiver
  structures match exactly.
- Each identity scope uses one library method and carries that method's marker.
- Every requested goal has independently attributable verdicts.
- Every protocol role reaches its own honest-run probe on an honest execution.
</success_criteria>

<example>
This complete file shows a probe on the success path when the document defines an error
branch. It is not a protocol template; role count and flow still come from the document.

```proverif
type nonce.
fun nonce_to_bitstring(nonce): bitstring [data, typeConverter].
const error_msg: bitstring.
free c: channel.

event reached_A().
query event(reached_A()).

let processA() =
  new N_a: nonce;
  out(c, nonce_to_bitstring(N_a));
  in(c, msg: bitstring);
  if msg = error_msg then
    0
  else
    if msg = nonce_to_bitstring(N_a) then
      event reached_A().

process ( !processA() )
```
</example>

<failure>
If the inlined document lacks a fact needed to construct the flow or bind a goal to a
model value, do not invent it. Reply `Cannot model: <missing fact and where it is needed>`;
the experiment records an explicit failure instead of a misleading verdict.
</failure>
