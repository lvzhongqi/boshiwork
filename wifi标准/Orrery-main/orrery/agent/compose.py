"""Shared pieces for assembling messages and prompts.

Every sentence a model sees lives in a prompts/*.md file next to the code that
uses it; the code computes variables and renders. Templates go through jinja2 in
strict mode, so an unsupplied variable is an error at load time rather than a
literal ``{{ … }}`` reaching the model.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, StrictUndefined

_JINJA = Environment(undefined=StrictUndefined, keep_trailing_newline=True)


def render_prompt(caller_file: str, name: str, **variables) -> str:
    """Render prompts/<name> from the caller's own directory. Passing no
    variables still runs the template, so a stray placeholder in an otherwise
    static prompt fails loudly."""
    text = (Path(caller_file).parent / "prompts" / name).read_text(encoding="utf-8")
    return _JINJA.from_string(text).render(**variables)


def _cut_blocks(text: str, cut_after: list[str], name: str) -> list[str]:
    """Cut a system template into cache blocks at the closing tag of each named
    section, taking the rest of that line with it. The cut happens on the
    template, before rendering, so injected text containing ``</document>``
    cannot move a boundary. Raises ValueError if a named tag is not found.
    """
    parts: list[str] = []
    rest = text
    for tag in cut_after:
        close = f"</{tag}>"
        i = rest.find(close)
        if i < 0:
            raise ValueError(
                f"{name}: cut_after names <{tag}>, but the template has no "
                f"closing {close} after the previous cut")
        nl = rest.find("\n", i + len(close))
        end = len(rest) if nl < 0 else nl + 1
        parts.append(rest[:end])
        rest = rest[end:]
    parts.append(rest)
    return parts


def render_system(caller_file: str, name: str, *, cut_after: list[str],
                  cut_after_prefix: bool = False, **variables) -> list[str]:
    """Render a system prompt into its cache blocks, each of which gets its own
    cache breakpoint. ``cut_after`` names the tagged sections that end a block;
    ``cut_after_prefix`` instead cuts at the first blank line, for an untagged
    corpus or model at the front. Three blocks at most. run_agent appends the
    delivery format to the last block."""
    text = (Path(caller_file).parent / "prompts" / name).read_text(encoding="utf-8")
    if cut_after_prefix:
        if cut_after:
            raise ValueError(
                f"{name}: cut_after_prefix cannot be combined with cut_after")
        prefix, gap, rest = text.partition("\n\n")
        if not gap or not prefix.strip() or not rest.strip():
            raise ValueError(
                f"{name}: cut_after_prefix needs a non-empty first paragraph")
        parts = [prefix, rest]
    else:
        parts = _cut_blocks(text, list(cut_after), name)
    if len(parts) > 3:
        raise ValueError(
            f"{name}: {len(parts)} system blocks; the request may mark three "
            f"(the message rolling breakpoint takes the fourth)")
    blocks = [_JINJA.from_string(p).render(**variables).strip("\n")
              for p in parts]
    for i, b in enumerate(blocks):
        if not b.strip():
            raise ValueError(f"{name}: system block {i} rendered to nothing")
    return blocks


def render_file(path: Path, **variables) -> str:
    """Render a prompt file by path, the form the realizer and injector leaves
    use: one directory per subtype with the prompts inside it."""
    return _JINJA.from_string(path.read_text(encoding="utf-8")).render(**variables)


def localized(name: str, lang: str) -> str:
    """The prompt file name for ``lang``: unchanged for ``"en"``, or the ``_zh``
    marker inserted before the first dot — ``main.sys.md`` -> ``main_zh.sys.md``.
    Raises ValueError for any other lang or an undotted name; a missing Chinese
    counterpart surfaces later as FileNotFoundError when the file is read."""
    if lang not in ("en", "zh"):
        raise ValueError(f"lang must be 'en' or 'zh', got {lang!r}")
    if lang == "en":
        return name
    stem, dot, rest = name.partition(".")
    if not dot:
        raise ValueError(f"{name!r}: expected a dotted filename")
    return f"{stem}_zh.{rest}"


def resume_user(submit) -> str:
    """The one resume message, generated from the submission contract shared by
    every node. ``submit`` is a SubmitSpec, typed loosely so compose does not
    have to import runner."""
    deliverable = {
        "tool": "the finished product by calling the submit tool",
        "json": "the JSON submission",
        "fence": f"the complete file in one ```{submit.fence_lang} block",
        "text": "your answer",
    }[submit.kind]
    return ("The previous session was interrupted. Continue from the progress "
            f"above and submit {deliverable}.")


def step_messages(bodies: list[str]) -> str:
    """The filed-messages section, appended to a fresh session's user message; a
    resumed session already got the same text in its transcript when the fix or
    gap executed. It goes last in the message, being the most specific thing the
    step is asked to honour. Empty string when there are no messages."""
    if not bodies:
        return ""
    joined = "\n\n".join(bodies)
    return ("\n\n<step_messages>\n"
            "Messages filed for this step earlier in this run — by the user "
            "after reading this step's output, or by a downstream step that "
            "found something missing. Each says which it is. They are in time "
            "order; where two conflict, the later one stands, because it was "
            "written knowing the earlier one. Apply them to this run of the "
            "step.\n\n"
            f"{joined}\n"
            "</step_messages>\n")


class RepairContext(str):
    """A repair attachment travelling inside a problems list: full context for
    the model's next attempt, such as an assembled file, rather than a finding.
    The runner keeps it out of the ledger's CheckReport, where a multi-line file
    would break the event digest's rendering."""


def assembled_context(pv: str) -> RepairContext:
    """The edits-mode repair tail, shared by apply and inject: the whole
    assembled file plus the two semantic rules a resubmission must know. Every
    round re-applies to the original model, so an array holding only the fix
    silently drops the edits that were right and can still typecheck."""
    return RepairContext(
        "Resubmit the **complete** edits array, not just the fix: your new "
        "array replaces the previous one entirely and is applied to the "
        "original model, so every edit you leave out is simply not made. "
        "Keep the edits that were right, correct the ones that were not. "
        "Anchors must quote the ORIGINAL model you were given in the context, "
        "not the assembled text below.\n"
        "The assembled result of your previous edits (for reference only):\n"
        f"```proverif\n{pv}\n```")


def diagnosis(attempt: int, max_repairs: int, findings: list[str]) -> str:
    """The repair message: the specific problems plus how many chances remain.
    findings come from the check layer or from a failed submission parse."""
    body = "\n".join(f"- {f}" for f in findings)
    return (f"Your submission did not pass acceptance (repair {attempt} of "
            f"{max_repairs}). Fix each problem below and submit again, leaving "
            f"everything else untouched:\n{body}")
