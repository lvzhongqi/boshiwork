<context>

Protocol: {{ protocol }}

Semantic principals and pre-run values (descriptions are evidence, not a ready-made
ProVerif signature):

{{ knowledge_json }}

Declaration reference:

{{ reference }}

</context>

<input>
# Scaffold (channels and the honest-run probe are fixed; fill declarations, every role,
# and the main process at their markers)
```proverif
{{ template }}
```
</input>

Complete the template and submit the full .pv; the framework checks it on submission and returns the findings.
{{ step_messages }}
