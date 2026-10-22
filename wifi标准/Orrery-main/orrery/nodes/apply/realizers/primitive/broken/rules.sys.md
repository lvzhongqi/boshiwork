<task>
The situation to build: the cryptographic object `target.family` names fails outright — the attacker holds a capability the object's ideal behaviour rules out, with no downgrade or negotiation involved. First identify which kind of object it is in this model; each kind has its own shape, and exactly one applies:

- **A Diffie-Hellman family**: add a `[private]` inverse `reduc` as the destructor's declaration and a parallel attack process that emits a Broken event and answers inversion queries.
- **A KEM family**: the same idiom — a `[private]` inverse `reduc` recovering a KEM private key from its public key, with no same-named `fun`, and an event-gated attack process answering inversions.
- **A low-entropy value** (a password, a PIN): the attacker can enumerate its space offline. The attacker does not receive the value; what changes is that "the attacker cannot name it" stops being true by fiat, and the analysis must ask whether a transcript lets a guess be *verified*. The edit is structural: the value becomes a top-level `free <name>: <type> [private].` declaration — the form ProVerif's offline-guessing analysis (`weaksecret`) works on. If the main process mints it with `new`, move the binding to the top-level private free and delete the `new`; every use keeps the existing name. Where replication mints the value once per member, hoist one distinguished member's binding to the top-level free and leave the other members drawing fresh values. The `weaksecret` query itself is the goal-injection step's business, not yours.
</task>

<constraints>
1. For a DH or KEM family, the inverse is `[private]` and reached only through the attack process. Declared public, it becomes an unconditional destructor and the world stops being able to distinguish "broken" from "never ideal in any run" — the event gates nothing.
2. For a DH or KEM family, emit the Broken event inside an independent attack-process branch before answering.
3. For a low-entropy value, change where the value is bound, never how it is used: same name, same type, every use untouched; the declaration keeps `[private]` (dropping it is a leak assumption, not a guessability one); no query, no `weaksecret`, no event.
4. The `reduc` is the inverse symbol's unique declaration.
</constraints>

<success_criteria>
1. The attacker can invoke the named family's inversion only through the added attack process, after its Broken event.
2. Each inverse symbol is introduced exactly once, by its `[private]` reduction rule, with no same-named `fun` declaration.
3. Protocol roles and ideal equations are unchanged; only the broken-family oracle or the low-entropy binding is added.
</success_criteria>

<examples>
<example>
A broken DH family (the Signal-PQXDH idiom; use the names of the current model — the KEM case is the same shape with `inversePK(kempk(s)) = s` and a `BrokenKEM` event):

```proverif
const G: element [data].   (* the group generator is a constructor: a `free` name cannot appear in rewrite rules *)

reduc forall s: scalar; discreteLog(SMUL(s, G)) = s [private].

event BrokenDH.
let dh_attacks() =
  in(c, p: element);
  event BrokenDH;
  out(c, discreteLog(p)).

process
  ( ...protocol roles... )
  | !dh_attacks()
```
</example>

<example>
A guessable password, hoisted for the offline-guessing analysis:

```proverif
(* before -- the password is minted inside the main process *)
process
  new pwd: bitstring;
  ( !processUser(U, pwd) | !processServer(S, pwd) )

(* after -- the same name, hoisted to a top-level private free declaration;
   uses are untouched, and the goal side may now ask weaksecret pwd *)
free pwd: bitstring [private].

process
  ( !processUser(U, pwd) | !processServer(S, pwd) )
```
</example>
</examples>
