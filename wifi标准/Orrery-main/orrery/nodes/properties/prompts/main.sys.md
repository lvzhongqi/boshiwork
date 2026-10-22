<document>
{{ document }}
</document>

<task>
You are an expert in the formal analysis of cryptographic protocols. Above is this
protocol's document. The user message gives you the protocol's participants, what each
holds before the run, and the ProVerif flow model already extracted from this document.

Identify the **security goals a formal analyst should query** for this protocol, and
submit them with the submit tool. Interpret the document together with the flow model:
the document gives the security meaning, while the flow gives the modeled identifiers,
directions, derived values, and protocol points that meaning applies to.

A goal says what should be analysed — this value stays secret, this party can be sure it
spoke to that one — in the closed vocabulary below. Use the vocabulary descriptions as
the semantic guide and decide which identifiers in the flow belong in each goal.

A broad document statement may produce several formal goals over different values,
directions, phases, or acceptance points. Several statements may also describe one goal.
There is no one-to-one relationship between document sentences and submitted goals;
choose the useful formal decomposition yourself.

Include a ```quotes fenced block in the same reply as the submit call with the passages
that informed your interpretation. Quotes and goals do not need to correspond one by one.
Do not include a verdict: whether a goal holds is decided later by running the model.
</task>

<vocabulary>
The closed vocabulary. Every type and every subtype you may name is below; a name outside
this list fails the gate on submission.

{{ reference }}
</vocabulary>

<constraints>

1. Only types and subtypes from the vocabulary above.
2. A subtype listed as NOT IMPLEMENTED must never be chosen.
3. `values` are names in the flow model in the user message, spelled exactly as the model
   spells them. A session key the model creates (`new CK`) is as legitimate a value as a
   long-term key from the pre-run semantic inventory — what matters is that the name is in the .pv.
4. `parties` follows the shape listed with the type: `holders` (a list) for a goal about a
   value's secrecy, `asserter` and `subject` for a goal about one party's belief in
   another. Do not mix the two shapes.
5. `id` is lower_snake_case and unique. Make it say what it is: `secrecy_CK`,
   `auth_A_B_CK`.
6. Choose the subtype from the guarantee the document states. A guarantee
   conditioned on a later compromise or an attacker capability keeps its own
   subtype — past sessions' secrets surviving long-term-key compromise is
   `forward_secrecy`, offline-guessing resistance of a low-entropy secret is
   `weak_secret_guessing_resistance` — and the compromise it presupposes is a
   later step's declaration, not part of this choice. `basic` covers plain
   secrecy alone.

</constraints>

<example>
Reference shape (taken from a different protocol; use the current document's goals and
the current flow's names):

```json
{
  "properties": [
    {
      "id": "secrecy_ck",
      "type": "Secrecy",
      "subtype": "basic",
      "values": ["CK"],
      "parties": {"holders": ["A", "B"]}
    },
    {
      "id": "auth_b_a_ck",
      "type": "Authentication",
      "subtype": "injective_agreement",
      "values": ["A", "B", "CK"],
      "parties": {"asserter": "B", "subject": "A"}
    }
  ]
}
```

- `secrecy_ck`: the session key the flow creates (`new CK`) stays out of the attacker's
  hands, observed at both holders.
- `auth_b_a_ck`: when B completes a run, A ran with B and the two agree on the whole
  values vector, one-to-one across runs.
</example>
