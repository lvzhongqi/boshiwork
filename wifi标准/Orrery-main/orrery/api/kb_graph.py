"""The assumption vocabulary as one self-contained HTML page — served at
``/vocabulary`` by the console, written by ``orrery kb <path>.html``, generated
on demand from the realizer and builder class declarations.

Protocol usage comes from the corpus (``api/corpus_usage``), an optional
dependency: with no readable root the page renders with an empty panel.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from orrery.api.corpus_usage import CorpusUsage, scan_usage
from orrery.api.reading_order import name_rank
from orrery.nodes.apply.realizers import FLOW_STATE, REALIZERS, VOCAB
from orrery.nodes.world.builders import (
    BUILDERS,
    WORLD_AXES,
    WORLD_FLOW_STATE,
    WORLD_INSTANCE_KEY,
    WORLD_SUBTYPES,
    WORLD_VOCAB,
)
from orrery.version import VOCAB_VERSION

_CSS = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --ink: #1c2330; --muted: #66707f;
  --line: #d8dde4; --world: #8a5a00; --world-bg: #fff3dd;
  --flow: #1a7f37; --stub: #9aa2ad; --edge: #6c4cf0; --chip: #eef0f4;
  --hit: #d92d20; --hit-soft: rgba(217,45,32,.09);
}
/* Dark by the OS setting, or by an explicit data-theme — the console is
   dark-themed and this page opens from it, so the two should not clash. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14171c; --card: #1d2229; --ink: #e6e9ee; --muted: #9aa4b1;
    --line: #333b46; --world: #e5b567; --world-bg: #2a2314;
    --flow: #57c07a; --stub: #6b7480; --edge: #b79cff; --chip: #262d36;
    --hit: #ff6b5e; --hit-soft: rgba(255,107,94,.12);
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #14171c; --card: #1d2229; --ink: #e6e9ee; --muted: #9aa4b1;
  --line: #333b46; --world: #e5b567; --world-bg: #2a2314;
  --flow: #57c07a; --stub: #6b7480; --edge: #b79cff; --chip: #262d36;
  --hit: #ff6b5e; --hit-soft: rgba(255,107,94,.12);
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 26px 80px; background: var(--bg);
       color: var(--ink);
       font: 14px/1.45 -apple-system, "PingFang SC", "Noto Sans SC",
             "Helvetica Neue", sans-serif; }
h1 { font-size: 20px; margin: 0 0 2px; }
.sub { color: var(--muted); margin-bottom: 16px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
          color: var(--muted); font-size: 12px; margin-bottom: 20px; }
h2 { font-size: 15px; margin: 26px 0 4px; }
h2 .note { font-weight: normal; color: var(--muted); font-size: 12px;
           margin-left: 8px; }

/* two columns: the cards, and the protocol panel that stays in view */
.wrap { display: flex; gap: 20px; align-items: flex-start; }
.main { flex: 1 1 auto; min-width: 0; }
.side { flex: 0 0 290px; position: sticky; top: 16px;
        max-height: calc(100vh - 32px); overflow: auto;
        background: var(--card); border: 1px solid var(--line);
        border-radius: 10px; padding: 12px 12px 14px; }
.side h3 { font-size: 13px; margin: 0 0 2px; }
.side .hint { color: var(--muted); font-size: 11px; margin-bottom: 10px; }
.p { display: block; width: 100%; text-align: left; font: inherit;
     font-size: 12.5px; font-weight: 650; color: var(--ink);
     background: transparent; border: 1px solid transparent;
     border-radius: 7px; padding: 3px 6px; margin-top: 8px; cursor: pointer; }
.p:hover { background: var(--chip); }
.p .n { color: var(--muted); font-weight: 400; font-size: 11px; }
.p.on { border-color: var(--hit); background: var(--hit-soft); color: var(--hit); }
.p.hit { border-color: var(--hit); background: var(--hit-soft); }
.pi { display: block; font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 11px; color: var(--muted); padding: 1px 6px 1px 14px;
      border-radius: 5px; cursor: pointer; }
.pi:hover { background: var(--chip); color: var(--ink); }
.pi.stub { text-decoration: line-through dotted; }
.pi.world { color: var(--world); }
/* the fold: a protocol directory opens to the sub-protocols under it */
.fold { margin: 0 0 8px 8px; }
.more { font: inherit; font-size: 11px; color: var(--muted); background: none;
  border: 0; padding: 2px 0; cursor: pointer; }
.more:hover { color: var(--ink); }
.mechs { margin: 3px 0 0 8px; border-left: 1px solid var(--line);
  padding-left: 8px; }
.p.mech { font-size: 11px; padding: 3px 6px; margin: 6px 0 2px; }
/* a directory declares nothing itself — its name reads as a container */
.p.dir { color: var(--muted); }
.mechs .pi { margin-left: 6px; }
.meta.none { font-style: italic; }

.band { display: flex; align-items: flex-start; gap: 6px; overflow-x: auto;
        padding: 10px 2px 16px; }
.band .arrow { align-self: center; color: var(--world); font-size: 20px;
               flex: 0 0 auto; padding: 0 2px; }
.groups { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start;
          padding-top: 8px; }
.group { border: 1px dashed var(--line); border-radius: 12px;
         padding: 12px 12px 14px; }
.group > .gname { color: var(--muted); font-size: 12px; letter-spacing: .04em;
                  margin-bottom: 10px; }
.group .cards { display: flex; gap: 12px; align-items: flex-start;
                flex-wrap: wrap; }
.axis { background: var(--card); border: 1px solid var(--line);
        border-radius: 10px; width: 320px; flex: 0 0 auto;
        box-shadow: 0 1px 2px rgba(0,0,0,.06); }
.axis.world { border-color: var(--world); }
.axis.hl { outline: 2px solid var(--edge); outline-offset: 3px; }
.axhead { display: flex; align-items: baseline; gap: 8px;
          padding: 10px 12px 8px; border-bottom: 1px solid var(--line); }
.axhead .name { font-weight: 650; font-size: 14px; }
.axhead .obj { color: var(--muted); font-size: 11px; margin-left: auto; }
.tag { display: inline-block; font-size: 10px; padding: 1px 6px;
       border-radius: 8px; background: var(--chip); color: var(--muted); }
.tag.world { background: var(--world-bg); color: var(--world); }
.tag.flow { color: var(--flow); border: 1px solid var(--flow);
            background: transparent; }
.tag.stub { border: 1px dashed var(--stub); background: transparent; }
.sts { padding: 4px 6px 6px; }
.st { padding: 7px 8px 8px 10px; border: 1px solid transparent;
      border-radius: 7px; cursor: pointer; }
.st + .st { margin-top: 2px; }
.st:hover { background: var(--chip); }
.st .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; }
.st .name { font-weight: 600; font-family: ui-monospace, "SF Mono", Menlo,
            monospace; font-size: 12.5px; }
.st.stub .name { color: var(--stub); }
.st .stronger { color: var(--muted); font-size: 11px; }
.st .desc { color: var(--muted); font-size: 11.5px; margin-top: 3px; }
.st .meta { color: var(--muted); font-size: 11px; margin-top: 3px;
            font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.st .writings { font-size: 11px; margin-top: 4px; color: var(--muted); }
.st .writings .tag { margin: 0 2px; }
.st .reqs { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 5px; }
.st .req { font-size: 10.5px; color: var(--edge);
           border: 1px dashed var(--edge); border-radius: 8px; padding: 1px 7px; }
.st .conf { font-size: 10.5px; color: var(--hit);
            border: 1px solid var(--hit); border-radius: 8px; padding: 1px 7px; }
/* the two selections: a protocol's subtypes, and the picked subtype itself */
.st.hit { border-color: var(--hit); background: var(--hit-soft); }
/* Weaker than .hit on purpose: declared and defaulted are different claims —
   one is recorded, the other is read off the absence of a record. */
.st.def { border-color: var(--hit); border-style: dashed; }
.p.dhit { border-color: var(--hit); border-style: dashed; }
.st.pick { border-color: var(--edge); background: var(--chip); }
body.sel .st:not(.hit):not(.pick):not(.rel):not(.def) { opacity: .32; }
body.sel .st.def { opacity: .7; }
body.sel .p:not(.on):not(.hit):not(.dhit) { opacity: .45; }
body.sel .p.dhit { opacity: .72; }
.st.rel { border-color: var(--hit); }
.railnote { color: var(--muted); font-size: 10px; padding: 0 12px 8px 14px; }
#edges { position: absolute; left: 0; top: 0; pointer-events: none; z-index: 5; }
.elabel { position: absolute; z-index: 6; transform: translate(-50%, -50%);
          font-size: 10.5px; color: var(--bg); padding: 1px 7px;
          border-radius: 8px; white-space: nowrap; }
[hidden] { display: none !important; }
"""

_JS = """
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.id = "edges";
  document.body.appendChild(svg);
  const labels = [];
  let sel = null;                       // {kind: "p"|"st", key}

  const el = (id) => document.getElementById(id);
  const stId = (coord) => "st-" + coord.replace(".", "-");

  function clear() {
    svg.replaceChildren();
    labels.forEach(l => l.remove()); labels.length = 0;
    // Every class a selection can add — the two dashed ones included. They
    // are painted by the same click as the solid ones, so leaving them out
    // left a flow state's default boxes on the protocol names forever.
    document.querySelectorAll(".hit, .pick, .on, .rel, .hl, .def, .dhit")
      .forEach(e => e.classList.remove(
        "hit", "pick", "on", "rel", "hl", "def", "dhit"));
    document.body.classList.remove("sel");
    sel = null;
  }

  function sizeOverlay() {
    const doc = document.documentElement;
    svg.setAttribute("width", doc.scrollWidth);
    svg.setAttribute("height", doc.scrollHeight);
    svg.style.width = doc.scrollWidth + "px";
    svg.style.height = doc.scrollHeight + "px";
    const c = getComputedStyle(doc);
    const defs = document.createElementNS(NS, "defs");
    for (const [name, color] of [["dep", c.getPropertyValue("--edge").trim()],
                                 ["con", c.getPropertyValue("--hit").trim()]]) {
      const m = document.createElementNS(NS, "marker");
      m.setAttribute("id", "ah-" + name);
      m.setAttribute("markerWidth", "7"); m.setAttribute("markerHeight", "7");
      m.setAttribute("refX", "6"); m.setAttribute("refY", "3.5");
      m.setAttribute("orient", "auto");
      const tip = document.createElementNS(NS, "path");
      tip.setAttribute("d", "M0,0 L7,3.5 L0,7 z");
      tip.setAttribute("fill", color);
      m.appendChild(tip); defs.appendChild(m);
    }
    svg.appendChild(defs);
  }

  // One edge between two boxes, entering through whichever border faces the
  // source, so a line never crosses the thing it points at.
  function edge(from, to, kind, text) {
    const c = getComputedStyle(document.documentElement);
    const color = c.getPropertyValue(kind === "con" ? "--hit" : "--edge").trim();
    const sx = window.scrollX, sy = window.scrollY;
    const a = from.getBoundingClientRect(), b = to.getBoundingClientRect();
    const p1 = { x: a.left + sx + a.width / 2, y: a.top + sy + a.height / 2 };
    const top = b.top + sy, bottom = b.bottom + sy;
    const cx = b.left + sx + b.width / 2, cy = top + b.height / 2;
    let p2;
    if (p1.y < top) p2 = { x: cx, y: top - 3 };
    else if (p1.y > bottom) p2 = { x: cx, y: bottom + 3 };
    else p2 = { x: p1.x < cx ? b.left + sx - 3 : b.right + sx + 3, y: cy };
    const dx = p2.x - p1.x, dy = p2.y - p1.y;
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", "M " + p1.x + " " + p1.y + " C " +
      (p1.x + dx * 0.12) + " " + (p1.y + dy * 0.5) + ", " +
      (p2.x - dx * 0.12) + " " + (p2.y - dy * 0.5) + ", " + p2.x + " " + p2.y);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", "1.6");
    if (kind === "dep") path.setAttribute("stroke-dasharray", "5 3");
    path.setAttribute("marker-end", "url(#ah-" + kind + ")");
    svg.appendChild(path);
    const l = document.createElement("div");
    l.className = "elabel"; l.textContent = text;
    l.style.background = color;
    l.style.left = (p1.x + p2.x) / 2 + "px";
    l.style.top = (p1.y + p2.y) / 2 + "px";
    document.body.appendChild(l); labels.push(l);
  }

  function drawFor(coord) {
    sizeOverlay();
    const src = el(stId(coord));
    if (!src) return;
    for (const e of (CONF[coord] || [])) {
      const dst = el(stId(e.other));
      if (dst) { dst.classList.add("rel"); edge(src, dst, "con", e.label); }
    }
  }

  function pickSubtype(coord) {
    clear();
    sel = { kind: "st", key: coord };
    document.body.classList.add("sel");
    const src = el(stId(coord));
    if (src) src.classList.add("pick");
    // Every protocol that declares it, boxed in the panel — and, for a flow
    // state, every protocol that simply never mentions the axis, boxed more
    // faintly: an unmentioned axis IS at its flow state, so lighting nothing
    // there would have been the page's own answer to the wrong question.
    document.querySelectorAll(".p").forEach(p => {
      const name = p.dataset.p;
      if ((USES[name] || []).includes(coord)) p.classList.add("hit");
      else if ((DEF[name] || []).includes(coord)) p.classList.add("dhit");
    });
    drawFor(coord);
  }

  function pickProtocol(name) {
    clear();
    sel = { kind: "p", key: name };
    document.body.classList.add("sel");
    const row = document.querySelector('.p[data-p="' + CSS.escape(name) + '"]');
    if (row) row.classList.add("on");
    for (const coord of (USES[name] || [])) {
      const st = el(stId(coord));
      if (st) st.classList.add("hit");
    }
    // and the axes it never mentions: it sits at their flow state, which is
    // half of what "the world this protocol is analysed in" means
    for (const coord of (DEF[name] || [])) {
      const st = el(stId(coord));
      if (st) st.classList.add("def");
    }
  }

  document.addEventListener("click", (ev) => {
    // The fold is navigation, not a selection: opening a directory must not
    // clear the subtype a reader is holding lit while they look for it.
    const more = ev.target.closest(".more");
    if (more) {
      const box = document.querySelector(
        '.mechs[data-for="' + CSS.escape(more.dataset.fold) + '"]');
      if (box) {
        box.hidden = !box.hidden;
        // A verb both ways: "open" read as the name of a sub-protocol.
        more.textContent = box.hidden ? "\u25b8 expand" : "\u25be collapse";
        if (sel && sel.kind === "st") pickSubtype(sel.key);
      }
      return;
    }
    const p = ev.target.closest(".p");
    if (p) {
      const was = sel && sel.kind === "p" && sel.key === p.dataset.p;
      was ? clear() : pickProtocol(p.dataset.p);
      return;
    }
    const pi = ev.target.closest(".pi");
    if (pi) {
      const was = sel && sel.kind === "st" && sel.key === pi.dataset.st;
      was ? clear() : pickSubtype(pi.dataset.st);
      return;
    }
    const st = ev.target.closest(".st");
    if (st) {
      const coord = st.dataset.coord;
      const was = sel && sel.kind === "st" && sel.key === coord;
      was ? clear() : pickSubtype(coord);
      return;
    }
    if (sel) clear();
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") clear(); });
  const redraw = () => { if (sel && sel.kind === "st") drawFor(sel.key); };
  window.addEventListener("resize", redraw);
  window.addEventListener("scroll", redraw, { passive: true });
})();
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def protocol_index(usage: CorpusUsage) -> dict[str, list[str]]:
    """key -> the subtype coordinates the corpus declares under it.

    Two kinds of key, both corpus-relative paths: a protocol directory carrying
    the union over the sub-protocols under it, and one per mechanism beneath it
    carrying that one alone. A protocol with no ``subprotocols/`` layer is one
    leaf and contributes only the directory key. Ordered by ``name_rank``.
    """
    out: dict[str, list[str]] = {}
    grouped = usage.by_protocol()
    for rel in sorted(grouped, key=name_rank):
        out[rel] = usage.coords_of(rel)
        leaves = grouped[rel]
        if len(leaves) == 1 and leaves[0].mechanism is None:
            continue
        for leaf in leaves:
            out[f"{rel}/{leaf.label}"] = list(leaf.coords)
    return out


def flow_defaults(index: dict[str, list[str]]) -> dict[str, list[str]]:
    """key -> the flow-state coordinates it sits at by default.

    An axis a protocol never mentions is at its flow state, which is what
    ``resolve.world_of`` assumes when it defaults an unmentioned dimension.
    Read off the absence of a declaration, so it is weaker evidence than a
    declaration and the page draws it weaker.
    """
    flow = {**FLOW_STATE, **WORLD_FLOW_STATE}
    axes = list(WORLD_AXES) + list(VOCAB.axes())
    out: dict[str, list[str]] = {}
    for name, coords in index.items():
        touched = {c.split(".")[0] for c in coords}
        out[name] = [f"{a}.{flow[a]}" for a in axes if a not in touched]
    return out


def conflict_map() -> dict[str, list[dict]]:
    """coordinate -> the coordinates it can contradict, symmetric.

    One side declaring is enough for the claims gate, which asks both
    directions, so both sides are recorded here too. Whether two concrete
    points really collide depends on their targets; what is drawn is the pair
    being capable of it."""
    out: dict[str, list[dict]] = {}
    for (axis, sub), cls in REALIZERS.items():
        mine = f"{axis}.{sub}"
        for other in cls.conflicts_with:
            for a, b in ((mine, other), (other, mine)):
                row = {"other": b, "label": f"{a} ⇄ {b}: cannot both hold"}
                if all(r["other"] != b for r in out.setdefault(a, [])):
                    out[a].append(row)
    return out


def _subtype_div(axis: str, sub: str, conflicts: dict,
                 usage: CorpusUsage) -> str:
    cls = REALIZERS[(axis, sub)]
    coord = f"{axis}.{sub}"
    tags = []
    if FLOW_STATE.get(axis) == sub:
        tags.append('<span class="tag flow">flow state</span>')
    if VOCAB.is_stub(axis, sub):
        tags.append('<span class="tag stub">stub</span>')
    if VOCAB.is_structural(axis, sub):
        tags.append('<span class="tag">structural</span>')
    stronger = ""
    if cls.stronger_than:
        stronger = ('<span class="stronger">≻ '
                    + _esc(", ".join(cls.stronger_than)) + "</span>")
    params = VOCAB.params(axis, sub)
    meta = ""
    if params:
        fields = ", ".join(
            f"{f}:{s['kind']}" + ("" if s.get("required", True) else "?")
            for f, s in params.items())
        meta = f'<div class="meta">target: {_esc(fields)}</div>'
    writings = ""
    if cls.writings:
        selector, mapping = "value lifetime", cls.writings_by_lifetime
        chips = " · ".join(
            f'{_esc(v)}→<span class="tag">{_esc(f)}</span>'
            for v, f in mapping.items())
        writings = (f'<div class="writings">writing decided by '
                    f"<b>{_esc(selector)}</b>: {chips}</div>")
    marks = []
    for row in conflicts.get(coord, []):
        marks.append(f'<span class="conf">✕ {_esc(row["other"])}</span>')
    reqs = f'<div class="reqs">{"".join(marks)}</div>' if marks else ""
    source = _usage_line(usage, coord)
    stub_cls = " stub" if VOCAB.is_stub(axis, sub) else ""
    return (f'<div class="st{stub_cls}" id="st-{_esc(axis)}-{_esc(sub)}" '
            f'data-coord="{_esc(coord)}">'
            f'<div class="row"><span class="name">{_esc(sub)}</span>'
            f'{"".join(tags)}{stronger}</div>'
            f'<div class="desc">{_esc(VOCAB.description(axis, sub))}</div>'
            f"{meta}{writings}{reqs}{source}</div>")


def _world_subtype_div(axis: str, sub: str, usage: CorpusUsage) -> str:
    """One world subtype card: the flow state, the target params and where it
    was modelled. A world axis's subtypes are alternative domains, so there is
    no ladder and no conflict to draw."""
    coord = f"{axis}.{sub}"
    tags = ('<span class="tag flow">flow state</span>'
            if WORLD_VOCAB.is_noop(axis, sub) else "")
    params = WORLD_VOCAB.params(axis, sub)
    meta = ""
    if params:
        fields = ", ".join(
            f"{f}:{spec['kind']}" + ("" if spec.get("required", True) else "?")
            for f, spec in params.items())
        meta = f'<div class="meta">target: {_esc(fields)}</div>'
    source = _usage_line(usage, coord)
    return (f'<div class="st" id="st-{_esc(axis)}-{_esc(sub)}" '
            f'data-coord="{_esc(coord)}">'
            f'<div class="row"><span class="name">{_esc(sub)}</span>{tags}</div>'
            f'<div class="desc">{_esc(WORLD_VOCAB.description(axis, sub))}</div>'
            f"{meta}{source}</div>")


def _world_card(axis: str, usage: CorpusUsage) -> str:
    key = WORLD_INSTANCE_KEY.get(axis)
    obj = ", ".join(key) if key else "the world as a whole"
    subs = "".join(_world_subtype_div(axis, s, usage)
                   for s in WORLD_SUBTYPES[axis])
    return (f'<div class="axis world" id="ax-{_esc(axis)}">'
            f'<div class="axhead"><span class="name">{_esc(axis)}</span>'
            f'<span class="tag world">world</span>'
            f'<span class="obj">obj: {_esc(obj)}</span></div>'
            f'<div class="sts">{subs}</div>'
            f'<div class="railnote">applied once per run · never a scenario '
            f"condition</div></div>")


def _world_band(usage: CorpusUsage) -> str:
    """The three world axes in build order, arrows between them. The order
    carries meaning: population reshapes the main process, and the role and
    session writings land on what it left."""
    cards = [_world_card(a, usage) for a in WORLD_AXES]
    return ('<div class="band">'
            + '<span class="arrow">→</span>'.join(cards) + "</div>")


def _axis_card(axis: str, conflicts: dict, usage: CorpusUsage) -> str:
    subs = "".join(_subtype_div(axis, s, conflicts, usage)
                   for s in VOCAB.dimension_values(axis))
    return (f'<div class="axis" id="ax-{_esc(axis)}">'
            f'<div class="axhead"><span class="name">{_esc(axis)}</span>'
            f'<span class="obj">obj: {_esc(VOCAB.obj_of(axis))}</span></div>'
            f'<div class="sts">{subs}</div>'
            f'<div class="railnote">↓ subtypes run weakest to strongest</div></div>')


def _usage_line(usage: CorpusUsage, coord: str) -> str:
    """How much of the corpus stands on this rung, as the card's last line.

    A share rather than a bare count. A flow state reads 0: an unmentioned axis
    sits there without declaring it, which is what the dashed default boxes
    show. Empty string when no corpus was scanned.
    """
    if not usage.roots:
        return ""
    n = usage.count_of(coord)
    cls = "meta" if n else "meta none"
    return (f'<div class="{cls}">corpus: used in {n} of '
            f"{len(usage.leaves)}</div>")


def _pi_class(coord: str) -> str:
    """The panel item's extra classes. World coordinates are branched on first:
    asking the object-level vocabulary about a world axis is a KeyError, the two
    layers being two separate vocabularies."""
    axis, sub = coord.split(".")
    if axis in WORLD_SUBTYPES:
        return " world"
    return " stub" if VOCAB.is_stub(axis, sub) else ""


def _chips(coords) -> str:
    return "".join(f'<span class="pi{_pi_class(c)}" data-st="{_esc(c)}">'
                   f"{_esc(c)}</span>" for c in coords)


def _panel(index: dict[str, list[str]], usage: CorpusUsage) -> str:
    """The protocol panel: one row per protocol directory, folded, opening to
    the mechanisms under it, which stay individually clickable once open.
    """
    if not usage.roots:
        return ('<aside class="side"><h3>protocols</h3>'
                '<div class="hint">No corpus was scanned, so this panel is '
                "empty. The page is generated from the class declarations and "
                "renders without a corpus; point <code>paths.lib_root</code> "
                "at a checkout to measure what actually declares each "
                "subtype.</div></aside>")
    grouped = usage.by_protocol()
    rows = []
    for rel in (k for k in index if k in grouped):
        leaves = grouped[rel]
        subs = [k for k in (f"{rel}/{leaf.label}" for leaf in leaves)
                if k in index]
        if not subs:
            # One protocol, one assumptions.json: the row is the declaration,
            # so its subtypes hang on it directly.
            rows.append(
                f'<button class="p" data-p="{_esc(rel)}">{_esc(rel)}'
                f'<span class="n"> · {len(index[rel])} subtypes</span>'
                "</button>" + _chips(index[rel]))
            continue
        # A directory of sub-protocols declares nothing of its own: its row
        # carries the count and lights the union when clicked, but the subtypes
        # hang one level down, on the sub-protocol whose file names them.
        rows.append(
            f'<button class="p dir" data-p="{_esc(rel)}">{_esc(rel)}'
            f'<span class="n"> · {len(subs)} subprotocols</span></button>')
        rows.append(
            f'<div class="fold"><button class="more" data-fold="{_esc(rel)}">'
            f"▸ expand</button>"
            f'<div class="mechs" data-for="{_esc(rel)}" hidden>'
            + "".join(
                f'<button class="p mech" data-p="{_esc(k)}">'
                f'{_esc(k.rsplit("/", 1)[-1])}'
                f'<span class="n"> · {len(index[k])}</span></button>'
                + _chips(index[k])
                for k in subs)
            + "</div></div>")
    scanned = ", ".join(usage.roots)
    return ('<aside class="side"><h3>protocols</h3>'
            '<div class="hint">what each protocol directory was actually '
            "modelled with, measured off the corpus's own assumptions.json "
            "files — nothing here is hand-written. Subtypes hang on whatever "
            "declared them: on the row itself when the protocol is one file, "
            "and on the sub-protocol inside when it is a directory of them "
            "(open it). Clicking a directory row lights the union of what its "
            "sub-protocols use; clicking a subtype boxes everything that "
            "declares it. World coordinates are marked in amber."
            f'<br>scanned: <code>{_esc(scanned)}</code> · '
            f"{len(usage.leaves)} assumption files in {len(grouped)} "
            "directories"
            + (f' · <b>{len(usage.unreadable)} unreadable</b>'
               if usage.unreadable else "")
            + "</div>"
            + "".join(rows) + "</aside>")


def render_kb_html(theme: str | None = None, corpus_roots=()) -> str:
    """Render the whole page as one HTML string.

    ``theme`` stamps ``data-theme`` on the root element; the CLI passes nothing
    and the page follows the OS. ``corpus_roots`` are the directories to
    measure protocol usage in; none given, or none that exist, renders the
    vocabulary with an empty protocol panel."""
    usage = scan_usage(corpus_roots)
    conflicts = conflict_map()
    index = protocol_index(usage)
    world_band = _world_band(usage)
    groups: dict[str, list[str]] = {}
    for axis in VOCAB.axes():
        groups.setdefault(VOCAB.obj_of(axis), []).append(axis)
    group_divs = "".join(
        f'<div class="group"><div class="gname">obj: {_esc(obj)}</div>'
        f'<div class="cards">'
        f'{"".join(_axis_card(a, conflicts, usage) for a in axes)}</div></div>'
        for obj, axes in groups.items())
    legend = (
        '<div class="legend">'
        '<span><span class="tag world">world</span> world-level assumption '
        '(the world section of assumptions.json)</span>'
        '<span><span class="tag flow">flow state</span> what an unmentioned '
        'axis means (noop)</span>'
        '<span><span class="tag stub">stub</span> declared, not implemented'
        "</span>"
        '<span>≻ directly stronger than (the axis partial order)</span>'
        '<span style="color:var(--hit)">✕ conflicts_with</span>'
        '<span><span style="border:1px solid var(--hit);border-radius:4px;'
        'padding:0 4px">declared</span> vs <span style="border:1px dashed '
        'var(--hit);border-radius:4px;padding:0 4px">at the flow state by '
        'default</span> (the axis is never mentioned)</span>'
        '<span>click a subtype or a protocol to light the relation; click '
        "again, or press Esc, to clear</span>"
        "</div>")
    themed = f' data-theme="{_esc(theme)}"' if theme else ""
    data = (f"const USES = {json.dumps(index)};\n"
            f"const DEF = {json.dumps(flow_defaults(index))};\n"
            f"const CONF = {json.dumps(conflicts)};")
    return f"""<!doctype html>
<html lang="en"{themed}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orrery assumption vocabulary {VOCAB_VERSION}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Orrery assumption vocabulary</h1>
<div class="sub">vocabulary {VOCAB_VERSION} · the axes and subtypes from the
realizer class declarations, the protocol usage measured off the corpus. The
coordinate is axis.subtype; the obj grouping is navigation only.</div>
{legend}
<div class="wrap">
<div class="main">
<h2>world assumptions<span class="note">what the analysed world is made of —
declared in the world section of assumptions.json, applied once by build_world
in the order below (it carries meaning), never a scenario condition</span></h2>
{world_band}
<h2>object-level axes<span class="note">a predicate on one object the model
names; disjoint write sets, so the apply order carries no meaning; grouped by
obj</span></h2>
<div class="groups">{group_divs}</div>
</div>
{_panel(index, usage)}
</div>
<script>{data}</script>
<script>{_JS}</script>
</body>
</html>
"""


def write_kb_html(path: Path, corpus_roots=()) -> Path:
    path.write_text(render_kb_html(corpus_roots=corpus_roots), encoding="utf-8")
    return path
