"""Every name a module under ``orrery/`` reads is bound somewhere in it.

Catches a helper renamed at one call site and deleted, with another caller left
holding the dead name until someone reaches that line at runtime. Binding
collection ignores scope on purpose, so a name bound anywhere in the file
passes; only a name bound nowhere at all fails.
"""

import ast
import builtins
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "orrery"

_ALWAYS = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__", "__debug__",
}


def _params(args: ast.arguments) -> set[str]:
    return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs,
                            args.vararg, args.kwarg) if a}


def _bound(tree: ast.AST) -> set[str]:
    names = set(_ALWAYS)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(n.name)
            names |= _params(n.args)
        elif isinstance(n, ast.Lambda):
            names |= _params(n.args)
        elif isinstance(n, ast.ClassDef):
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, ast.Global) or isinstance(n, ast.Nonlocal):
            names.update(n.names)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            names.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            names.add(n.rest)
    return names


def test_every_name_read_is_defined_somewhere_in_its_module():
    dead = []
    for f in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), str(f))
        known = _bound(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) \
                    and n.id not in known:
                dead.append(f"{f.relative_to(ROOT.parent)}:{n.lineno} {n.id}")
    assert not dead, "names read but defined nowhere:\n  " + "\n  ".join(dead)
