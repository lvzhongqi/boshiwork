"""The container image's own files stay loadable as the engine changes.

The image seeds each workspace with docker/config.docker.yaml and locks knobs
named in the Dockerfile's ORRERY_READ_ONLY. Both are checked against the
engine's config schema here, since the loader refuses a key it does not know
and a stale seed would stop every new container at its first start. The build
context is checked too: config.yaml holds an API key and must never be sent to
a builder.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from orrery.api import settings
from orrery.pipeline.config import load_config

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_the_seed_config_loads_and_keeps_everything_on_the_volume() -> None:
    seed = yaml.safe_load((ROOT / "docker" / "config.docker.yaml").read_text(encoding="utf-8"))
    cfg = load_config(seed, require=False)
    for key in ("work_root", "lib_root", "playback_root"):
        assert cfg["paths"][key].startswith("/work/"), key
    assert cfg["proverif"]["executable"] == "/usr/local/bin/proverif"


def test_the_locked_knobs_are_config_keys(monkeypatch) -> None:
    m = re.search(r"ORRERY_READ_ONLY=([\w.,]+)", DOCKERFILE)
    assert m, "the Dockerfile sets no ORRERY_READ_ONLY"
    monkeypatch.setenv("ORRERY_READ_ONLY", m.group(1))
    locked = settings._read_only()                  # raises on an unknown key
    assert "proverif.executable" in locked and "paths.work_root" in locked


def test_the_build_context_is_an_allowlist_without_secrets() -> None:
    """At the context root, the one place every builder reads it."""
    rules = [ln.strip() for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    assert rules[0] == "*", "the build context must start from nothing"
    allowed = [r[1:] for r in rules if r.startswith("!")]
    for secret in ("config.yaml", "CLAUDE.local.md", "AGENTS.local.md"):
        assert secret not in allowed
    assert not any(a.startswith(("runs", "a_runs", "experiments", "tests"))
                   for a in allowed)


def test_the_package_is_installed_the_standard_way() -> None:
    """A regular install into a virtual environment, with the source tree left
    in its build stage; ORRERY_HOME tells the installed copy where its data is."""
    assert "pip install -e" not in DOCKERFILE and "--editable" not in DOCKERFILE
    assert "ORRERY_HOME=/work" in DOCKERFILE


def test_proverif_ships_with_its_license_and_source() -> None:
    """GPL-2.0 asks a binary copy to come with its corresponding source."""
    assert "install -m 0644 LICENSE /out/doc/LICENSE" in DOCKERFILE
    assert "/usr/local/share/doc/proverif/" in DOCKERFILE
    assert re.search(r"PROVERIF_SHA256=[0-9a-f]{64}\b", DOCKERFILE)


def test_the_entrypoint_is_executable() -> None:
    assert (ROOT / "docker" / "entrypoint.sh").stat().st_mode & 0o111
