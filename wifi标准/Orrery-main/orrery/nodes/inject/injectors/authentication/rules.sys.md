<task>
Inject every Authentication goal from the user message into the complete
ProVerif model.

For each goal, the `subject` raises `begin_<id>` when all fields in `values`
first exist in its local view. The `asserter` raises `end_<id>` when its run
has completed — required checks passed, all protocol messages sent — and the
run's subject is one of the principals `main` instantiates the subject role
for: exactly the designated subject under a fixed assignment, all of them
where `main` runs that role for several. The query requires each end to have
a preceding matching begin.

| subtype | meaning | query |
|---|---|---|
| `aliveness` | the subject ran | `event(end(...)) ==> event(begin(...))` |
| `weak_agreement` | the subject ran with this asserter and the named identities agree | `event(end(...)) ==> event(begin(...))` |
| `non_injective_agreement` | both roles agree on the complete `values` vector | `event(end(...)) ==> event(begin(...))` |
| `injective_agreement` | the complete vector agrees one-to-one across runs | `inj-event(end(...)) ==> inj-event(begin(...))` |

`parties` selects the roles. Event arguments are exactly `values`, in order.
Each role supplies its own local binding for every position.
</task>

<constraints>
1. Give every goal its own `begin_<id>`, `end_<id>`, query, begin call, and end
   call. Use exactly the types and order of `values`.
2. Bind each position to that role's local view: its own value, the value
   received or selected in this run, or its original value when the peer echoes
   it. Negotiated fields use each role's own result.
3. Place begin at the earliest point where the full local vector is available;
   begin carries no guard. Place end after successful protocol completion, at
   the role's tail. A guard's scope holds its end event alone: no protocol
   statement falls inside it.
4. When the run's subject is received or selected during the run, record end
   under a guard comparing it with the stable identities (and credentials,
   where the role carries them) of the principals `main` instantiates the
   subject role for — one disjunct per principal. A subject that is a
   `main`-fixed parameter from that set needs no guard.
5. Treat the actual subject and its stable honest references as separate
   values: a value received or selected in this run never serves as its own
   reference. Pass the stable values already present in `main` as observation
   parameters and update the role definition and every call when needed.
</constraints>

<success_criteria>
- Every goal has one independent event pair and a query matching its subtype.
- Begin and end use the two roles' local views of the same ordered `values`
  vector.
- Honest execution reaches begin before end.
- end fires only for runs whose subject is one of the principals `main`
  instantiates the subject role for.
- Begin is unguarded, and removing every injected event and guard leaves the
  protocol behaviour unchanged.
</success_criteria>

<example>
For `auth_b_to_a`, `subject=B`, `asserter=A`, and `values=[B,A,N]`, on a
scenario model whose `main` runs both roles for A and for B:

```proverif
type host.
type nonce.
free c: channel.

event begin_auth_b_to_a(host, host, nonce).
event end_auth_b_to_a(host, host, nonce).
query b: host, a: host, n: nonce;
  event(end_auth_b_to_a(b, a, n)) ==>
  event(begin_auth_b_to_a(b, a, n)).

let processB(B_self: host, A: host) =
  new N: nonce;
  event begin_auth_b_to_a(B_self, A, N);
  out(c, (B_self, A, N)).

(* main runs the subject role for A and for B, so the accepted subjects are
   exactly those two; HonestA and HonestB are their stable identities, passed
   as observation parameters. With one subject-role instance the disjunction
   is a single comparison. The asserter side carries no guard *)
let processA(A_self: host, HonestA: host, HonestB: host) =
  in(c, (B_run: host, A_recv: host, N_recv: nonce));
  if A_recv = A_self then
    out(c, N_recv);
    if B_run = HonestA || B_run = HonestB then
      event end_auth_b_to_a(B_run, A_self, N_recv).

process
  new A: host;
  new B: host;
  ( !processB(B, A)
  | !processB(A, B)
  | !processA(A, A, B)
  | !processA(B, A, B) )
```
</example>
