"""How ``orrery/main.py`` answers one condition: a config left unfilled.

Commands that would spend a credential refuse in a sentence; ``config``, whose
job is to report the configuration, reports it and exits 0. What each command
does behind that boundary is tested in the layer it wraps.
"""

from click.testing import CliRunner

from orrery.main import cli

# A config that loads and is still incomplete: a solver path, no key. It is
# passed on the command line so `ensure_config` is never reached; reaching it
# would write a config.yaml into the project root of whoever ran the suite.
_NO_KEY = "proverif:\n  executable: /bin/true\n"


def test_unfilled_config_is_a_sentence_not_a_stack(tmp_path):
    """`run` refuses an unfilled config with a sentence, not a traceback.

    It names the missing key and the config file it read. The batch runner
    drives `run` in a subprocess, so this is also what a batch prints once
    per protocol.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_NO_KEY)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    r = CliRunner().invoke(cli, ["run", "--name", "X", "--dir", str(protocol),
                                 "--config", str(cfg)])
    assert r.exit_code == 1
    assert "Error: required config left unfilled" in r.output
    assert "llm.profiles.remote-openai-responses.api_key" in r.output   # which key
    assert str(cfg.resolve()) in r.output                     # and which file
    assert "Traceback" not in r.output


def test_config_answers_an_incomplete_config(tmp_path):
    """`config` still answers when the configuration is incomplete.

    It is the command somebody runs because the configuration is not working,
    so it prints the state it finds — unfilled values included — and exits 0.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_NO_KEY)
    r = CliRunner().invoke(cli, ["--config", str(cfg), "config"])
    assert r.exit_code == 0
    assert "???" in r.stdout                       # the unfilled value, as itself
    assert "proverif" in r.stdout                  # and the rest of the config
    assert "still unfilled" in r.output            # stated, not left to a scan
    assert "llm.profiles.remote-openai-responses.api_key" in r.output
