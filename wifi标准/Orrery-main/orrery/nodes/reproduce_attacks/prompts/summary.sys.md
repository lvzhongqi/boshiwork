<task>
An automatic analysis replayed the attacks behind several failed security goals of one protocol and explained each one. You are given the conclusion written for each of those cells. Write the summary a reader sees first: which problems these failures come down to, and which cells each problem covers.

Submit:

- `groups`: one entry per distinct problem, with the cells it covers.
- `summary`: a short paragraph over all the groups.
</task>

<constraints>
1. Every cell in the input belongs to exactly one group; name cells exactly as the input names them.
2. Put cells in one group only when their conclusions describe the same weakness, for example the same message that does not name its recipient, or the same key handed to the attacker.
3. Keep a failure that rests on the protocol's own messages or checks apart from one that follows from a value the scenario handed the attacker, and say which is which.
4. Use only what the conclusions say.
</constraints>

<success_criteria>
- Every input cell appears in exactly one group, and no group names a cell the input does not have.
- Each group states one problem in a sentence a reader can act on.
- The summary says how many problems there are and which of them rest on the protocol itself.
</success_criteria>
