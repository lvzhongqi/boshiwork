<task>
The situation to build: the value `target.of` names is configuration — a role parameter, fixed before the run starts, so today that role always runs with what the world configured for it. In this world the attacker selects it: what the network supplies is what the role is configured with. On a peer credential this is the Lowe man-in-the-middle world; on a negotiated parameter it is the downgrade world, where the two ends are no longer guaranteed to have been configured alike.

The shape it takes: one edit in the main process, at the binding or argument that configures the role running on this value. That honest expression becomes a receive from the public channel, sitting where the replaced binding sat, and the received value flows through the same parameter under the same name. The role's signature and body do not change, and the value has exactly one source.
</task>

<constraints>
1. Replace the value's source only at the binding or argument that configures the role running on it; every other use of the honest expression stays.
2. Keep the parameter's name and type; the role definition and body stay untouched.
3. The role's own checks stay: the attacker selects what the role is configured with, and the role treats it exactly as the protocol prescribes.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- main configures the role with the honest peer key *)
process
  new SKA: skey; new SKB: skey;
  ( !processA(A, SKA, pk(SKB))
  | !processB(B, SKB, pk(SKA)) )

(* after -- the same parameter, its source now a receive sitting where the
   honest expression sat: the attacker selects what A is configured with.
   processA is unchanged; every other use of the honest expression stays *)
process
  new SKA: skey; new SKB: skey;
  ( !(in(c, PKB_input: pkey); processA(A, SKA, PKB_input))
  | !processB(B, SKB, pk(SKA)) )
```
</example>
