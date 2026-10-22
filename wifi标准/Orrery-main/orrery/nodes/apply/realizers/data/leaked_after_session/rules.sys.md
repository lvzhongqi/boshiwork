<task>
The situation to build: the sessions run to completion first, and only afterwards does the named long-lived secret reach the attacker. The compromise is real but late — every message of every session was exchanged while the key was still secret, and the attacker gets the key with all of those transcripts already in hand. This is the forward-secrecy setting: a device seized after the fact, a key extracted from a decommissioned server, an archive decrypted years later.

The shape it takes: `phase` divides the main process in time — everything in the other branches runs in phase 0 as normal protocol execution, and the attacker obtains the key only behind the phase boundary the target names (`phase <N>`, 1 when it names none). The leak is one `out(c, K)` inside the key's scope, as its own unreplicated branch beside the existing behaviour. A parallel composition cannot be followed by a sequential tail, so the leak is always a branch within the group, never a step after it.

The query that asks the forward-secrecy question needs a phase qualifier of its own; that belongs to the goal-injection step, not to this one.
</task>

<constraints>
1. Put the leak behind `phase <N>`, `<N>` the phase the target names, 1 when it names none. An `out(c, K)` with no phase builds `data.disclosed`, a different assumption.
2. Add exactly the one value `target.of` names. The declaration names one long-term secret, and sweeping in other keys the holder carries on your own initiative builds a stronger world than the one declared.
3. A phase-1 leak already present in the model is **another declaration's**, applied before this one, and both are meant to hold. Leave it where it is and put yours beside it. Removing it withdraws an assumption this run was asked to make, and nothing downstream can tell: the model still typechecks, the solver still returns verdicts, and those verdicts describe a milder world than the one declared.
</constraints>

<examples>
<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the main process runs the roles; nothing ever leaks *)
process
  ( !roleA(skA, pkB) | !roleB(skB, pkA) )

(* after -- one unreplicated branch joins the parallel group, and `phase 1`
   puts it after the sessions. Everything else runs in phase 0 as before *)
process
  ( !roleA(skA, pkB) | !roleB(skB, pkA)
  | phase 1; out(c, skA) )
```
</example>

<example>
A phase-1 branch is already in the model. It carries another declaration's leak — this
run states one per long-term secret — so it grows rather than changes; here
`target.of` is `skB`:

```proverif
(* before -- skA's leak is already applied *)
  ( !roleA(skA, pkB) | !roleB(skB, pkA)
  | phase 1; out(c, skA) )

(* after -- skB joins it; skA's output stays exactly where it was *)
  ( !roleA(skA, pkB) | !roleB(skB, pkA)
  | phase 1; out(c, skA); out(c, skB) )
```
</example>

<example>
The same object-level assumption on an issuing-form main process (the form produced by the unbounded-population world assumption). Each `skU` is scoped to its own issuing round, so a separate branch cannot name it:

```proverif
(* before -- the issuing branch publishes each identity's public key only *)
!( new U: host; new skU: skey;
   out(c, pk(skU));
   !out(s, (U, skU, pk(skU))) )

(* after -- the private key follows, behind a phase boundary, so it reaches the
   attacker only once the sessions of phase 0 have run *)
!( new U: host; new skU: skey;
   out(c, pk(skU));
   ( !out(s, (U, skU, pk(skU)))
   | phase 1; out(c, skU) ) )
```
</example>
</examples>
