<task>
Inject every `basic` Secrecy goal by locating the target's binding at each named
holder and querying whether the attacker obtains it.

Each holder is an independent observation point: its local binding takes the
mechanism below, one goal may combine direct queries and witnesses, and every
query carrying one goal id counts into that goal's verdict.

| binding at the observation point | mechanism |
|---|---|
| top-level `free K` | `query attacker(K). (* <goal id> *)` — one query covers every holder |
| `new K` in main | `query attacker(new K). (* <goal id> *)` — one query covers every holder |
| `new K` in this holder's role | the same direct query; a witness when the observation needs an honest-session guard |
| `let` or pattern binding in this holder's role | one witness for this holder |

A binding in a non-holder role is an upstream origin, not an observation point:
observe the value where the named holders hold it.

For each holder observed by witness, add a private
`witness_<id>_<value>_<holder>`, one query, and one output that wraps the witness
under that holder's local target value. Declare a one-way wrapper whose second
argument has the target's actual type:

```proverif
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.
```

Place the witness output after the target is bound and after the holder's final
protocol send.

Decide the goal's session scope once and apply it at every observation point.
When the goal covers only honest sessions, guard every witness output whose role
reads or selects any peer identity or credential during the run: compare those
actual values with the stable honest values from `main`, updating the role
signature and every call as needed. A role whose peers are all `main`-fixed
honest parameters carries no guard. A
goal that also covers attacker-peer runs keeps every witness unguarded.

Put complete declarations and queries in `declarations`. Put witness outputs,
guards, and coordinated role/main rewrites in `edits`. A direct-query comment
contains only the goal id.
</task>

<constraints>
1. Map every target by protocol meaning and use the model's actual name, type,
   scope, and each holder's local binding.
2. Give every witness-observed holder its own witness, query, and output.
   Witness names contain the exact goal id, target name, and holder name.
3. Use one wrapper pair per target type where possible. Declare the constructor
   with `fun`; introduce the destructor in the left side of `reduc`.
4. Let a guard wrap only the witness output. Pass independent stable honest
   references from `main` whenever the role's actual-peer values may vary.
   One goal, one scope: every witness output of a goal applies the same
   scoping rule.
5. Preserve protocol messages, checks, branches, and sends. Preserve the final
   `0.` when an edit replaces a role tail.
</constraints>

<success_criteria>
- Each named holder is observed through the mechanism its local binding takes.
- Every direct query has a trailing `(* <goal id> *)` comment containing only
  the id.
- Every witness uses the correct holder-local value and target type at the end
  of a completed run.
- One goal's witness outputs all apply its session scope: guarded wherever the
  role's peers vary, unguarded only where they are `main`-fixed or the goal
  covers attacker-peer runs.
- Honest-session guards use independent stable references and leave protocol
  behaviour unchanged.
</success_criteria>

<example>
**Direct query.**

```proverif
type key.
free root_key: key [private].
query attacker(root_key). (* secrecy_root_key *)
query attacker(new master_key). (* secrecy_master_key *)

process
  new master_key: key;
  0
```

**A `let`-bound value witnessed without a guard.**

```proverif
type key.
free c: channel.
fun kdf(key): key.
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.

free witness_secrecy_traffic_traffic_key_A: bitstring [private].
query attacker(witness_secrecy_traffic_traffic_key_A).

let processA(seed: key) =
  let traffic_key: key = kdf(seed) in
  out(c, wenc_key(witness_secrecy_traffic_traffic_key_A, traffic_key)).

process
  new seed: key;
  !processA(seed)
```

**A role-body `new` witnessed under an honest-session guard.**

```proverif
type host.
type key.
type skey.
type pkey.
free c: channel.
fun pk(skey): pkey.
fun aenc(key, pkey): bitstring.
reduc forall x: key, sk: skey; adec(aenc(x, pk(sk)), sk) = x.
fun wenc_key(bitstring, key): bitstring.
reduc forall x: bitstring, y: key;
  wdec_key(wenc_key(x, y), y) = x.

free witness_secrecy_session_session_key_A: bitstring [private].
query attacker(witness_secrecy_session_session_key_A).

let processA(peer_run: host, peer_pk_run: pkey,
             peer_honest: host, peer_pk_honest: pkey) =
  new session_key: key;
  out(c, aenc(session_key, peer_pk_run));
  if peer_run = peer_honest then
    if peer_pk_run = peer_pk_honest then
      out(c, wenc_key(witness_secrecy_session_session_key_A, session_key)).

process
  new B: host; new I: host;
  new skB: skey; new skI: skey;
  ( !processA(B, pk(skB), B, pk(skB))
  | !processA(I, pk(skI), B, pk(skB))
  | out(c, skI) )   (* I's key is the attacker's: the second instance runs with
                       an attacker-controlled peer, and the guard is what keeps
                       its witness out of that run *)
```
</example>
