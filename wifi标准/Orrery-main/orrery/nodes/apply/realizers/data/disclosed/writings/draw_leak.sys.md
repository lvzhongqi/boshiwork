<task>
The situation to build: the random value the target names reaches the attacker the moment it is drawn — a broken or backdoored generator, coins logged by a compromised runtime. The attacker holds the term itself, from before its first use.

The shape it takes: in the holder's role body, immediately after the `new <name>` that draws the value, insert `out(c, <name>);`. Nothing else moves: the role keeps using the value exactly as before, and the protocol's own messages are untouched.
</task>

<constraints>
1. The leak sits directly after the `new`, before the value's first use. Placed later, the attacker learns the value only after the protocol has already committed to it, which is a weaker assumption (a post-hoc log, not a broken RNG).
2. Leak exactly the named value. Its derivatives and the messages built from it are the protocol's own outputs; adding them changes the message flow.
3. The extra `out` is an insertion, not a rewrite: every existing line of the role stays.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before *)
let processA(A: host, B: host, K: key) =
  new Na: nonce;
  out(c, senc((Na, A), K));
  ...

(* after -- the draw leaks at once; everything else stands *)
let processA(A: host, B: host, K: key) =
  new Na: nonce;
  out(c, Na);
  out(c, senc((Na, A), K));
  ...
```
</example>
