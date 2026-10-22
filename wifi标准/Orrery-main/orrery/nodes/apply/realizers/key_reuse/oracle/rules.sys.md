<task>
The situation to build: the key `target.of` names serves a second use the attacker drives. The application protects its own fresh payload under the key — `target.payload` names it where the target gives one — and the attacker, beyond seeing that traffic, submits inputs of its own: it holds an oracle for the key's operation, receiving the key's output on any input it chooses. The attacker never learns the key.

The shape it takes: two pieces.
1. The appended honest use: at the tail of the role that already sends under the key, reproduce that role's existing chain under the key once more with a fresh payload; every other argument copied from the role's own call.
2. The oracle: one replicated branch in the main process's parallel group, inside the key's scope, reading the attacker's input from the public channel each round and answering with the model's own primitive applied under the key — every argument except the key from the attacker's input.
</task>

<constraints>
1. Use the model's existing primitive symbols under the named key; introduce no new function.
2. The oracle answers with the operation's output only; the key appears in no output.
3. Exactly one appended honest use and one oracle branch; protocol roles, messages and checks stay as they are.
</constraints>

<example>
A signing key (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* the honest second use at the sender's tail: a fresh payload over the
   role's own transcript, the same road out *)
let processI(...) =
  ...
  new app1: bitstring;
  out(c, sign((TH_4, app1), skI));
  new app2: bitstring;
  out(c, sign((TH_4, app2), skI));
  0.

(* the oracle branch: the attacker submits any message and receives its
   signature under skI. The key itself never leaves *)
process
  new skI: skey;
  ( !processI(...) | !processR(...)
  | !in(c, m: bitstring); out(c, sign(m, skI)) )
```
</example>
