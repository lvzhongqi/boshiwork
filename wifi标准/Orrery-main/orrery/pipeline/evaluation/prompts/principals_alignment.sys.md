<task>
Align the names in two independently written formal initial-knowledge models.
Map a candidate name to a corpus name only when both denote the same formal
principal or the same formal value. This is alpha-renaming, not a judgement of
whether the candidate is correct.
</task>

<constraints>
1. Mappings are one-to-one. A name may occur in at most one pair.
2. Related values are not necessarily identical. An algorithm configuration is
   not the selected algorithm; an input is not its derived output; a certificate
   or trust anchor is not the public key it authenticates.
3. Preserve dependency categories: an independent value maps to an independent
   value; a derived value maps to a derived value.
4. A derived value and every source named by its `derived_from` edge must be
   mapped together. The mapped sources must be exactly the corpus value's
   sources. The relation's cryptographic meaning comes from the descriptions.
5. Description wording may differ and does not prevent a name mapping. Use it
   as evidence about what the value means.
6. Leave a name unmatched when the evidence does not establish identity. Do
   not map merely to maximize the number of pairs.
</constraints>

<success_criteria>
Every mapping is a defensible statement that the two names can be substituted
for one another without changing what formal value the model denotes.
</success_criteria>
