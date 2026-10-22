<task>
The situation to build: the negotiation space of the family `target.family` names contains a weak member the protocol may still legitimately select. When a session picks it, that family's characteristic guarantee is void; when a session picks the strong member, everything holds as before. The attacker's route to the weak member is the negotiation itself — on the public network it can steer or tamper with the offered parameters, so "the negotiated value can be tampered with" is this assumption exercised through the ordinary network, not a separate one.

One idiom for every family (the TLS-lib shape), three pieces:
1. Declare an algorithm type with a Weak and a Strong constant for the family.
2. Make the primitive algorithm-parameterised: the strong branch keeps the ideal behaviour; the weak branch carries the family's characteristic failure —
   - **hash** (SLOTH): the weak member's output collides — `hash(WeakHash, x) = collision` for a single `const collision`, while `hash(StrongHash, x)` stays ideal.
   - **DH group** (Logjam): weak-group exponentiation returns a fixed predictable element — `dh_exp(WeakDH, e, x) = BadElement`, strong stays ideal.
   - **AEAD** (Lucky13/RC4 class): the weak member is malleable and leaky at once — a `aead_forged(p, aead_enc(WeakAE, ...))` that still decrypts to `p`, and an `aead_leak(aead_enc(WeakAE, k, n, ad, x)) = x` destructor.
   - **PKE** (Bleichenbacher/DROWN): the weak decryption succeeds on attacker-shaped input where the strong one fails, handing the attacker an oracle.
   - a family with a different failure follows the same split: strong = ideal, weak = that family's documented break.
3. Thread the negotiated algorithm through each existing call of the primitive, and emit an event (`event ServerChoosesHash(..., h)` or the model's analogue) where the session selects it, so the goal side can name the weak choice as its allowed exception. A model that carries no negotiated-algorithm value gets one here: the selecting role receives the algorithm from the network before its first use (`in(c, halg: hash_alg)`) — the network is the negotiation surface — and the same threading and event apply.
</task>

<constraints>
1. The weak member is reachable by negotiation, not forced. Both constants exist and a session may pick either; hard-wiring the weak member everywhere tests a broken protocol, not an agile one with a weak option — that world is `primitive.broken`.
2. Only the weak branch fails. The strong branch keeps the ideal behaviour; collapsing both erases the distinction the assumption is about.
3. Emit the choice as an event where the algorithm is selected. The goal side keys its exception disjunct on that event; omit it and a `true` verdict cannot carry the "or the session chose the weak member" reading.
</constraints>

<example>
Reference shape for a hash family (the TLS13-lib idiom; use the names and the family of the current model):

```proverif
(* before -- an ideal hash *)
fun hash(bitstring): bitstring.
...
  let th = hash(transcript) in ...

(* after -- an agile hash with a colliding weak member *)
type hash_alg.
const StrongHash, WeakHash: hash_alg [data].
const collision: bitstring [data].
fun hash_ideal(bitstring): bitstring.
fun hash(hash_alg, bitstring): bitstring
reduc forall x: bitstring; hash(WeakHash, x) = collision
otherwise forall x: bitstring; hash(StrongHash, x) = hash_ideal(x).
...
  let th = hash(h, transcript) in ...      (* h is the negotiated algorithm *)
  event ServerChoosesHash(cr, sr, h);
```
</example>
