"""Anchoring reads the model's code, not its prose.

A name occurring only inside a comment anchors to nothing, and an unresolved
name reaches the injection prompt as a hint. The model's own markers are the
exception: an `@orrery-idiom` line is where an identity scope is declared, and
some protocols name their scope there and nowhere else.
"""

from orrery.nodes.claims.node import _model_code


_PV = """\
(* An SA response selects one suite from an offered SA payload. *)
(* @orrery-idiom identity.authenticated_key_binding/v1 scope=peer_auth *)
table peers(host, spkey).

let processInitiator(SAi2: bitstring) =
  out(c, SAi2);
  0.
"""


def _has(text, word):
    import re
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def test_a_name_living_only_in_prose_stops_matching():
    assert _has(_PV, "SA")
    assert not _has(_model_code(_PV), "SA")


def test_a_scope_named_in_a_marker_still_matches():
    """The marker is the model's declaration of the scope, not commentary."""
    assert _has(_model_code(_PV), "peer_auth")
    assert "@orrery-idiom" in _model_code(_PV)


def test_code_is_untouched():
    assert _has(_model_code(_PV), "SAi2")
    assert _has(_model_code(_PV), "processInitiator")


def test_offsets_are_preserved():
    """The result is matched against positions taken from the source, so it
    has to line up character for character."""
    assert len(_model_code(_PV)) == len(_PV)
