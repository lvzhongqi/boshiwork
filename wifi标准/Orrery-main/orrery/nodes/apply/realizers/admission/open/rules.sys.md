<task>
Encode **admission.open** for `target.scope` in the complete ProVerif model.

The attacker obtains its own legitimate participation information for this
scope. Read the whole model and connect its producers, credentials, bindings,
checks, role execution, and every consumer through the model's existing
recognition semantics.

The attacker plays its own protocol moves from the public network with the
material it holds; honest role instances run for honest principals and may
select or accept the attacker's participant as a peer.
</task>

<constraints>
1. Open the complete producer-to-consumer capability for `target.scope`.
2. Give the attacker fresh identities, credentials, and secrets of its own.
3. Keep format, cryptographic-validity, and binding checks in the recognition path.
4. Extend declarations, roles, helpers, registration, and main invocations wherever
   the attacker's legitimate participant must be selected or accepted as a peer.
   Every role instance in `main` keeps running for an honest principal; the
   attacker's own moves come from the network.
5. Make the capability available with the model's session multiplicity.
</constraints>

<success_criteria>
1. The attacker can construct or obtain a complete set of its own participation information that passes the target scope's actual admission logic.
2. Every consumer in the target scope recognises that information through the same logic it uses for legitimate honest information.
3. Named honest participants retain their original information.
4. Honest roles can run with the attacker-owned participant wherever the target
   scope permits a peer to be selected.
5. Every role instance in `main` runs for an honest principal; the attacker's
   participation happens through the network with its own recognised material.
</success_criteria>

<example>
These examples illustrate registry, credential-issuance, and combined
producer/consumer mechanisms.

**Registry.** A closed model contains honest rows and consumers read them:

```proverif
table recognised(host, key).
...
insert recognised(A, KA);
insert recognised(B, KB);
(...)
```

Open admission can add a replicated intake for an attacker-controlled row while leaving the honest rows and existing `get` consumers intact:

```proverif
insert recognised(A, KA);
insert recognised(B, KB);
( ...
| (! in(c, (attacker_id: host, attacker_key: key));
     if attacker_id <> A && attacker_id <> B then
       insert recognised(attacker_id, attacker_key)) )
```

**Certificate issuance.** If consumers already accept any correctly signed subject/key binding, open admission can add an issuer path for an attacker-chosen subject and public credential under the existing trusted authority. The authority secret remains private, and the attacker receives only the resulting valid credential.

```proverif
| (! in(c, (attacker_id: host, attacker_pk: pkey));
     if attacker_id <> A && attacker_id <> B then
       out(c, cert(attacker_id, attacker_pk, caSK)))
```

**Combined producer and consumer gates.** A model may issue a valid credential but still restrict its subject to one named honest value:

```proverif
let (cert_id, cert_pk) = validate_certificate(cert_recv, trusted_root) in
if verify(payload_signature, cert_pk) = payload then
let (payload_id, rest) = payload in
if cert_id = payload_id then
if payload_id = HonestID then
  accept
```

Open admission may require both issuing an attacker-owned valid credential and opening the named-subject admission gate. It keeps certificate validation, signature verification, and `cert_id = payload_id`; only the restriction that makes valid participation exclusive to `HonestID` is changed. If the model has additional acceptance checks, preserve them unless they themselves define the closed admission set.
</example>
