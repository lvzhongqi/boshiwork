<task>
The situation to build: the value `target.of` names is created by the role itself, once per session, and in this world that creation is replaced by attacker input — the rigged-RNG setting, where the coins come from a compromised runtime. The role runs on whatever the attacker hands it instead of on something it drew, so any binding the role derives from that value is the attacker's to decide.

The shape it takes: the value's `new` binding becomes an `in(c, ...)` of the same name and the same type. Nothing else moves — every use further down the body already reads the right name, and there is no honest reference to keep, because a value the role drew has no configured counterpart to compare against.
</task>

<constraints>
1. Keep the name and the type. Every later use in the body refers to it; renaming here means editing the whole body for no gain, and a type change makes the file stop typechecking.
2. Replace exactly the `new` that `target.of` names. A role that draws several values draws them for different reasons; sweeping in the others builds a wider world than the one declared.
3. A configured item bound by `new` inside a role body is usually a modelling slip: configuration is initial knowledge and belongs in the role's parameters, where this assumption's other writing would apply instead. Encode the world as asked, and record the observation with it — include one comment line at the top of the file noting that this value looks mistakenly modelled as freshly drawn upstream. That comment is the audit trail the base model gets corrected from later.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the role draws the value itself, once per session *)
let processA(A: host, B: host, SKA: skey) =
  new Na: nonce;
  out(channel_A_B, (A, Na));
  ...

(* after -- the draw becomes attacker input, same name, same type. Nothing
   below moves *)
let processA(A: host, B: host, SKA: skey) =
  in(c, Na: nonce);
  out(channel_A_B, (A, Na));
  ...
```
</example>
