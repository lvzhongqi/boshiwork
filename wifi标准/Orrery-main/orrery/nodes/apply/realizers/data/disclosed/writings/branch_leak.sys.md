<task>
The situation to build: before the run begins, the attacker already holds the long-lived secret `target.of` names — a long-term key, an identifier, a pre-shared value.

The shape: one `out(c, K)` inside the secret's scope, as its own unreplicated branch beside the existing behaviour. No role body changes.
</task>

<constraints>
1. Leak exactly the value `target.of` names, and only it. A shared symmetric key is held by both ends, so leaking it once makes it public for both. Sweeping in other keys the holder carries builds a different, stronger world than the one declared — the declaration names one object.
2. The `out` sits inside the secret's scope.
3. Leak exactly the term `target.of` names, and only it. Output that term; never a value it derives from. When the target names a derived public value (`G_I = exp(g, I)`, a verifier `J(pi)`), leak that value itself (`out(c, G_I)`), never the source it was built from (`out(c, I)`) — leaking the source hands the attacker more than the assumption declares and typically makes the goal false for a reason the scenario never asked. When the target instead names a private key, output that key, not its public counterpart `pk(SK)`, which publishes only what the attacker already holds.
4. Make holder-only helper functions public when possession of the leaked secret enables their computation.
</constraints>

<examples>
<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the main process runs the roles; every long-term key is secret *)
process
  new Ksa: key; new Ksb: key;
  ( !Alice(A, S, Ksa) | !Bob(B, S, Ksb) | !Server(S, Ksa, Ksb) )

(* after -- one unreplicated branch joins the parallel group, inside the key's
   scope. No role body moves: the leak says what the attacker starts with *)
process
  new Ksa: key; new Ksb: key;
  ( !Alice(A, S, Ksa) | !Bob(B, S, Ksb) | !Server(S, Ksa, Ksb)
  | out(c, Ksa) )
```
</example>

<example>
The same object-level assumption on an issuing-form main process (the form produced by the unbounded-population world assumption). Each `skU` is scoped to its own issuing round, so a separate branch cannot name it:

```proverif
(* before -- the issuing branch publishes each identity's public key only *)
!( new U: host; new skU: skey;
   out(c, pk(skU));
   !out(s, (U, skU, pk(skU))) )

(* after -- the private key follows it out, so every issued identity's key is
   in the attacker's hands from the start *)
!( new U: host; new skU: skey;
   out(c, pk(skU));
   out(c, skU);
   !out(s, (U, skU, pk(skU))) )
```
</example>
</examples>
