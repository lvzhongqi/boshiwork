"""Unit tests for the five-way classification of a ProVerif run. The OK and
SYNTAX_ERROR cases read real ProVerif 2.05 output from samples/.

TIMEOUT and RESOURCE_LIMIT are outcomes of their own and are never folded into
SYNTAX_ERROR.
"""

from pathlib import Path

from orrery.infra.proverif.outcome import (
    OutcomeKind,
    classify,
    parse_diagnostics,
    parse_verdicts,
)
from orrery.infra.proverif.runner import RawRun

SAMPLES = Path(__file__).parent / "samples"


def _raw(stdout="", stderr="", rc=0, timed_out=False) -> RawRun:
    return RawRun(
        stdout=stdout, stderr=stderr, returncode=rc, duration_s=0.1,
        timed_out=timed_out,
    )


def test_ok_real_nspk_sample():
    stdout = (SAMPLES / "ok_nspk.txt").read_text()
    out = classify(_raw(stdout=stdout, rc=0))
    assert out.kind is OutcomeKind.OK
    # 7 RESULT lines, one of them the secondary ``RESULT (even ...)`` line of an
    # injective query, which is excluded: only 6 main verdicts count.
    assert len(out.verdicts) == 6
    assert all(v.verdict in ("true", "false", "cannot_be_proved")
               for v in out.verdicts)
    # Standard NSPK yields both true and false, because of the Lowe attack.
    kinds = {v.verdict for v in out.verdicts}
    assert "true" in kinds and "false" in kinds
    assert not any(v.query.startswith("(") for v in out.verdicts)


def test_syntax_error_real_sample():
    stdout = (SAMPLES / "syntax_error.txt").read_text()
    out = classify(_raw(stdout=stdout, rc=2))
    assert out.kind is OutcomeKind.SYNTAX_ERROR
    assert out.errors and "syntax" in out.errors[0].lower()
    # ProVerif puts the location on its own line before the message; it has to
    # travel with the error, or the repair round cannot tell which line broke.
    # The file it names does not: see the test after this one.
    assert "line 2" in out.errors[0] and 'File "' not in out.errors[0]


def test_a_host_path_never_reaches_an_error_or_a_warning():
    """ProVerif names the file by the path it was handed: a run directory or a
    temp directory on the host. A repair round never saw the file under that
    name, so only the line and character travel, and a path quoted inside a
    message is cut to its last component."""
    stdout = ('File "/var/folders/ab/T/tmpq1/03_r1_typecheck.pv", line 114, '
              'characters 1-3:\nError: Syntax error.\n'
              'File "/home/u/runs/P/P01/rounds/04_r2_typecheck.pv", line 7, '
              'character 2:\nWarning: identifier k rebound.\n'
              'Error: File "/home/u/lib/extra.pvl" not found\n')
    errors, warnings = parse_diagnostics(stdout, "")
    assert errors == ['line 114, characters 1-3: Error: Syntax error.',
                      'Error: File "extra.pvl" not found']
    assert warnings == ['line 7, character 2: Warning: identifier k rebound.']
    assert not any("/" in e for e in errors + warnings)


def test_timeout_is_not_syntax_error():
    out = classify(_raw(timed_out=True, rc=-1))
    assert out.kind is OutcomeKind.TIMEOUT
    assert out.errors == []          # no error lines are fabricated for a timeout


def test_memory_limit_is_its_own_outcome():
    raw = _raw(stderr="Fatal error: out of memory", rc=-9)
    raw = RawRun(**{**raw.__dict__, "memory_limited": True,
                    "peak_rss_bytes": 9 * 1024 ** 3,
                    "memory_limit_bytes": 8 * 1024 ** 3})
    out = classify(raw)
    assert out.kind is OutcomeKind.RESOURCE_LIMIT
    assert out.kind is not OutcomeKind.SYNTAX_ERROR


def test_solver_limit_on_abnormal_exit():
    out = classify(_raw(stdout="Translating the process into Horn clauses...\n",
                        rc=137))
    assert out.kind is OutcomeKind.SOLVER_LIMIT


def test_typecheck_ok_with_no_queries():
    # A clean exit with no RESULT line is OK carrying empty verdicts.
    out = classify(_raw(stdout="Process 0 (that is, the initial process):\n", rc=0))
    assert out.kind is OutcomeKind.OK
    assert out.verdicts == []


def test_parse_verdicts_cannot_be_proved_and_secondary_lines():
    stdout = (
        "RESULT not attacker(w_secrecy[]) is true.\n"
        "RESULT inj-event(e(x)) ==> inj-event(b(x)) cannot be proved.\n"
        "RESULT (but event(e(x)) ==> event(b(x)) is true.)\n"   # secondary line
    )
    vs = parse_verdicts(stdout)
    assert [v.verdict for v in vs] == ["true", "cannot_be_proved"]
