"""What a wheel actually contains, by building one and looking inside.

The package is more than its Python: prompts, realizer and builder rules, the
primitive library, the console's assets and vendored Vue. Nothing imports those
files, and an editable install reads the working tree, so a wheel can lose one
for months with every checkout still looking fine. The ``package-data`` patterns
are no substitute: setuptools in pyproject mode defaults
``include-package-data`` to true and sweeps the directories itself.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "orrery"


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> zipfile.ZipFile:
    """A wheel built from this checkout, as ``pip install .`` would build it."""
    out = tmp_path_factory.mktemp("wheel")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(out),
         str(ROOT)],
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        pytest.skip(f"could not build a wheel here: {proc.stderr.strip()[-300:]}")
    built = sorted(out.glob("orrery-*.whl"))
    if not built:
        pytest.skip("pip built no orrery wheel")
    return zipfile.ZipFile(built[-1])


def _packaged(wheel: zipfile.ZipFile) -> set[str]:
    return {name[len("orrery/"):] for name in wheel.namelist()
            if name.startswith("orrery/") and not name.endswith("/")}


def _in_tree(pattern: str) -> set[str]:
    return {str(p.relative_to(PKG).as_posix()) for p in PKG.rglob(pattern)
            if p.is_file() and "__pycache__" not in p.parts}


def test_the_files_read_while_importing_are_in_the_wheel(wheel) -> None:
    """The rules every realizer and builder is checked against at import.

    ``nodes/world/builders/__init__`` and the realizer registries walk their own
    directories the moment they are imported and raise on a subtype whose rules
    are missing, so a wheel without these files does not start.
    """
    rules = _in_tree("rules*.sys.md")
    assert rules, "no rules.sys.md in the tree; this test is measuring nothing"
    assert not (rules - _packaged(wheel)), sorted(rules - _packaged(wheel))


def test_the_prompt_preview_ships_its_fixture(wheel) -> None:
    """`orrery prompt` renders from a protocol directory inside the package.

    Whole, not mostly: ``render.py`` reads a ProVerif model out of the fixture
    while being imported, so a missing .pv is the command dead rather than a
    preview short of one page.
    """
    fixture = _in_tree("utils/prompts/fixture/**/*")
    assert fixture, "no prompt fixture in the tree; this test is measuring nothing"
    assert any(f.endswith(".pv") for f in fixture), "fixture lost its model"
    assert not (fixture - _packaged(wheel)), sorted(fixture - _packaged(wheel))


def test_the_console_ships_whole(wheel) -> None:
    """Every file the page loads, the vendored ones included.

    The console has no build step and no CDN: Vue, Pico and both fonts are
    served from this directory, and a wheel that dropped them renders a blank
    page with failed requests and nothing in the terminal.
    """
    static = {s for s in (
        str(p.relative_to(PKG).as_posix())
        for p in (PKG / "web" / "static").rglob("*") if p.is_file())
        if not s.endswith(".gitkeep")}
    assert {s for s in static if "vendor/" in s}, "no vendored assets in the tree"
    assert not (static - _packaged(wheel)), sorted(static - _packaged(wheel))


def test_the_prompts_and_the_library_ship(wheel) -> None:
    """What every run reads: the step prompts and the primitive library.

    Not read at import, so their absence is quieter: a run gets as far as its
    first model call and fails there.
    """
    for pattern in ("prompts/*.md", "*.yaml"):
        want = {f for f in _in_tree(pattern) if f.startswith(("kb/", "nodes/",
                                                             "pipeline/",
                                                             "expert/"))}
        assert want, f"nothing in the tree matches {pattern}"
        assert not (want - _packaged(wheel)), sorted(want - _packaged(wheel))
