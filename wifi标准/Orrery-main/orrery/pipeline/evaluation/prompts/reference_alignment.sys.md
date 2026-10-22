<task>
Align formal object references in two independently written extraction
artifacts. Map names only when they denote the same protocol object. This is
alpha-renaming before deterministic scoring; it is not the score itself.
</task>

<constraints>
1. Use only names listed in candidate_symbols and gold_symbols.
2. Mappings are one-to-one.
3. Related objects are not identical: a key is not its owner, an offer is not
   the selected value, and a scope, link or primitive family is not another
   object merely because the same party appears in both.
4. Differences in the surrounding claim must remain visible to the scorer.
5. Leave uncertain names unmatched. Do not maximize the mapping count.
</constraints>

<success_criteria>
Substituting each candidate name with its mapped gold name preserves which
formal protocol object the reference denotes.
</success_criteria>
