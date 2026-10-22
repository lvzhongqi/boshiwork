```proverif
{{ pv }}
```

{{ rules }}

<encoding_freedom>
The realizer rules define the resulting world rather than a fixed ProVerif
shape. Read the complete model and use any coordinated edits needed across
declarations, role definitions and bodies, helper processes, tables, channels,
and the main process. Preserve the stated semantic boundary and unrelated
protocol behaviour. Examples illustrate meaning; the current model determines
the implementation.
</encoding_freedom>

<batch_contract>
All inputs in this call are fixed data assumptions with the same subtype and the same
writing. Encode every input in one combined edit set. Compatible changes may share one
branch or declaration block, but no input may be omitted and no value outside the list
may be changed. The writing rules describe one `target.of`; apply those rules separately
to each listed target. Thus "one value" means one value per assumption, not one value for
the whole batch.
</batch_contract>
