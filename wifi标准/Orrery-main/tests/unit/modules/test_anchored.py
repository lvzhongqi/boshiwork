"""The scenario stage's anchored edit language: anchor uniqueness, whitespace
tolerance and sequential application against the current text are each pinned
by a case here."""
import pytest

from orrery.modules.pvtext.anchored import Edit, EditError, apply_edits

PV = """\
free c: channel.
free channel_A_S: channel.

let processA(A: host, B: host, Ksa: key) =
  out(channel_A_S, (A, B));
  in(channel_S_A, response: bitstring);
  let (B_recv: host, Kab: key) = sdec(response, Ksa) in
  if B_recv = B then
    out(channel_A_B, ticket);
  0.

let processS(S: host, Ksa: key, Ksb: key) =
  in(channel_A_S, request: bitstring);
  new Kab: key;
  out(channel_S_A, response);
  0.

process
  new A: host;
  (!processA(A, B, Ksa)) | (!processS(S, Ksa, Ksb))
"""


def test_insert_after():
    out = apply_edits(PV, [Edit(anchor="new Kab: key;", position="after",
                                text="  event kab_made(Kab);")])
    assert "new Kab: key;\n  event kab_made(Kab);\n  out(channel_S_A" in out


def test_insert_before():
    out = apply_edits(PV, [Edit(anchor="if B_recv = B then", position="before",
                                text="  event got_ticket(B_recv);")])
    assert "  event got_ticket(B_recv);\n  if B_recv = B then" in out


def test_replace():
    out = apply_edits(PV, [Edit(anchor="new Kab: key;", position="replace",
                                text="in(c, Kab: key);")])
    assert "new Kab: key;" not in out
    assert "in(c, Kab: key);" in out


def test_delete_via_empty_replace():
    out = apply_edits(PV, [Edit(anchor="  if B_recv = B then\n", position="replace",
                                text="")])
    assert "B_recv = B" not in out
    assert "out(channel_A_B, ticket);" in out     # neighbours intact


def test_multiline_anchor():
    anchor = "  in(channel_A_S, request: bitstring);\n  new Kab: key;"
    out = apply_edits(PV, [Edit(anchor=anchor, position="replace",
                                text="  in(channel_A_S, request: bitstring);\n  in(c, Kab: key);")])
    assert "in(c, Kab: key);" in out
    assert "new Kab: key;" not in out


def test_sequential_edits_apply_to_current_text():
    out = apply_edits(PV, [
        Edit(anchor="new Kab: key;", position="replace", text="in(c, Kab: key);"),
        Edit(anchor="in(c, Kab: key);", position="after", text="  event swapped;"),
    ])
    assert "in(c, Kab: key);\n  event swapped;" in out


def test_conflicting_edits_fail_loudly():
    # The first edit consumes the line, so the second's anchor no longer exists.
    with pytest.raises(EditError, match="edit 2"):
        apply_edits(PV, [
            Edit(anchor="new Kab: key;", position="replace", text="in(c, Kab: key);"),
            Edit(anchor="new Kab: key;", position="after", text="  event x;"),
        ])


def test_ambiguous_anchor_rejected():
    with pytest.raises(EditError, match="occurs 2 times"):
        apply_edits(PV, [Edit(anchor="  0.", position="after", text="ignored")])


def test_not_found_suggests_closest_line():
    with pytest.raises(EditError, match="closest real line"):
        apply_edits(PV, [Edit(anchor="new Kab: keu;", position="after", text="x")])


def test_whitespace_drift_tolerated_when_unique():
    # The model quoted with different indentation; content is identical.
    out = apply_edits(PV, [Edit(anchor="new Kab: key;", position="after",
                                text="  event drifted;")])
    exact = apply_edits(PV, [Edit(anchor="  new Kab: key;", position="after",
                                  text="  event drifted;")])
    assert out == exact


def test_normalised_match_still_rejects_ambiguity():
    with pytest.raises(EditError):
        apply_edits(PV, [Edit(anchor="0.", position="after", text="x")])


def test_empty_anchor_rejected():
    with pytest.raises(EditError, match="anchor is empty"):
        apply_edits(PV, [Edit(anchor="   ", position="after", text="x")])


def test_unknown_position_rejected():
    with pytest.raises(EditError, match="unknown position"):
        apply_edits(PV, [Edit(anchor="new Kab: key;", position="around", text="x")])
