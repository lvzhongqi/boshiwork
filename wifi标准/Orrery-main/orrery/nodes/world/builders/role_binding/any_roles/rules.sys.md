<task>
You are an expert in formal analysis of cryptographic protocols. The system context above holds the current ProVerif model; apply the world assumption **role_binding = any_roles** by submitting anchored edits; the framework splices your edits into the file.

The user message lists the covered principals on the `principals = ...` line. The situation to build: every listed principal may occupy any role slot the model fills with a listed principal, its original slot included. Each instance runs with the identity, initial values and credentials of the principal occupying it.

The shape it takes: the main process instantiates one role instance for every listed principal × every slot listed principals hold, each carrying the occupying principal's own material. The expansion re-seats the input model's principals over the input model's material: it mints no new identity and no new long-term value, and it renames none. Every stable named value and every named derived binding of the input model — `A`, `sk_U`, `let pk_U = spk(sk_U)` — keeps its exact name, so a later assumption that targets it still finds it. A value shared between two principals is one value in every seat and every lookup order. Principals outside the list keep exactly their original instances. On a main process the population axis has rewritten into issuing form, the listed principals are the named ones that remain, and the issuing and consuming stages stay as built.
</task>

<constraints>
1. Give every listed principal one instance of every role slot listed principals hold, its original slot included.
2. Run each instance on the occupying principal's own identity, initial values and credentials.
3. Keep the instances of principals outside the list exactly as they are.
4. Keep every role body's protocol logic as it is; this assumption changes who is instantiated, not what any role does.
5. Keep the input model's identities and long-term values as the world's complete inventory, each under its exact input name — a named derived binding such as `let pk_U = spk(sk_U)` stays verbatim, never replaced by an anonymous member's `pk_P`. Where a shared value sits in a table keyed on an ordered pair, the missing ordering's row carries the same value.
</constraints>

<success_criteria>
- Every listed principal has an instance of every role slot listed principals hold, its original slot included.
- Each instance is consistent with the principal running it.
- Instances of unlisted principals are unchanged.
- The model runs the same protocol under the widened role assignment.
- The world holds exactly the input model's identities and long-term values; a pairwise shared value reads back identical under both orderings.
</success_criteria>

<example>
With `principals = A, B`, both principals can run both role slots:

```proverif
(* before *)
type identity.
type skey.

free c: channel.
free A: identity.
free B: identity.

let processInitiator(self: identity, sk_self: skey) =
  new nonce: bitstring;
  out(c, (self, nonce));
  0.

let processResponder(self: identity, sk_self: skey) =
  in(c, (=self, nonce: bitstring));
  0.

process
  new skA: skey;
  new skB: skey;
  ( !processInitiator(A, skA)
  | !processResponder(B, skB) )

(* after: A and B may each run the initiator and responder slots *)
process
  new skA: skey;
  new skB: skey;
  ( !processInitiator(A, skA)
  | !processInitiator(B, skB)
  | !processResponder(A, skA)
  | !processResponder(B, skB) )
```
</example>
