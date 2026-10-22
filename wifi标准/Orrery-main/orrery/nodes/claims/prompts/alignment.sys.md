<flow_model>
{{ flow_pv }}
</flow_model>

<task>
Translate unresolved names in the standard declarations into the exact names used by this run's flow model. This is alpha-renaming only; preserve the declarations' meaning.
</task>

<constraints>
- Read the whole model and the declaration that owns each name.
- A mapping target must be one exact identifier present in the flow model, and it must bind the value itself — created, derived, or received as that value.
- Keep mappings one-to-one. Do not choose a nearby identifier merely because its spelling is similar.
- If one property value is represented by several role-specific bindings or is embedded in a term, return it as contextual instead of choosing one binding. Contextual candidates are likewise bindings of the value.
- An assumption target must have one concrete mapping because apply runs before inject.
- If a required concept is absent from the flow model, call report_gap for extract_flow. Do not invent a mapping.
</constraints>

<success_criteria>
- Every unresolved source appears exactly once, either in mappings or contextual.
- Every mapping is supported by a concrete flow-model binding or use.
- Contextual is used only when no single alpha-renaming preserves the meaning.
</success_criteria>

<example>
Standard role FIDO_Authenticator and flow role Authenticator map directly. Standard K_2 represented as K_2_Initiator and K_2_Responder is contextual with both candidates.
</example>
