<task>
The situation to build: the attacker never obtains the value the target names — the analysis holds that as a premise. The premise is checked: a model that contradicts it fails loudly instead of returning verdicts.

The shape: one `not attacker(...)` line among the top declarations. No process changes at all: no role body, no signature, no main process.
</task>

<constraints>
1. State the premise on the existing term named by `target.of`.
2. Use `not attacker(new K).` for a `new` binding and `not attacker(K).` for a top-level `free` value.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the CA key is created in the main process and its secrecy is
   whatever the protocol makes of it *)
process
  new caSK: skey;
  ...

(* after -- one line in the top declarations makes it a premise. For a name
   bound by `new` the term is `new caSK`; for a name declared `free` it is the
   name itself. No process changes *)
not attacker(new caSK).

process
  new caSK: skey;
  ...
```
</example>
