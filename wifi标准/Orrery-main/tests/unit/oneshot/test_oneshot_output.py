"""What the one-shot run directory holds: a redacted config.yaml and run.log."""
import asyncio
from types import SimpleNamespace

import yaml

from experiments.oneshot import runner


def test_oneshot_records_redacted_config_and_run_log(tmp_path, monkeypatch,
                                                     capsys):
    config = {
        "llm": {
            "backend": "test",
            "profiles": {
                "test": {"model": "model", "api_key": "top-secret"},
            },
        },
    }
    monkeypatch.setattr(runner, "load_config", lambda *a, **kw: config)

    async def body(*args):
        print("baseline output")
        return 0

    monkeypatch.setattr(runner, "_run_body", body)
    args = SimpleNamespace(
        config="unused.yaml", dir=str(tmp_path / "corpus"),
        subprotocol=None, name="NSPK", out=str(tmp_path / "runs"),
        run_name="NSPK01", backend=None, model=None, overrides=None,
    )

    assert asyncio.run(runner.run(args)) == 0
    run_dir = tmp_path / "runs" / "NSPK" / "NSPK01"
    recorded = yaml.safe_load((run_dir / "config.yaml").read_text())
    assert recorded["llm"]["profiles"]["test"]["api_key"] == "********"
    assert "top-secret" not in (run_dir / "config.yaml").read_text()
    assert "baseline output" in (run_dir / "run.log").read_text()
    assert "baseline output" in capsys.readouterr().out
