<run_state>
This is the run as it stands right now, read from disk for this message. It is a summary, not evidence: cite an artifact, a session or the document, never this block.

- run: {{ run_name }} | protocol: {{ protocol }}{% if subprotocol %} (sub-protocol {{ subprotocol }}){% endif %}
- status: {{ status }}{% if status == "running" %} — the pipeline is still writing to this directory, so a missing artifact may mean "not yet" rather than "wrong"{% elif status == "check_failed" %} — a step ran to the end and its check said no (the cross-check against ground truth disagreed); that step's artifacts are on disk, and the steps after it never ran{% elif status == "failed" %} — a step could not finish, so the run stopped there; the steps after the failure never ran, so what they would have produced is absent, not empty{% endif %}
{% if from_node %}- re-entered from: {{ from_node }} (the steps before it were kept from the earlier attempt)
{% endif %}- steps: {{ steps }}
{%- if scenarios %}

Scenarios and their verdicts:
{% for line in scenarios %}- {{ line }}
{% endfor %}{%- endif %}
{%- if answers %}

Final answers (results.json): {{ answers | join(", ") }}
{%- endif %}
{%- if gaps %}

{{ gaps }}
{%- endif %}
{%- if facts %}

Messages already filed for this run's steps (step (source): text):
{% for line in facts %}- {{ line }}
{% endfor %}Do not propose a fix that repeats one of these; say it was asked for already and report what that step did with it.
{%- endif %}
{%- if sessions %}

Sessions readable with read_transcript / read_prompt:
{% for name in sessions %}- {{ name }}
{% endfor %}
{%- endif %}
</run_state>
