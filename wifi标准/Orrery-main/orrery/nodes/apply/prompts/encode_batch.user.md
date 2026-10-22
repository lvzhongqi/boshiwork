<input>
Fixed data assumptions in this batch:
{{ assumptions_json }}

The declaration and the model may spell a name differently. Map each target by meaning,
then use the model's notation in both `coverage.model_term` and the edits.
</input>

Encode the complete batch on the model in the system context. Submit one coverage row per
assumption id and one combined anchored edit set. Quote the original model line(s) each
edit attaches to; the framework splices the edits and runs the checks.
{{ step_messages }}
