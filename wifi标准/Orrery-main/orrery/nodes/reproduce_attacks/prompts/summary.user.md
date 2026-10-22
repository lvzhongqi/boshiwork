<context>
Protocol: {{ protocol }}
{% if pending %}
{{ pending }} further false cell(s) have not been replayed yet and are not part of this summary.
{% endif %}
</context>

<input>
{{ cells }}
</input>

Group these failures by the problem behind them and submit the summary.
