<document>
{{ document }}
</document>

<task>
You are an expert in the formal analysis of cryptographic protocols. Above is the
protocol document. The user message gives you a semantic inventory of principals and
pre-run values, plus a thin ProVerif scaffold. The inventory deliberately does not decide
types, holders, process parameters, constructors, attacker knowledge, or main-process
initialisation. Infer those formal choices from the document and the complete flow.

Complete the scaffold into a runnable `.pv` file whose flow matches the documented
protocol. This is the protocol's base flow model: black-box cryptographic primitives,
honest parties, and the fixed Dolev-Yao attacker.

Complete three parts:

1. At `(* @DECLARATIONS *)`, write the declarations the model needs:
   - `type` for semantic types other than the built-in `bitstring`;
   - `const` / `free` for global constants and free names;
   - `fun`, `reduc`, and `equation` for primitives and their symbolic semantics.
2. At every `(* @ROLE X *)`, write exactly one `let processX(...) =` definition. Choose
   parameters from what the role actually needs when it starts, then implement the
   documented sends, receives, fresh values, lookups, and checks.
3. At `(* @MAIN *)`, create or configure pre-run values, bind derived values, install
   honest state, and invoke every role.

Deliver the complete executable `.pv` file in one ```proverif block. If an upstream
artifact lacks information required to continue, call `report_gap`.
</task>

<constraints>
Template and declarations:

1. Preserve every framework-owned protocol comment, marker, channel declaration,
   honest-run event declaration, and probe query verbatim. Fill around markers; do not
   delete, rename, or duplicate existing lines.
2. Put declarations only at `@DECLARATIONS`. Role definitions and `process` belong at
   their respective markers.
3. Every value in the semantic inventory must occur under its exact stable name.
   `derived_from` states deterministic dependency, not a constructor. For
   `Y.derived_from: [X, ...]`, bind exactly one
   `let Y = <term using every listed source> in`; never create `Y` independently with
   `new`, `free`, or `const`. Read the description and document to decide whether the
   relation is a signing public key, encryption public key, DH public value, verifier, or
   something else.
4. A value without `derived_from` may be a `new`, `free`, `const`, process input, or table
   result, according to the document. Do not infer its holder from list position or its
   name. Model built-in values, provisioned values, and run-time lookups in their actual
   operational form. `new` mints a secret: fresh, unguessable entropy. Algorithm
   identifiers, protocol tags, and other ambient parameters that every party and the
   attacker knows from the specification are `const` or public `free` declarations,
   never `new` — including when the semantic inventory carries one as a value.
5. Do not output a value to the attacker merely because its description calls it an
   identity, a public key, or another party-held public value. Publicity is applied
   downstream as a fixed `data.disclosed` assumption. The base flow contains only
   documented messages and provisioning steps.
6. Reuse functions and equations supplied in the user message. When a standard primitive
   is missing, call `lookup_function_signature` first. If lookup misses because the
   document defines a custom transformation, declare a one-way `fun` with no `reduc`.
   Give it reversible semantics only when a legitimate role must recover the source.
7. When the protocol uses identities, long-term keys, PKI, a CA, certificates, or
   credentials to select a key or accept a peer, call `lookup_identity_modeling`. The
   query must say what was received, where the peer key comes from, whether lookup occurs
   at run time, whether a certificate is verified, and what the document omits. Select
   one applicable method per identity scope and follow its rules and marker. Do not
   invent a mechanism when no candidate applies, and do not call the tool when the
   document has no identity binding.

Roles and main process:

8. Only pre-run values a role genuinely needs at startup belong in its parameters. Values
   received, generated, or looked up during the run stay in the body; the semantic
   inventory does not itself determine a parameter list.
9. Each role uses its directed channels: `out` on `channel_<self>_<peer>` and `in` on
   `channel_<peer>_<self>`.
10. Pair every protocol-message `out` with the corresponding `in`; leave no protocol send
    without a receiver.
11. Receive into a `bitstring`, then decrypt or destructure according to the actual message
    shape until every field has its own name and type. For example, first write
    `in(channel_A_B, msg: bitstring);`, then
    `let (x: bitstring, y: host) = msg in`.
12. `bitstring` is a transport and container type; it must not erase semantic types that
    prevent type-confusion attacks. Use distinct types for identities, nonces, keys,
    exponents, and other protocol atoms. When a semantic atom is used alone as a
    `bitstring` payload, declare and use
    `fun <type>_to_bitstring(<type>): bitstring [data, typeConverter].`; tuples need no
    converter.
13. Fields built by the sender and fields extracted by the receiver match exactly in
    count, order, nesting, and type. Model every semantic field the document defines
    for the analysed flow's messages under its documented stable name, optional fields
    included; a field the document leaves unconstructed is a fresh value at its origin.
    Optionality says a real deployment may omit the field; the base flow models it
    present.
14. Do not bind a name twice in one scope. Prefer document symbols; suffix received values
    with `_recv` to distinguish them from locally held semantic values.
15. Implement only checks required by the document. When a received value must match a
    local value, write `if <received> = <local> then`. Write `else` only when the document
    specifies failure behaviour.
16. For timestamps, ticket lifetimes, sequence numbers, and other time-varying parameters,
    call `lookup_time_variant_modeling`. State who creates and receives the value, how it
    is checked, what happens on expiry, and whether it is integrity-protected, then use
    the returned method.
17. Every independent interaction has a clear first sender; do not make all roles of an
    interaction wait to receive first.
18. Replicate roles without bound in main by default, for example `!processA(...)`. Omit
    replication only when the document explicitly limits the role to one run. If one
    principal has multiple independent entries or concurrent behaviours, call
    `lookup_structure_modeling` first and use the returned structure.
19. `reached_<role>` marks honest success for that role. Call it after the last message is
    processed and every documented check has passed. Nothing follows the event: no `;`
    and no later statement. End every successful branch separately. Never infer success
    from the last textual `0`.
20. The scaffold's `[private]` channels and reached probes test honest-run reachability
    only. Still model the real messages, checks, and bindings required when the final flow
    runs on a public Dolev-Yao network.
</constraints>

<success_criteria>
- Every framework-owned line is preserved verbatim, including the complete probe.
- Every semantic value uses its exact name; each `derived_from` value has one named `let`
  binding that uses every source.
- The base flow does not leak a value merely because its description calls it public.
- Every principal has exactly one role definition, invoked from main with the values it
  actually needs.
- Every role's honest execution reaches its own `reached_<role>`.
- Every name, type, function, and equation is declared exactly once.
- Every documented message, field, and check is modeled, and sender/receiver structures
  match exactly.
- Every check genuinely depends on run state: the two sides of a comparison can
  differ, and no check is identically true.
</success_criteria>

<example>
This complete minimal model demonstrates derived public keys, semantic types, paired
sends and receives, received-value names, checks, replicated roles, and reached probes.
It demonstrates code organisation only; use the current document's roles, messages, and
cryptographic operations in the submitted model.

```proverif
(* Protocol: Example *)

(* -- Declarations -- *)
(* @DECLARATIONS *)
type host.
type nonce.
type pkey.
type skey.

fun pk(skey): pkey.
fun aenc(bitstring, pkey): bitstring.
reduc forall m: bitstring, sk: skey;
  adec(aenc(m, pk(sk)), sk) = m.

fun nonce_to_bitstring(nonce): bitstring [data, typeConverter].

(* -- Channels -- *)
free c: channel.
free channel_A_B: channel [private].
free channel_B_A: channel [private].

(* -- Honest-run probe -- *)
set reconstructTrace = false.
event reached_A().
event reached_B().
query event(reached_A()).
query event(reached_B()).

(* -- Role processes -- *)
(* @ROLE A *)
let processA(A: host, SKA: skey, PKB: pkey) =
  new N_A: nonce;
  out(channel_A_B, aenc((N_A, A), PKB));
  in(channel_B_A, msg_B_A: bitstring);
  let (N_A_recv: nonce, N_B_recv: nonce) = adec(msg_B_A, SKA) in
  if N_A_recv = N_A then
    out(channel_A_B, aenc(nonce_to_bitstring(N_B_recv), PKB));
    event reached_A().

(* @ROLE B *)
let processB(A: host, SKB: skey, PKA: pkey) =
  in(channel_A_B, msg_A_B_1: bitstring);
  let (N_A_recv: nonce, A_recv: host) = adec(msg_A_B_1, SKB) in
  if A_recv = A then
    new N_B: nonce;
    out(channel_B_A, aenc((N_A_recv, N_B), PKA));
    in(channel_A_B, msg_A_B_2: bitstring);
    let nonce_to_bitstring(N_B_recv: nonce) = adec(msg_A_B_2, SKB) in
    if N_B_recv = N_B then
      event reached_B().

(* -- Main process -- *)
(* @MAIN *)
process
  new A: host;
  new SKA: skey;
  let PKA = pk(SKA) in
  new SKB: skey;
  let PKB = pk(SKB) in
  (
    !processA(A, SKA, PKB)
  | !processB(A, SKB, PKA)
  )
```
</example>

<failure>
Call `report_gap` and stop when an upstream artifact lacks information needed for a valid
model:

- the documented flow requires a value absent from the semantic inventory;
- the document requires a cryptographic role absent from the principal list;
- the semantic inventory is internally inconsistent or omits a required deterministic
  dependency.

A standard primitive missing from the user inventory is not a gap: look it up first. A
document-defined transformation that needs no inversion is declared under constraint 6.
Do not submit a `.pv` file together with a gap report.
</failure>
