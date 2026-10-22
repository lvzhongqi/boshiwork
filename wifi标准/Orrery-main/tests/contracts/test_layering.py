"""The layering contract: the dependency rules of ARCH.md in executable form.

Implemented by walking the AST, with no dependencies, and equivalent to an
import-linter layers contract. The table below and the architecture document
state the same rules, so they move together.
"""

import ast
from pathlib import Path

PKG = "orrery"
ROOT = Path(__file__).resolve().parents[2] / PKG

# Which other top-level subpackages each top-level subpackage may import.
# Imports within one package are unrestricted. kb holds data and configs holds
# configuration; neither is importable code, so neither has a row.
# "__root__" is the files directly under orrery/: main.py, the command line,
# which drives pipeline, installs the log handlers, asks api how the corpus
# lays out and starts the console; and version.py, which imports nothing, so
# every layer can read the two version numbers.
ALLOWED = {
    "infra": set(),
    "services": {"infra"},
    "modules": {"infra"},
    "checks": {"modules", "infra"},
    "agent": {"services", "modules", "checks", "infra"},
    "nodes": {"agent", "checks", "modules", "services", "infra"},
    "pipeline": {"nodes", "agent", "checks", "modules", "services", "infra"},
    "expert": {"agent", "services", "modules", "infra"},
    "api": {"expert", "pipeline", "nodes", "agent", "checks", "modules",
            "services", "infra"},
    # The console: a driving adapter over api and nothing else. api is the
    # read/write surface a front end may see, and holding both front ends to it
    # keeps one question from getting two answers depending on who asked.
    "web": {"api"},
    # Developer-facing utilities, reached only from the command line. They may
    # see everything a request is assembled from: `orrery prompt` renders what a
    # run sends by calling the run's own builders. No pipeline, since previewing
    # a request is not orchestrating a run. Only __root__ names utils, so only
    # __root__ may import it.
    "utils": {"expert", "nodes", "agent", "checks", "modules", "services",
              "infra"},
    "__root__": {"api", "web", "pipeline", "services", "utils"},
}
CODE_PACKAGES = set(ALLOWED) - {"__root__"}


def _top(parts):
    """['orrery', 'checks', ...] -> 'checks'; None for a path outside this
    package."""
    if len(parts) >= 2 and parts[0] == PKG:
        return parts[1]
    return None


def _iter_internal_imports(py_file: Path):
    """Yield (imported top-level subpackage of this package, line number) for
    one file, resolving relative imports against its own package path."""
    rel = py_file.relative_to(ROOT.parent)
    mod_parts = list(rel.with_suffix("").parts)
    if mod_parts[-1] == "__init__":
        mod_parts.pop()
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                t = _top(alias.name.split("."))
                if t in CODE_PACKAGES:
                    yield t, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                parts = node.module.split(".") if node.module else []
                if parts == [PKG]:  # from orrery import xxx
                    for alias in node.names:
                        if alias.name in CODE_PACKAGES:
                            yield alias.name, node.lineno
                else:
                    t = _top(parts)
                    if t in CODE_PACKAGES:
                        yield t, node.lineno
            else:  # relative import: strip `level` parts off this module's path
                base = mod_parts[: len(mod_parts) - node.level]
                parts = base + (node.module.split(".") if node.module else [])
                t = _top(parts)
                if t in CODE_PACKAGES:
                    yield t, node.lineno


def test_layering():
    """Walk every module under orrery/ and collect the imports its own layer is
    not allowed to make, plus any code found outside the table."""
    violations = []
    for py_file in sorted(ROOT.rglob("*.py")):
        rel_parts = py_file.relative_to(ROOT).parts
        src_top = "__root__" if len(rel_parts) == 1 else rel_parts[0]
        if src_top not in ALLOWED:
            violations.append(f"{py_file}: code found under non-code package {src_top!r}")
            continue
        allowed = ALLOWED[src_top]
        for target, lineno in _iter_internal_imports(py_file):
            if target != src_top and target not in allowed:
                violations.append(
                    f"{py_file.relative_to(ROOT.parent)}:{lineno}: "
                    f"{src_top} may not import {target}"
                )
    assert not violations, "layering contract violated:\n" + "\n".join(violations)
