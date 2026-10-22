"""The config as the console renders and edits it: what leaks and what may be
written back."""

from pathlib import Path

import pytest
import yaml

from orrery.api import settings


def _config(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({
        "llm": {"backend": "remote-openai-compatible",
                "profiles": {"remote-openai-compatible": {
                    "api_key": "sk-relay-secret", "url": "https://relay/v1",
                    "model": "glm-4.5-flash",
                    "extra_headers": {"Authorization": "Bearer relay-token",
                                      "X-Tenant": "acme"}}}},
        "proverif": {"executable": "/bin/true"},
    }), encoding="utf-8")
    return p


def test_relay_headers_never_leave_the_server(tmp_path):
    """A relay header is a credential as often as not, and the lifted copy on
    llm.extra_headers is not a knob: walked, it came out as editable rows
    carrying the value in clear."""
    cfg = _config(tmp_path)
    rows = {k["path"]: k for k in settings.describe(cfg, tmp_path)["knobs"]}
    assert not any(p.startswith("llm.extra_headers") for p in rows), sorted(rows)
    header = rows["llm.profiles.remote-openai-compatible.extra_headers.Authorization"]
    assert header["secret"] and header["value"] == "(set)"
    assert "relay-token" not in settings.as_yaml(cfg)
    assert "sk-relay-secret" not in settings.as_yaml(cfg)


def test_the_lifted_reading_cannot_be_written_back(tmp_path):
    """llm.extra_headers.* is the loader's reading of the live slot; stored,
    it would sit on top of every slot and silently win over the profile."""
    cfg = _config(tmp_path)
    with pytest.raises(ValueError, match="where the live backend's slot is"):
        settings.store(cfg, "llm.extra_headers.X-Relay", "1")
    settings.store(cfg, "llm.profiles.remote-openai-compatible.extra_headers.X-Relay", "1")
    stored = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "extra_headers" not in stored["llm"]
    assert stored["llm"]["profiles"]["remote-openai-compatible"]["extra_headers"]["X-Relay"] == "1"


def test_a_run_name_that_walks_is_not_a_run(tmp_path, monkeypatch):
    """``..`` joins to the work root and ``.`` to a protocol directory; either
    lets a per-run route read past the run it names."""
    from fastapi import HTTPException

    from orrery.web import server
    work = tmp_path / "wr"
    (work / "NSPK" / "NSPK01").mkdir(parents=True)
    monkeypatch.setattr(server.app.state, "work_root", work)
    assert server._run_dir("NSPK01") == work / "NSPK" / "NSPK01"
    for name in ("..", ".", "latest", "_ground_truth", "NSPK/NSPK01"):
        with pytest.raises(HTTPException) as e:
            server._run_dir(name)
        assert e.value.status_code == 404


def test_a_deployment_can_fix_the_machine_knobs(tmp_path, monkeypatch):
    """The container image fixes the solver it ships and the run directory on
    its volume. The page draws those rows locked and refuses to write them;
    everything else stays editable, and a checkout with nothing named locks
    nothing."""
    cfg = _config(tmp_path)
    rows = {k["path"]: k for k in settings.describe(cfg, tmp_path)["knobs"]}
    assert not rows["proverif.executable"]["locked"]

    monkeypatch.setenv("ORRERY_READ_ONLY", "proverif.executable, paths.work_root")
    rows = {k["path"]: k for k in settings.describe(cfg, tmp_path)["knobs"]}
    assert rows["proverif.executable"]["locked"] and rows["paths.work_root"]["locked"]
    assert not rows["llm.backend"]["locked"]
    with pytest.raises(ValueError, match="fixed by this deployment"):
        settings.store(cfg, "proverif.executable", "/bin/sh")
    settings.store(cfg, "llm.backend", "remote-claude")          # still editable


def test_a_misspelt_lock_is_loud(tmp_path, monkeypatch):
    monkeypatch.setenv("ORRERY_READ_ONLY", "proverif.exe")
    with pytest.raises(ValueError, match="not config keys"):
        settings.describe(_config(tmp_path), tmp_path)
