"""Tests for the kb graph page, which renders the whole vocabulary: every axis
and subtype gets an element, every conflict edge is drawn both ways, and the
writings mapping ships with the selector that decides it. Completeness is the
contract, since this page is the reading surface for the vocabulary."""

import json
import re

import pytest

from orrery.api.corpus_usage import scan_usage
from orrery.api.kb_graph import render_kb_html
from orrery.nodes.apply.realizers import REALIZERS, VOCAB
from orrery.nodes.world.builders import (
    WORLD_AXES,
    WORLD_FLOW_STATE,
    WORLD_SUBTYPES,
)


def _corpus(tmp_path, **targets):
    """A corpus root holding one protocol per keyword: the keyword is a
    ``family/protocol`` path, the value the entries its assumptions.json
    declares. Synthetic, so the tests do not track LIB's current contents.
    """
    for rel, entries in targets.items():
        home = tmp_path / rel
        (home / "claims").mkdir(parents=True)
        (home / "claims" / "assumptions.json").write_text(
            json.dumps({"vocab_version": "2.2.0", **entries}), encoding="utf-8")
    return [tmp_path]


@pytest.fixture
def corpus(tmp_path):
    """Two protocol directories: one plain, one with mechanisms under it."""
    root = tmp_path / "corpus"
    _corpus(root, **{
        "academic/NSPK": {
            "world": [], "fixed": [],
            "variable": [{"id": "v", "axis": "data", "target": {"of": "K"},
                          "subtypes": ["none", "disclosed"]}]},
    })
    for i, sub in enumerate(("mech-1", "mech-2")):
        home = root / "ISO/9798-2" / "subprotocols" / sub / "claims"
        home.mkdir(parents=True)
        home.joinpath("assumptions.json").write_text(json.dumps({
            "vocab_version": "2.2.0",
            "world": [{"id": "w", "axis": "population", "subtype": "unbounded"}],
            "fixed": [{"id": "f", "axis": "channel",
                       "target": {"link": ["A", "B"]},
                       "subtype": "secure" if i else "authentic"}],
            "variable": [],
        }), encoding="utf-8")
    return [root]


def test_kb_graph_is_complete(corpus):
    page = render_kb_html(corpus_roots=corpus)
    for axis in VOCAB.axes():
        assert f'id="ax-{axis}"' in page, axis
        for sub in VOCAB.dimension_values(axis):
            assert f'id="st-{axis}-{sub}"' in page, (axis, sub)
    # every relation the page can light ships in its data: the conflicts, which
    # are symmetric so the undeclared side lights too, and who declares what
    from orrery.api.kb_graph import conflict_map, protocol_index

    conf, uses = conflict_map(), protocol_index(scan_usage(corpus))
    for (axis, sub), cls in REALIZERS.items():
        coord = f"{axis}.{sub}"
        assert f'data-coord="{coord}"' in page, coord
        for other in cls.conflicts_with:
            # declared one way, drawn both ways
            assert any(e["other"] == other for e in conf[coord]), (coord, other)
            assert any(e["other"] == coord for e in conf[other]), (other, coord)
    # the protocol panel: one entry per protocol, each listing its subtypes
    for name, coords in uses.items():
        assert f'data-p="{name}"' in page, name
        for c in coords:
            assert f'data-st="{c}"' in page, (name, c)
    # lifetime-dependent writing mappings render as declared data; semantic
    # realizers such as admission.open have one sighted prompt and no selector
    for (axis, sub), cls in REALIZERS.items():
        if cls.writings:
            selector, mapping = "value lifetime", cls.writings_by_lifetime
            assert selector in page, (axis, sub)
            for value, form in mapping.items():
                assert form in page and value in page, (axis, sub, form)
    # the world assumptions are a separate vocabulary on the same page, ahead
    # of the object-level axes and in build order
    assert "world section" in page       # and the page says where they live
    for axis in WORLD_AXES:
        assert f'id="ax-{axis}"' in page, axis
        for sub in WORLD_SUBTYPES[axis]:
            assert f'id="st-{axis}-{sub}"' in page, (axis, sub)
            assert f'data-coord="{axis}.{sub}"' in page, (axis, sub)
    assert page.index('<div class="band">') < page.index('<div class="groups">')
    assert [page.index(f'id="ax-{a}"') for a in WORLD_AXES] == sorted(
        page.index(f'id="ax-{a}"') for a in WORLD_AXES)   # build order, as laid out


def test_kb_graph_is_self_contained():
    """One file, no external fetches — the page must open offline."""
    page = render_kb_html()
    for marker in ("http://", "https://", "src=", "@import"):
        assert marker not in page.replace("http://www.w3.org/2000/svg", ""), marker


def test_a_flow_state_lights_the_protocols_that_default_to_it(corpus):
    """An axis a protocol never mentions is at its flow state, and a corpus
    records only what it uses. The page ships those defaults as well, drawn
    weaker than a declaration because they are read off an absence."""
    from orrery.api.kb_graph import flow_defaults, protocol_index
    from orrery.nodes.apply.realizers import FLOW_STATE

    idx = protocol_index(scan_usage(corpus))
    dflt = flow_defaults(idx)
    flow = {**FLOW_STATE, **WORLD_FLOW_STATE}
    assert set(dflt) == set(idx)                     # one entry per protocol
    for name, coords in idx.items():
        touched = {c.split(".")[0] for c in coords}
        for coord in dflt[name]:
            axis, sub = coord.split(".")
            assert axis not in touched, (name, coord)   # never both
            assert flow[axis] == sub, coord             # only flow states
        # every axis is accounted for, as declared or as default, world axes
        # included: an unmentioned world axis is at its flow state too
        assert (touched | {c.split(".")[0] for c in dflt[name]}
                == set(VOCAB.axes()) | set(WORLD_AXES))


def test_a_world_declaration_is_indexed_like_an_assumption(corpus):
    """A world entry sits in the same assumptions.json as an assumption and is
    as much part of what the protocol was modelled with, so one index carries
    both and a click lights both halves at once."""
    from orrery.api.kb_graph import protocol_index

    idx = protocol_index(scan_usage(corpus))
    assert "population.unbounded" in idx["ISO/9798-2"]
    assert "population.unbounded" in idx["ISO/9798-2/mech-1"]


def test_the_panel_folds_mechanisms_under_their_protocol_directory(corpus):
    """A standard part with N mechanisms is one row, not N: N top-level rows
    would give it N times the weight of a protocol that ships a single target.
    The mechanisms stay reachable as their own keys."""
    from orrery.api.kb_graph import protocol_index

    idx = protocol_index(scan_usage(corpus))
    assert set(idx) == {"academic/NSPK", "ISO/9798-2",
                        "ISO/9798-2/mech-1", "ISO/9798-2/mech-2"}
    # the directory key carries the union over its mechanisms, each mechanism
    # its own; a one-file protocol does not fold open to a copy of itself
    assert idx["ISO/9798-2"] == ["channel.authentic", "channel.secure",
                                 "population.unbounded"]
    assert idx["ISO/9798-2/mech-1"] == ["channel.authentic",
                                        "population.unbounded"]
    assert "academic/NSPK/NSPK" not in idx
    page = render_kb_html(corpus_roots=corpus)
    # the fold names what it opens to in the corpus's word, not the panel's
    assert "2 subprotocols" in page and "2 protocols" not in page


def test_subtypes_hang_on_whatever_declared_them(corpus):
    """One assumptions.json is one declaration, so that is what wears the
    subtypes: a single-file protocol on its own row, a mechanism on its own row
    inside the fold. A directory declares nothing, so its row wears none.
    """
    page = render_kb_html(corpus_roots=corpus)

    def chips_after(marker: str) -> list[str]:
        """The data-st chips between one row button and the next button."""
        rest = page[page.index(marker) + len(marker):]
        rest = rest.split("<button")[0]
        return re.findall(r'data-st="([^"]+)"', rest)

    # the single-file protocol wears its own
    assert chips_after('data-p="academic/NSPK"') == ["data.disclosed",
                                                     "data.none"]
    # the directory wears none, and is marked as the container it is
    assert chips_after('data-p="ISO/9798-2"') == []
    assert 'class="p dir" data-p="ISO/9798-2"' in page
    # each mechanism wears exactly what its own file declares: mech-1 has
    # channel.authentic, mech-2 has channel.secure, and neither has both
    assert chips_after('data-p="ISO/9798-2/mech-1"') == ["channel.authentic",
                                                         "population.unbounded"]
    assert chips_after('data-p="ISO/9798-2/mech-2"') == ["channel.secure",
                                                         "population.unbounded"]
    # the union is still reachable: it is what the directory row's click
    # lights, which is a query rather than a declaration to display
    from orrery.api.kb_graph import protocol_index
    assert protocol_index(scan_usage(corpus))["ISO/9798-2"] == [
        "channel.authentic", "channel.secure", "population.unbounded"]


def test_a_subtype_states_how_much_of_the_corpus_stands_on_it(corpus):
    """The count says how much of the corpus stands on a rung, and zero
    distinguishes a rung nothing uses from one nobody wrote down. It is stated
    as a share, in neither of the two words the page has already spent:
    ``target`` belongs to the vocabulary card and ``protocol`` to the panel.
    """
    page = render_kb_html(corpus_roots=corpus)
    assert "corpus: used in 2 of 3" in page     # population.unbounded
    assert "corpus: used in 1 of 3" in page     # channel.authentic
    assert "corpus: used in 0 of 3" in page     # nothing declares it
    for spent in ("targets", "corpus: 2 protocols"):
        assert spent not in page, spent


def test_no_corpus_still_renders_the_vocabulary(tmp_path):
    """The corpus is an optional dependency: a checkout without one renders
    the whole vocabulary and an empty panel, rather than failing."""
    page = render_kb_html(corpus_roots=[tmp_path / "not-there"])
    for axis in VOCAB.axes():
        for sub in VOCAB.dimension_values(axis):
            assert f'id="st-{axis}-{sub}"' in page, (axis, sub)
    assert "No corpus was scanned" in page
    assert "corpus: " not in page               # no count claimed either way
    assert "target: " in page                   # the vocabulary's own target


def test_clearing_a_selection_removes_the_dashed_boxes_too():
    """One click paints the dashed classes alongside the solid ones (a flow
    state boxes every protocol defaulting to it), so clear() must name them or
    they stay on the protocol names forever."""
    page = render_kb_html()
    start = page.index("function clear()")
    body = page[start:page.index("document.body.classList.remove", start)]
    for cls in ("hit", "pick", "on", "rel", "hl", "def", "dhit"):
        assert f'"{cls}"' in body, cls


def test_the_page_ships_the_defaults_and_draws_them_weaker():
    page = render_kb_html()
    assert "const DEF = {" in page
    assert '.st.def {' in page and '.p.dhit {' in page
    # a declaration and a default must not render identically, or the page
    # claims a record where it only has an absence
    assert "border-style: dashed" in page
