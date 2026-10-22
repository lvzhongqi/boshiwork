<task>
Inject the single `Privacy.unlinkability` goal as a ProVerif biprocess.

Run the same protocol twice. In the left projection, both selected sessions use
the original subject. In the right projection, the first uses the original
subject and the second uses a fresh alternative subject of the same type. Apply
the same choice consistently to every identity and long-term credential that
represents each entry in `parties.subjects`.

Put alternative-subject declarations in `declarations`. Put the biprocess main
rewrite and the exact marker `(* @orrery-unlinkability <goal id> *)` in `edits`.
The observational-equivalence result is the goal's verdict.
</task>

<constraints>
1. Build one two-session biprocess for this goal. The projections differ only
   in ownership of the selected second session.
2. Place `choice[original,alternative]` on subject-bearing role/session
   arguments and their coherent long-term credential tuple.
3. Give each alternative subject private top-level names of the required types;
   every introduced name contains the exact goal id.
4. Keep public messages, fresh session values, role bodies, cryptographic
   operations, checks, channels, and scenario assumptions identical across the
   projections.
5. Add the exact goal marker once. The model uses observational equivalence and
   contains no reachability query for this goal.
</constraints>

<success_criteria>
- The model has one goal marker and a non-degenerate `choice[left,right]`.
- Both projections run the same protocol twice and differ only in the selected
  second session's subject.
- Every subject identity and identity credential switches coherently.
</success_criteria>

<example>
```proverif
free alternate_unlink_alice: host [private].

(* @orrery-unlinkability unlink_alice *)
process
  ( Session(A)
  | Session(choice[A, alternate_unlink_alice]) )
```
</example>
