<document>
{{ document }}
</document>

<task>
Extract the protocol's semantic principals and the initial knowledge that exists before
a protocol run. Submit two lists:

- `principals`: parties whose honest behaviour, provisioning, registry, or credential
  service belongs to the protocol model;
- `values`: important pre-run identities, symmetric or asymmetric keys, credentials,
  verifiers, and provisioned parameters. Each value has one stable record.

This is a document-level factual inventory, not a ProVerif model. Each value gives a
stable name, a complete semantic description, and `derived_from`: the other listed
values on which it deterministically depends. The flow node later uses this information
to decide types, constructors, role parameters, tables, initialisation, and how each
party obtains and uses the value.

In the same reply as the submit call, include a ```quotes fenced block containing the
document passages that support the extraction.
</task>

<constraints>
1. When the document supplies a symbol, copy it verbatim. Otherwise choose a concise
   identifier made of letters, digits, and underscores, preferably
   `<purpose>_<principal>`.
2. Put both halves of every asymmetric key in `values`. Set a public or verification
   key's `derived_from` to its corresponding private key. State in the description
   whether it is used for encryption, signatures, DH, KEM, or another purpose.
3. Use `derived_from` only for deterministic dependencies that every formal encoding
   must preserve. It records dependency, not a relation kind or ProVerif constructor.
   List every required source; use an empty array for an independent value.
4. In the description, state what the value means, its protocol purpose, where the
   document places or configures it before the run, and how other parties obtain it.
   Where the document distinguishes them, distinguish preconfiguration, session input,
   local lookup, remote query, derivation, and receipt in a protocol message. If the
   document does not determine the acquisition method, state the uncertainty instead of
   guessing.
5. Do not output `type`, `public`, holder, owner, keypair, relation-kind, or
   derivation-kind fields. Attacker knowledge is outside this artifact; public baseline
   facts are extracted downstream as fixed data assumptions.
6. Algorithms, hashes, ciphers, group generators, and ambient mathematical parameters
   are not values held by a party and do not belong in `values`; the flow node declares
   cryptographic primitives. An algorithm or format identifier that the document
   associates with a value is still an algorithm identifier: record the association in
   that value's description, not as a value of its own.
7. Leave out nonces, ephemeral secrets, offers, selected negotiation results, traffic
   keys, and other values first generated, received, or computed during a protocol run.
   When needed to avoid ambiguity, explain the origin of such run-time values in the
   description of the related pre-run value.
8. Do not infer symmetric pre-run knowledge from role names. If one party selects its
   peer before the first message while that peer learns the sender's identity from the
   message, preserve that distinction in the descriptions.
9. Do not list the attacker as a principal. Include only parties that execute protocol
   behaviour or form an independent identity, trust boundary, registry, or credential
   service; do not list a transparent relay with no independent identity or state.
</constraints>

<success_criteria>
- Every actual protocol principal has one principal record.
- Every important pre-run value has one value record and a unique stable name.
- Every public/private, verifier/source, certificate/input, or other deterministic
  dependency is represented by `derived_from` and explained in the description.
- Descriptions preserve the document's acquisition and storage facts without choosing a
  ProVerif representation.
- No run-time intermediate value, cryptographic primitive, or formal-modelling field
  appears.
</success_criteria>
