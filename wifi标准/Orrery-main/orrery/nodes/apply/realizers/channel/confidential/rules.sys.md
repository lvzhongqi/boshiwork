<task>
Encode **channel.confidential** on the directed link named by the target.

The world this builds: the attacker reads nothing of what crosses this link, yet can place content of its own choosing on it. What honest parties send stays hidden; what the receiver accepts can come from anyone.

The shape it takes: the link's channel declaration becomes private, and one replicated forwarder joins the main process's parallel group, reading from the public channel and writing onto the link. Sender and receiver keep using the link under its existing name; whatever the attacker composes on the public channel enters the link through the forwarder.
</task>

<constraints>
1. Declare the target link `[private]`.
2. Add the forwarder `!in(c, x: bitstring); out(<link>, x)` as one branch of the main parallel group.
3. Apply the change to the target direction; the reverse direction keeps its own assumption.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the link is an ordinary public channel *)
free channel_A_B: channel.

process
  ( !processA(...) | !processB(...) )

(* after -- the private declaration hides everything honest parties put on the
   link; the forwarder is the attacker's write path onto it. Both endpoint
   processes keep using the same channel name *)
free channel_A_B: channel [private].

process
  ( !processA(...) | !processB(...)
  | !in(c, x: bitstring); out(channel_A_B, x) )
```
</example>
