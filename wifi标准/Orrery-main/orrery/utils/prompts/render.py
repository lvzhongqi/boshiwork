"""Renders every request the pipeline can send, one markdown file per request,
so the prompts can be read as the model gets them without paying for a run.

Each file is a session opening — tools, system blocks, user message — built by
the run's own ``sent_blocks`` / ``sent_tools`` and each node's ``build_prompt``,
so the preview cannot drift from what is sent. Subtypes that open no session
(noop, stub, ``is_code``) get no file; a request is rendered again with a
``_zh`` suffix wherever a ``_zh`` prompt file exists. Input is the ``fixture/``
protocol beside this module, never LIB, so the output moves with the prompts
and not with the corpus.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from orrery.agent.runner import Prompt, sent_blocks, sent_tools
from orrery.expert import session as expert_session
from orrery.modules.libschema.model import Goal, Point
from orrery.nodes.apply.node import build_batch_encode_prompt, build_encode_prompt
from orrery.nodes.apply.realizers import REALIZERS
from orrery.nodes.inject import node as inject_node
from orrery.nodes.inject.injectors import INJECTORS
from orrery.nodes.assumptions import node as assumptions_node
from orrery.nodes.claims import node as claims_node
from orrery.nodes.flow import node as flow_node
from orrery.nodes.preprocess import section_tagger as tag_node
from orrery.nodes.properties import node as properties_node
from orrery.nodes.flow.template import render_template
from orrery.nodes.principals import node as principals_node
from orrery.services.transcript.prompt import render

#: The toy protocol the preview reads, a LIB-shaped directory shared with the
#: tests. It sits beside this module so it travels with the package.
FIXTURE = Path(__file__).resolve().parent / "fixture"
if not FIXTURE.is_dir():
    raise FileNotFoundError(
        f"the prompt preview reads its fixture protocol at {FIXTURE}, which is "
        "not there; the package is incomplete")
#: Where `orrery prompt` writes when no directory is named; relative, so it
#: lands where the command was run.
OUT_DEFAULT = Path("prompts")
PROTOCOL = "TAP"
FIXTURE_PV = (FIXTURE / "formal" / "proverif" / "flow.pv"
              ).read_text(encoding="utf-8").rstrip("\n")
FIXTURE_DOC = (FIXTURE / "source" / "main" / "TAP.md").read_text(encoding="utf-8")
FIXTURE_KNOWLEDGE = json.loads(
    (FIXTURE / "principals" / "principals.json").read_text(encoding="utf-8"))

# One sample value per param kind, so a target can be built for any subtype
# without hand-writing one per entry. Names are the fixture model's.
_SAMPLE = {
    "entity": "A",
    "value_name": "KAB",
    "entity_pair": ["A", "B"],
    "entity_set": ["A", "B"],
    "identity_scope": "peer_auth",
    "phase": 1,
    "primitive": "aenc",
}
_VALUE_NAME_BY_AXIS = {"data": "PKB"}
# A field name beats the axis default where the axis sample would name a value
# of the wrong sort: the reuse axes' `payload` is an application payload the
# extra use carries, not a key.
_VALUE_NAME_BY_FIELD = {"payload": "I_A"}


def sample_target(realizer) -> dict | None:
    """A target for this subtype with every declared param filled, optional
    ones included, since an optional param changes what the rules say. Returns
    None for a subtype that declares no params."""
    if not realizer.params:
        return None
    out = {}
    for name, spec in realizer.params.items():
        kind = spec["kind"]
        if kind == "value_name":
            out[name] = _VALUE_NAME_BY_FIELD.get(
                name, _VALUE_NAME_BY_AXIS.get(realizer.axis, _SAMPLE[kind]))
        else:
            out[name] = _SAMPLE[kind]
    return out


def as_markdown(p: Prompt) -> str:
    """One request as the reader sees it. Both transforms are the run's own."""
    return render(tools=sent_tools(p.tools, p.submit, where=p.label),
                  system=sent_blocks(p.system, p.submit),
                  user=p.user)


# The file-name prefix of each group, so a directory listing reads in pipeline
# order instead of alphabetically. The numbers are the run directory's own, so
# the two listings line up; the expert is not a node and sorts last under 99.
_PREFIX = {
    "tag_sections": "02",
    "principals": "03",
    "flow": "04",
    "assumptions": "05",
    "properties": "06",
    "claims": "07",
    "apply.encode": "06_1b",
    "apply.encode_batch": "06_1c",
    "inject": "06_4",
    "attacks": "13",
    "expert": "99",
}


def _build_or_skip(build, lang: str):
    """Call the zero-arg thunk ``build`` and return its Prompt. Under
    ``lang == "zh"`` a missing prompt file means the node or subtype has no
    ``_zh`` counterpart yet, and this returns ``None``; under ``lang == "en"``
    every prompt file must exist, so ``FileNotFoundError`` propagates."""
    if lang != "zh":
        return build()
    try:
        return build()
    except FileNotFoundError:
        return None


def extraction_requests(lang: str = "en"):
    """The four document readers plus the flow node: one request each."""
    t = _build_or_skip(lambda: tag_node.build_prompt(
        corpus=FIXTURE_DOC, protocol=PROTOCOL, step_messages="", lang=lang), lang)
    if t is not None:
        yield ("02_tag_sections", t)
    p = _build_or_skip(lambda: principals_node.build_prompt(
        corpus=FIXTURE_DOC, protocol=PROTOCOL, step_messages="", lang=lang), lang)
    if p is not None:
        yield ("03_principals", p)
    f = _build_or_skip(lambda: flow_node.build_prompt(
        corpus=FIXTURE_DOC, protocol=PROTOCOL, knowledge=FIXTURE_KNOWLEDGE,
        template=render_template(protocol_name=PROTOCOL,
                                 knowledge=FIXTURE_KNOWLEDGE),
        step_messages="", lang=lang), lang)
    if f is not None:
        yield ("04_flow", f)
    for label, mod in (("05_assumptions", assumptions_node),
                       ("06_properties", properties_node)):
        v = _build_or_skip(lambda mod=mod: mod.build_prompt(
            corpus=FIXTURE_DOC, protocol=PROTOCOL,
            knowledge_json=json.dumps(FIXTURE_KNOWLEDGE, ensure_ascii=False,
                                      indent=2),
            flow_pv=FIXTURE_PV, step_messages="", lang=lang), lang)
        if v is not None:
            yield (label, v)
    c = _build_or_skip(lambda: claims_node.build_prompt(
        corpus=FIXTURE_DOC, protocol=PROTOCOL,
        assumptions_json="{}", properties_json="{}",
        flow_pv=FIXTURE_PV,
        step_messages="", lang=lang), lang)
    if c is not None:
        yield ("07_claims", c)


def apply_requests(lang: str = "en"):
    """One ordinary encoding per writing, plus its fixed-data batch form. Only
    the subtypes that open a session: a noop writes nothing, a stub is not
    implemented, and an ``is_code`` subtype applies its edit in code and so has
    no rules block to render."""
    for (axis, subtype), cls in sorted(REALIZERS.items()):
        if cls.is_noop or cls.is_stub or cls.is_code:
            continue
        realizer = cls()
        target = sample_target(realizer)
        for form in (sorted(realizer.writings) or [None]):
            e = _build_or_skip(lambda form=form: build_encode_prompt(
                FIXTURE_PV, realizer, target, form=form,
                step_messages="", lang=lang), lang)
            if e is not None:
                stem = (f"{_PREFIX['apply.encode']}_apply.encode.{axis}.{subtype}"
                        + (f".{form}" if form else ""))
                yield (stem, e)
            if axis == "data":
                points = [
                    Point(axis=axis, subtype=subtype, target={"of": name},
                          ref_id=f"fixed_{name.lower()}")
                    for name in ("PKA", "PKB")
                ]
                b = _build_or_skip(lambda form=form, points=points:
                                   build_batch_encode_prompt(
                                       FIXTURE_PV, realizer, points, form=form,
                                       step_messages="", lang=lang), lang)
                if b is not None:
                    stem = (f"{_PREFIX['apply.encode_batch']}_apply.encode_batch."
                            f"{axis}.{subtype}"
                            + (f".{form}" if form else ""))
                    yield (stem, b)


_GOALS = {
    "Secrecy": [Goal(id="secrecy_i_a", type="Secrecy", values=("I_A",),
                     parties={"holders": ["A", "B"]}),
                Goal(id="secrecy_i_b", type="Secrecy", values=("I_B",),
                     parties={"holders": ["A", "B"]})],
    "Authentication": [Goal(id="auth_a_to_b", type="Authentication",
                            values=("PKA",),
                            parties={"asserter": "A", "subject": "B"}),
                       Goal(id="auth_b_to_a", type="Authentication",
                            values=("PKB",),
                            parties={"asserter": "B", "subject": "A"})],
}


def inject_requests(lang: str = "en"):
    """One request per goal subtype that has rules. Each file is a single-cell
    batch; a multi-cell batch renders the same bytes, because the rules block is
    deduplicated and the Authentication tiers share one."""
    for (gtype, subtype), cls in sorted(INJECTORS.items()):
        try:
            cls().sys_prompt(lang=lang)
        except FileNotFoundError:
            continue        # no rules written yet — for this axis, or for this lang
        goals = _GOALS.get(gtype)
        if goals is None:
            continue
        cells = [(gtype, subtype, goals)]
        p = _build_or_skip(lambda cells=cells: inject_node.build_prompt(
            FIXTURE_PV, cells, step_messages="", lang=lang), lang)
        if p is not None:
            yield (f"{_PREFIX['inject']}_inject.{gtype}.{subtype}", p)


def attack_requests(lang: str = "en"):
    """One explanation, of Lowe's attack on NSPK as the step scripts it, and the
    summary over it. The scenario and goal texts are stand-ins in the node's
    own format; the script is the one the step builds from the graph."""
    from orrery.modules.attacks.graph import read
    from orrery.modules.attacks.script import build
    from orrery.nodes.reproduce_attacks import explain
    graph = FIXTURE / "attack_graphs" / "nspk_auth.dot"
    script = explain.render_script(build(read(graph)).to_json())
    p = _build_or_skip(lambda: explain.build_explain_prompt(
        protocol=PROTOCOL, scenario="peer_key_attacker_supplied",
        assumptions=("- admission_peer_auth = open (admission, scope peer_auth; "
                     "chosen by this scenario): <the subtype's description>"),
        goal="auth_b_to_a (Authentication.injective_agreement) about A, B, "
             "I_A: <the goal's description>",
        script=script, replay=False,
        tools=explain.cell_tools(graph, graph), lang=lang), lang)
    if p is not None:
        yield (f"{_PREFIX['attacks']}_explain", p)
    s = _build_or_skip(lambda: explain.build_summary_prompt(
        protocol=PROTOCOL,
        cells=("peer_key_attacker_supplied/auth_b_to_a\n<the conclusion "
               "written for this cell>"),
        pending=0, lang=lang), lang)
    if s is not None:
        yield (f"{_PREFIX['attacks']}_summary", s)


def expert_requests(lang: str = "en"):
    """The one request the expert session opens with, on a placeholder run
    state and user message."""
    p = _build_or_skip(lambda: expert_session.build_prompt(
        state="<the run overview: nodes, scenarios, verdicts, gaps>",
        user_text="<the user's message>", lang=lang), lang)
    if p is not None:
        yield (f"{_PREFIX['expert']}_expert", p)


GROUPS = (("extraction", extraction_requests),
          ("apply", apply_requests),
          ("inject", inject_requests),
          ("attacks", attack_requests),
          ("expert", expert_requests))


def _clear(out: Path) -> None:
    """Empty ``out`` so it can be rebuilt, refusing anything that is not a
    previous rendering. ``--out`` is a path a reader typed, and a rendering is
    nothing but ``.md`` files, so that is the whole test: an empty directory or
    one holding only markdown gets wiped, anything else raises."""
    if not out.exists():
        return
    if not out.is_dir():
        raise NotADirectoryError(f"{out} is not a directory")
    intruders = sorted(p.name for p in out.iterdir() if p.suffix != ".md"
                       or not p.is_file())
    if intruders:
        raise RuntimeError(
            f"{out} holds files this command did not write ({', '.join(intruders[:5])}"
            f"{', …' if len(intruders) > 5 else ''}); rendering would wipe it. "
            "Point --out at a fresh directory.")
    shutil.rmtree(out)


def write_all(out: Path) -> int:
    """Wipe ``out`` and write one file per request in English, plus a second
    file (same stem, ``_zh`` before the extension) for each request whose node
    or subtype has a Chinese prompt; returns the total written. The directory is
    rebuilt rather than updated, so a request that stops existing takes its file
    with it. Which subtypes are translated is not tracked here — it is read off
    ``build_prompt`` raising ``FileNotFoundError`` (``_build_or_skip``)."""
    out = Path(out)
    _clear(out)
    out.mkdir(parents=True)
    counts, zh_counts = {}, {}
    for group, requests in GROUPS:
        n = 0
        for stem, prompt in requests():
            (out / f"{stem}.md").write_text(as_markdown(prompt), encoding="utf-8")
            n += 1
        counts[group] = n
        nz = 0
        for stem, prompt in requests(lang="zh"):
            (out / f"{stem}_zh.md").write_text(as_markdown(prompt), encoding="utf-8")
            nz += 1
        zh_counts[group] = nz
    total = sum(counts.values()) + sum(zh_counts.values())
    print(f"{total} request(s) written to {out}/  "
          + ", ".join(f"{k} {v}" for k, v in counts.items())
          + "  (zh: " + ", ".join(f"{k} {v}" for k, v in zh_counts.items()) + ")")
    return total

