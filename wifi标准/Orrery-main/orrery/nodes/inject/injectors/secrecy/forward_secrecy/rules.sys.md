<task>
Inject every `forward_secrecy` goal into the complete scenario model.

The scenario model already contains the long-term-key compromise: as a leak
behind a `phase` boundary, or as knowledge the attacker holds from the start.
The goal asks whether the session secrets of completed runs stay safe in that
world.

For every goal value × holder, wrap a private witness under the holder's local
value at the end of its completed run, then query that witness without a phase
annotation: the query is evaluated on the attacker's final knowledge, after
every leak the model contains.

Put witness declarations, one-way wrapper declarations, and queries in
`declarations`. Put witness outputs, guards, and coordinated role/main rewrites
in `edits`.
</task>

<constraints>
1. Keep the model's compromise exactly as it stands: preserve every existing
   `phase` boundary and leak, and add neither a phase nor a leak of your own.
2. Give every goal value × `parties.holders` entry an independent witness,
   query, and output. Every introduced name contains the exact goal id.
3. Bind the witness to the holder's actual phase-0 value after the value is
   available and after the role's final protocol send.
4. Map goal values by meaning to the model's names, types, and local bindings.
5. Decide the goal's session scope once and apply it at every witness output.
   When the goal covers only honest sessions, guard every output whose role
   reads or selects any peer identity or credential during the run, comparing
   those actual values with independent stable honest values from `main`;
   update the role signature and every call as needed. A role whose peers are
   all `main`-fixed honest parameters carries no guard. When attacker-peer runs
   are part of the goal, every witness stays unguarded. A guard wraps only the
   witness output.
6. Preserve protocol messages, checks, branches, sends, and the existing phase
   boundary. Preserve a role's final `0.` in tail replacements.
</constraints>

<success_criteria>
- Every goal value × holder has one private witness, one unannotated query, and
  one witness output at the holder's run end.
- The model's compromise structure is unchanged: every existing phase boundary
  and leak stays, and no new one appears.
- Honest-session guards use independent stable references and wrap only the
  witness output.
- The protocol and scenario assumptions retain their original behaviour.
</success_criteria>

<example>
```proverif
type key.
free c: channel.
fun senc(bitstring, key): bitstring.
reduc forall m: bitstring, k: key; sdec(senc(m, k), k) = m.
fun k2b(key): bitstring [data, typeConverter].
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.

free witness_forward_secrecy_app_key_A: bitstring [private].
query attacker(witness_forward_secrecy_app_key_A).

(* the session's record travels under the long-term key, so the phase-1 leak
   reaches back through it: the query answers false -- this protocol does not
   have forward secrecy. The injection is the witness and the query alone;
   the compromise is the scenario's own *)
let processA(ltk: key, app_key: key) =
  out(c, senc(k2b(app_key), ltk));
  out(c, wenc_key(witness_forward_secrecy_app_key_A, app_key)).

process
  new long_term_key: key;
  new app_key: key;
  ( !processA(long_term_key, app_key)
  | phase 1; out(c, long_term_key) )
```
</example>
