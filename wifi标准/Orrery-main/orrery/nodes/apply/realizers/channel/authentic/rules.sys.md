<task>
Encode **channel.authentic** on the directed link named by the target.

The world this builds: every message the receiver accepts from this link was sent on it by the named sender — origin and content are settled. The attacker reads everything that crosses the link and places nothing on it; forgery and replay are both outside this world.

The shape it takes: the link's channel declaration becomes private, and a public copy on `c` follows every send on the link. Sender and receiver keep using the link under its existing name.
</task>

<constraints>
1. Change the target channel declaration to private.
2. Follow every `out(<link>, m)` with `out(c, m)`.
3. Apply the change to the target direction; the reverse direction keeps its own assumption.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the link is an ordinary public channel, and the sender just sends *)
free channel_A_B: channel.

let processA(A: host, B: host, SKA: skey, PKA: pkey, PKB: pkey) =
  new I_A: bitstring;
  out(channel_A_B, aenc((I_A, A), PKB));
  ...

(* after -- the channel is private, so the attacker cannot write to it, and a
   public copy follows every send on the link, so the attacker still reads it *)
free channel_A_B: channel [private].

let processA(A: host, B: host, SKA: skey, PKA: pkey, PKB: pkey) =
  new I_A: bitstring;
  out(channel_A_B, aenc((I_A, A), PKB));
  out(c, aenc((I_A, A), PKB));
  ...

(* the receiver is untouched: it goes on reading the same channel name *)
let processB(B: host, A: host, SKB: skey, PKB: pkey, PKA: pkey) =
  in(channel_A_B, msg1: bitstring);
  ...
```
</example>
