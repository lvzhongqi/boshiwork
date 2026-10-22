<context>
Protocol: {{ protocol }}
Scenario: {{ scenario }}

The assumptions this scenario runs under:
{{ assumptions }}

The goal that does not hold:
{{ goal }}
{% if replay %}
The solver reported a replay: the injective form of this goal fails while the non-injective form holds.
{% endif %}
</context>

<input>
{{ script }}
</input>

Explain this attack and submit the explanation.
{{ step_messages }}
