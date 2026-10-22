<task>
You are an expert in formal analysis of cryptographic protocols. The system context above holds the current ProVerif model; apply the world assumption **session_multiplicity = single_session** by submitting anchored edits; the framework splices your edits into the file.

The situation to build: the world runs exactly one session per role. This is the one-shot setting — a pairing or provisioning ceremony that happens once — where cross-session interleaving is out of the threat model. The flow model writes unbounded concurrent sessions (a `!` over the session group); this assumption removes that replication.

The shape it takes: drop the `!` in front of the session group in the main process, so each role runs once. The role bodies do not change — only how many times the main process launches them.
</task>

<constraints>
1. Strip only the session group's replication. Every `new`, every role body, every message stays exactly as it is; this assumption is about how many sessions run, nothing else.
2. If the main process has an issuing form (identities handed out on a private channel under their own `!`), that issuing replication is the population axis's, not this one — strip the consuming session group's `!`, never the issuing branch's.
3. Remove the replication, do not gate it. A `phase` or a counter does not make the world single-session; only dropping the `!` does.
</constraints>

<example>
Reference shape (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- unbounded concurrent sessions *)
process
  new K: key;
  !( initiator(A, B, K) | responder(B, A, K) )

(* after -- one session per role; the bodies are untouched *)
process
  new K: key;
  ( initiator(A, B, K) | responder(B, A, K) )
```
</example>
