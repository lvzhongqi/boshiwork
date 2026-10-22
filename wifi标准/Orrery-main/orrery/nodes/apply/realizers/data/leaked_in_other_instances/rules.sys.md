<task>
The situation to build: other sessions of this protocol have already finished and given up their copies of the named per-session value — a session key together with the credentials that session produced, or an intermediate state read out of memory — and the attacker holds those copies. Every running session's own copy must still meet its goals. This is the known-key / state-reveal setting: keys of past runs recovered by cryptanalysis, state lifted from a swapped-out process.

The shape it takes: one `!`-replicated leftovers process joins the main process's parallel group; everything already there, the session group's replication included, stays as it is. Each round the leftovers process creates a value of the same kind as the one `target.of` names, publishes it, and publishes the credential the protocol wraps that value in — the same message shape, under the model's own long-term keys. It runs no protocol steps and reads from no channel: what a finished session leaves behind is a value and a credential, nothing live.
</task>

<constraints>
1. Build the leftovers as a standalone process that only creates and outputs: no protocol step, no channel read, no `phase`.
2. Build each leftover from the model's own material: the same long-term keys, the same credential and message shapes.
3. Keep the existing main process as it is, the session group's replication included; the leftovers branch is the only change.
</constraints>

<example>
A session key, with the ticket its session produced (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- the main process runs one replicated session group *)
process
  !( Alice(A, B) | Bob(A, B) | Server(A, B) )

(* after -- the replicated leftovers process joins the group; the session
   group itself is untouched. The ticket line, sealed under the model's own
   KB, is what carries the leak's force: a value the protocol binds to
   nothing would hand the attacker nothing it lacks *)
let otherSessionLeftovers(A: host, B: host, KB: key) =
  new CK_old: key;
  out(c, CK_old);                    (* the finished session's key *)
  out(c, senc((CK_old, A), KB));     (* its ticket -- B cannot tell old from new *)
  0.

process
    !( Alice(A, B) | Bob(A, B) | Server(A, B) )
  | !otherSessionLeftovers(A, B, KB)
```
</example>
