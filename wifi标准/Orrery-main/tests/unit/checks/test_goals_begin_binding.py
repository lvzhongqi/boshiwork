"""``goals_begin_binding``: a begin event that binds a received copy its own
body has already settled against a parameter.

Injection binds the received copy in general, but once `if X_recv = X then` sits
above the event every run reaching it holds the two equal. The copy then costs
only position — begin goes at the earliest point where every value is bound, so
it slides below the receive that carries the copy, low enough on IKEv2 that the
query reads false on a protocol that holds.
"""

from orrery.checks.rules.goals import _begin_binding


def _check(pv):
    return _begin_binding({"pv": pv})


_SETTLED = """\
free c: channel.
type host.

let processA(A: host, B: host, TSi: bitstring) =
  in(c, msg: bitstring);
  let (B_recv: host, TSi_recv: bitstring) = msg in
  if B_recv = B then
  if TSi_recv = TSi then
  event begin_g1(B_recv, TSi_recv);
  0.

process new A: host; new B: host; new TSi: bitstring; ( !processA(A, B, TSi) )
"""


def test_a_settled_copy_is_reported():
    r = _check(_SETTLED)
    assert not r.passed
    assert len(r.findings) == 2
    assert any("binds B_recv" in x and "parameter B" in x for x in r.findings)
    assert any("binds TSi_recv" in x and "parameter TSi" in x for x in r.findings)


def test_binding_the_parameter_passes():
    assert _check(_SETTLED.replace("event begin_g1(B_recv, TSi_recv);",
                                   "event begin_g1(B, TSi);")).passed


def test_an_unchecked_copy_is_left_alone():
    """With no check above it the copy is what this run actually had, so
    reporting it would push injection toward the binding that hides an attack."""
    assert _check(_SETTLED.replace("  if B_recv = B then\n", "")).findings == [
        x for x in _check(_SETTLED).findings if "TSi_recv" in x]


def test_a_check_below_the_event_does_not_settle_it():
    """The event fires first, so binding the parameter there would leave an
    honest-valued record behind a run that then stops at the test."""
    moved = _SETTLED.replace(
        "  if B_recv = B then\n  if TSi_recv = TSi then\n  event begin_g1(B_recv, TSi_recv);",
        "  event begin_g1(B_recv, TSi_recv);\n  if B_recv = B then\n  if TSi_recv = TSi then\n  0;")
    assert _check(moved).passed


def test_the_honest_set_test_is_not_a_settling_check():
    """`if xA = A || xA = B then` names the honest principals without pinning
    the copy to one parameter, so it does not settle the copy."""
    pv = _SETTLED.replace("  if B_recv = B then\n", "  if B_recv = A || B_recv = B then\n")
    assert [x for x in _check(pv).findings if "B_recv" in x] == []


def test_end_events_are_not_touched():
    """The asserter's end sits after everything it checks, so a binding there
    costs no position and is out of this check's scope."""
    assert _check(_SETTLED.replace("begin_g1", "end_g1")).passed
