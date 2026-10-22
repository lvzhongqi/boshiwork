<task>
The situation to build: the named long-lived secret reaches the attacker only after a session completed correctly — the weak-forward-secrecy premise. Every message of that completed session was exchanged while the secret was still safe, and the leak exists only in worlds where a correct completion happened.

The shape it takes: two pieces, both this assumption's own.
1. A completion record: declare a table, and at the point the holder's role completes correctly — its final protocol check passed, its last protocol send done — insert a constant token into it.
2. A gated leak: one new unreplicated branch in the main process's parallel group, `| phase <N>; get <table>(x) in out(c, K)`, with `<N>` the phase the target names. Table rows persist across the phase boundary, so the leak fires exactly in the worlds that recorded a correct completion.
</task>

<constraints>
1. Insert the completion record on the success path only: after the role's last protocol check and last protocol send.
2. Gate the leak behind both the phase boundary and the table read: `phase <N>; get <table>(x) in out(c, K)`.
3. The table row carries a constant token; the secret travels only in the gated branch's `out(c, K)`.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the role's tail: the final check passes and the body ends *)
let processB(B: host, K: key) =
  ...
  if h = hash(Nb) then
  out(c, senc(ack, CK));
  0.

process
  ( !processA(...) | !processB(...) )

(* after -- (1) the completion record at the tail; (2) the gated leak in main.
   The table row persists across the phase boundary, so K leaks exactly in the
   worlds where a session completed correctly *)
table session_done(bitstring).
const done_tok: bitstring.

let processB(B: host, K: key) =
  ...
  if h = hash(Nb) then
  out(c, senc(ack, CK));
  insert session_done(done_tok);
  0.

process
  ( !processA(...) | !processB(...)
  | phase 1; get session_done(x) in out(c, K) )
```
</example>
