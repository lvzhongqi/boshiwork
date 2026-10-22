<task>
You are an expert in formal analysis of cryptographic protocols. The system context above holds one complete ProVerif scenario model. The user message contains one `weak_secret_guessing_resistance` goal. Inject ProVerif's offline-guessing query for every value named by that goal.

This goal asks whether the public transcript gives the attacker a successful offline test for a low-entropy secret. It is not ordinary derivability: a private password can satisfy `query attacker(password)` while its transcript still reveals enough to test guesses. ProVerif asks the intended question with `weaksecret password.`

The low-entropy assumption has already represented each target as a top-level
private `free` name. Submit one complete `weaksecret <value>.` declaration for
each goal value. This goal needs declarations only.
</task>

<constraints>
1. Resolve each goal value by meaning and use its exact model name.
2. Add exactly one `weaksecret <value>.` per `values` entry, using its existing
   top-level private `free` binding.
3. Put every statement in `declarations` and submit an empty `edits` list.
</constraints>

<success_criteria>
- Every goal value has exactly one `weaksecret` statement using the corresponding top-level private free name.
- `edits` is empty and no protocol behaviour changes.
</success_criteria>

<example>
```proverif
free password: bitstring [private].
weaksecret password.
```

Submit `weaksecret password.` in `declarations` and an empty `edits` list.
</example>
