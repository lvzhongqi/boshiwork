"""Result-side checks on model output format: valid JSON, and conformance to a
declared json_schema.

They run whether the connection is direct or relayed, so a relay that silently
dropped the structured-output parameters yields an explicit error instead of a
wrong answer. Repair rounds belong to the agent loop, not here.
"""
import json
import re

import jsonschema


class OutputFormatViolation(RuntimeError):
    """The model's output does not satisfy the declared format constraint —
    invalid JSON, or a mismatch against the schema.

    Distinct from a service failure (timeout, empty response): the agent runner
    turns this into one repair round. ``raw`` carries the reply verbatim for the
    transcript, since the rejected text never re-enters the session.
    """

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


def clean_json(text: str) -> str:
    """Extract the first valid top-level JSON object from model output.

    Strips ```json fences, tolerates prose before and after, and accepts only an
    object ({...}) at the top level. Returns the cleaned JSON string, not a
    dict. Raises TypeError on a non-string and ValueError when nothing is found.
    """
    if not isinstance(text, str):
        raise TypeError("clean_json() expects a string")

    text = text.strip()
    fence_match = re.fullmatch(
        r"\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*", text, flags=re.S
    )
    if fence_match:
        text = fence_match.group(1).strip()

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        start = match.start()
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        return text[start:start + end].strip()

    # The rejected text travels on OutputFormatViolation.raw, not in this
    # message: quoting a whole reply here puts tens of thousands of characters
    # into every chained traceback.
    raise ValueError(
        f"No valid top-level JSON object found in {len(text)} characters of output"
    )


def _clean(content: str, model_name: str, mode: str) -> str:
    """Run ``clean_json`` and turn its ValueError into OutputFormatViolation."""
    try:
        return clean_json(content)
    except ValueError as e:
        raise OutputFormatViolation(
            f"no JSON object in {model_name} output under {mode}; "
            f"first 300 chars: {content[:300]}", raw=content
        ) from e


def ensure_valid_json(content: str, model_name: str) -> str:
    """Guarantee for ``response_format="json"``: clean the output, check that it
    parses, and return the cleaned JSON text. Raises OutputFormatViolation."""
    cleaned = _clean(content, model_name, "response_format='json'")
    try:
        json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise OutputFormatViolation(
            f"invalid JSON from {model_name} under response_format='json': "
            f"{e.msg} at pos {e.pos}; cleaned text (first 300): {cleaned[:300]}",
            raw=content
        ) from e
    return cleaned


def _sharpen(error: jsonschema.ValidationError, data):
    """Replace an ``anyOf`` blanket error with the sub-error of the branch the
    answer aimed at: the union error names no field, while the branch selected
    by its const discriminator names the field that is actually wrong.
    """
    if error.validator != "anyOf" or not isinstance(data, dict):
        return error
    for sub in error.context or []:
        branch = error.schema["anyOf"][sub.schema_path[0]]
        consts = {k: v["const"] for k, v in branch.get("properties", {}).items()
                  if isinstance(v, dict) and "const" in v}
        if consts and all(data.get(k) == v for k, v in consts.items()):
            return sub
    return error


def check_against_schema(data, schema: dict, model_name: str,
                         excerpt: str) -> None:
    """Validate an already-parsed object against ``schema``; returns nothing and
    raises OutputFormatViolation on a mismatch.

    ``excerpt`` is the text the object came from, quoted in the error message;
    a tool call arrives already parsed by the provider, with no text to clean.
    """
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        e = _sharpen(e, data)
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        # The top-level keys make the commonest failure — the object wrapped, or
        # not wrapped, differently from the schema — visible at a glance.
        got = (f"top-level keys: {sorted(data)}" if isinstance(data, dict)
               else f"top-level type: {type(data).__name__}")
        raise OutputFormatViolation(
            f"{model_name} output does not match json_schema: {e.message} "
            f"(at {path}); {got}; what was parsed (first 300 chars): {excerpt}",
            raw=json.dumps(data, ensure_ascii=False, indent=2)
        ) from e


def ensure_schema_valid(content: str, schema: dict, model_name: str) -> str:
    """Guarantee for ``json_schema``: clean, parse, and validate in full with
    jsonschema, returning the cleaned JSON text.

    It covers two holes in provider-side structured outputs: SDKs and providers
    strip schema keywords they do not support, and a relay may discard the
    structured-output parameters entirely.
    """
    cleaned = _clean(content, model_name, "the json_schema constraint")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise OutputFormatViolation(
            f"invalid JSON from {model_name} under the json_schema constraint: "
            f"{e.msg} at pos {e.pos}; cleaned text (first 300): {cleaned[:300]}",
            raw=content
        ) from e
    check_against_schema(data, schema, model_name, cleaned[:300])
    return cleaned
