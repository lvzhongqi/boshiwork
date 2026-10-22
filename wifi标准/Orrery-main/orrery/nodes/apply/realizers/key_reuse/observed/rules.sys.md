<task>
The situation to build: the key `target.of` names serves a second use in this deployment — an application beyond this protocol protects its own data under the same key — and the attacker sees that second use's output. The application's payload is its own fresh value, under `target.payload`'s name where the target gives one; the attacker observes the traffic, never the key, and never chooses the payload.

The shape it takes: one appended use at the tail of the role that already sends under the key, placed after that role has run to completion — every receive processed, every check passed, its last protocol send done, at the body's tail. Find that role's existing use of the key, read outward through every wrapper the protocol puts around it up to the `out(...)` that carries it, and reproduce that whole chain once more at the tail: a fresh payload in place of the protocol's, every other argument — key, transcript, associated data — copied from the completed run's own values.

- **a signing private key**: the same key signs the same transcript together with the fresh payload, and the signature travels the road the role's own signature travels.
- **a symmetric key**: the fresh payload is protected once more with the primitive the role already uses under that key — the same context arguments — and travels the same road.
</task>

<constraints>
1. Exactly one appended use, at the tail of the role whose existing send under the key the chain reproduces; every other role stays untouched.
2. The fresh payload is the only new name; every other argument — key, transcript, associated data, tags — is copied from the role's existing call.
3. The appended use sits after the whole protocol flow completes — after the role's last decryption, its last authentication check and its last protocol send — never between a receive and the check that validates it. A use reachable before those checks turns the role into an oracle for attacker-supplied input, a strictly stronger world than this one. Every existing line of the role stays.
</constraints>

<examples>
<example>
A signing key whose protocol road runs through an AEAD (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the role's tail.  Read the road this signature travels:
   sign(...) -> sealed by aeadEncrypt(..., K_3, aad_3) -> out(c, ...) *)
let processI(...) =
  ...
  new app1: bitstring;
  out(c, aeadEncrypt((tag_prot, sign((tag_prot, TH_4, app1), skI)), K_3, aad_3));
  0.

(* after -- a fresh payload, the same key over the same transcript under the
   same tag, and the same road out: the appended signature is sealed in the
   AEAD too.  The protocol flow above is untouched *)
let processI(...) =
  ...
  new app1: bitstring;
  out(c, aeadEncrypt((tag_prot, sign((tag_prot, TH_4, app1), skI)), K_3, aad_3));
  new app2: bitstring;
  out(c, aeadEncrypt((tag_prot, sign((tag_prot, TH_4, app2), skI)), K_3, aad_3));
  0.
```
</example>

<example>
A symmetric key — the payload is fresh, the context is the role's own; with plain symmetric encryption there is no separate context argument:

```proverif
(* AEAD *)
let processI(...) =
  ...
  out(c, aeadEncrypt(app1, K_3, aad_3));
  new app2: bitstring;
  out(c, aeadEncrypt(app2, K_3, aad_3));
  0.

(* plain senc *)
let processA(...) =
  ...
  out(c, senc((K_ab, B), K_as));
  new app2: bitstring;
  out(c, senc(app2, K_as));
  0.
```
</example>
</examples>
