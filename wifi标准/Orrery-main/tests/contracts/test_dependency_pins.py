"""The dependency list, checked for the two ways a frozen environment thaws.

Every version this project installs is written in one place, pyproject.toml,
pinned with ``==``. That is not the usual shape for a package — libraries state
ranges — and it is deliberate: the artifact README gives exactly one install
command, ``pip install -e .``, so this list is the only thing standing between
a reviewer and whatever PyPI happens to serve that day. A reported experiment
that cannot be re-run against the same versions is not reproducible.

Two failures would each unfreeze it silently, and neither shows up on the
machine that already has the packages:

**A range slips in.** Someone adds a dependency the ordinary way, without a
version, and that one line floats while everything around it looks pinned.

**The list stops being closed.** Pins on the ten imported packages do not pin
pydantic, starlette or httpx — pip resolves those from what fastapi and the
SDKs ask for. So the transitive packages are written out too, and the list has
to stay closed under its own requirements: bump fastapi, and if its new version
wants a package nobody has listed, that package installs unpinned. The check
reads the installed metadata, which is why it wants the environment to match
the list it is checking.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, requires
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]


def _declared() -> list[Requirement]:
    """Every dependency pyproject names, runtime and extras alike."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    lines = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        lines.extend(extra)
    return [Requirement(line) for line in lines]


def _wanted_by(req: Requirement) -> list[Requirement]:
    """What an installed dependency asks for, with this project's extras."""
    try:
        raw = requires(req.name) or []
    except PackageNotFoundError:  # pragma: no cover - environment, not code
        raise AssertionError(
            f"{req.name} is pinned in pyproject.toml but not installed, so the "
            f"list cannot be checked against reality. Install this project's "
            f"own dependency set before running the contract tests."
        )
    out = []
    for line in raw:
        dep = Requirement(line)
        contexts = [{"extra": ""}] + [{"extra": e} for e in sorted(req.extras)]
        if dep.marker and not any(dep.marker.evaluate(c) for c in contexts):
            continue
        out.append(dep)
    return out


def test_every_dependency_is_an_exact_pin() -> None:
    loose = sorted(str(r) for r in _declared() if not str(r.specifier).startswith("=="))
    assert not loose, (
        f"pyproject.toml pins every version with `==`; these do not: {loose}. "
        f"An unpinned line installs at whatever version PyPI serves that day."
    )


def test_the_pinned_set_is_closed() -> None:
    declared = _declared()
    listed = {canonicalize_name(r.name) for r in declared}
    missing = {}
    for req in declared:
        for dep in _wanted_by(req):
            name = canonicalize_name(dep.name)
            if name not in listed:
                missing.setdefault(name, set()).add(req.name)
    assert not missing, (
        f"installed but unlisted, so pip is free to pick their versions: "
        f"{ {k: sorted(v) for k, v in sorted(missing.items())} }. Add each one "
        f"to pyproject.toml at the version this environment resolved."
    )
