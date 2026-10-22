<context>

Protocol: {{ protocol }}

The assumption space read from this document — condition only on the `variable` entries:

{{ assumptions_json }}

The goals read from this document — claim only these ids:

{{ properties_json }}

The flow model extracted from this document — use it only to align the queries above to
the model's exact names and protocol structure:

```proverif
{{ flow_pv }}
```

</context>

Read out the scenarios and the claims, and submit them, with a ```quotes block in the same reply.
{{ step_messages }}
