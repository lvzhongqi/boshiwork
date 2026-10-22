<context>
Protocol: {{ protocol }}

Run-wide world (apply once, before object-level assumptions):
```json
{{ world_json }}
```
</context>

<input>
Scenario: `{{ scenario_name }}`

Complete object-level assignment for this scenario:
```json
{{ scenario_json }}
```

Security goals to verify:
```json
{{ properties_json }}
```

Goal ids: {{ goal_ids }}
</input>

Construct the final model for exactly this world and scenario, using flow defaults only
where no selected rule overrides them; submit the complete `.pv` in exactly one
```proverif block with independently attributable queries for every goal id.
