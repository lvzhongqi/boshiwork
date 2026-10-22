<input>
Goals to inject:
```json
{{ goals_json }}
```
</input>

{% if unresolved_json %}
These names do not appear verbatim in the model:
```json
{{ unresolved_json }}
```
Each maps to `{name: [the goals that reference it]}`. The model almost always holds the value: under another spelling, split across several bindings, or inside a tuple with no name of its own. Work out what each one denotes and write the query against the model's actual structure.
{% endif %}
Inject every goal above into the model in the system context, and submit one set of declarations and anchored edits covering all of them.
{{ step_messages }}
