<task>
You are an expert in formal analysis of cryptographic protocols. The system context above holds the current ProVerif model; apply the world assumption **population = unbounded** by submitting anchored edits; the framework splices your edits into the file.

The situation to build: this axis answers one question — which principals exist. In this world, unboundedly many honest principals exist. The named principals stay: each keeps its identity, its long-term material and its named derived bindings (`let pk_U = spk(sk_U)`) verbatim, and joins the population as a drawable member, so every later declaration that targets a named value still finds it. The issuing stage adds unboundedly many further members beside them, each with its own identity and long-term material. Every ordinary role slot is filled by a drawn member — named or issued — the same member may fill several slots at once (a principal running with itself included), and one member may appear in unboundedly many runs. The attacker is outside the population. Principals the protocol distinguishes as infrastructure — a server every run contacts, an authority — stay named outside the draw, and per-member material they hold (a shared-key entry) is created with the member. A named value reaches the attacker only through the data axis's own declarations, applied downstream; this stage publishes only its issued members' public parts. Who may play which role and how many sessions run are the other two world axes' questions; this one leaves them as they are.

The resulting model form: the named principals keep their bindings in `main` and each hands its own tickets out on a private channel, the hand-out replicated. Beside them, an issuing stage — under replication — creates one further member per round, publishes the public part on the public channel, and hands the member out on the same private channel, its hand-out replicated too. The consuming stage draws one member per ordinary role slot and runs those role instances on the drawn material. Members travel only on the private channel; that is what keeps every member honest.
</task>

<constraints>
1. Replicate the issuing stage and every member's hand-out, the named principals' hand-outs included. A hand-out is a role slot: unbounded hand-outs let one member fill any number of slots at once, which is where self-pairing comes from, and ProVerif reconstructs an attack trace by consuming one `out` per use, so the hand-out replication is what keeps every trace constructible.
2. Keep every named principal's stable values and named derived bindings verbatim, under their exact names; the draw adds members, it renames nothing.
3. Run one unreplicated instance per ordinary role slot in the consuming stage; how many sessions a drawn combination runs is `session_multiplicity`'s question.
4. Keep secrets on the private channel and public material on the public channel: long-term private keys and pre-shared secrets travel only on the private hand-out channel; identities, public keys and credentials the document treats as public keep their `out(c, …)`.
5. Keep every role body's protocol logic as it is. This assumption changes where identities and long-term material come from; adjust a role's signature only where a named constant becomes a parameter.
</constraints>

<example>
Reference shape for a two-slot protocol — one draw per ordinary role slot (taken from a different protocol; follow the structure and position, use the names of the current model):

```proverif
(* before -- two named principals, one fixed pairing *)
process
  new A: host; new B: host;
  new skA: skey; new skB: skey;
  ( !initiator(A, B, skA, pk(skA), pk(skB))
  | !responder(B, A, skB, pk(skB), pk(skA)) )

(* after -- the named principals stay, bindings verbatim, each handing its own
   tickets out on the private channel; the issuing stage adds unboundedly many
   further members beside them; the consuming stage draws one member per role
   slot. Both draws may take the same member -- a principal running with
   itself *)
free s: channel [private].

process
  new A: host; new skA: skey; let pkA = pk(skA) in
  new B: host; new skB: skey; let pkB = pk(skB) in
  ( !out(s, (A, skA, pkA))
  | !out(s, (B, skB, pkB))
  | ( !new U: host; new skU: skey; let pkU = pk(skU) in
        out(c, pkU);
        !out(s, (U, skU, pkU)) )
  | ( !in(s, (X: host, skX: skey, pkX: pkey));
        in(s, (Y: host, skY: skey, pkY: pkey));
        ( initiator(X, Y, skX, pkX, pkY) | responder(Y, X, skY, pkY, pkX) ) ) )
```
</example>
