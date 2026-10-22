"""The config file as something a front end can render and edit.

The engine answers the whole shape here — which keys exist, which are closed
choices, what each one is for — so a page infers nothing from the values it
happens to see. Credentials go in through ``store`` but never come back out:
``describe`` and ``as_yaml`` mask every secret at every depth.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path

import yaml

from orrery.infra.proverif.runner import solver_problem
from orrery.pipeline.config import (
    BACKENDS, CHOICES, DEFAULTS, EXAMPLE_PATH, HELP, ConfigSource,
    MissingConfigError, ensure_config, generic, load_config, missing_keys,
)

__all__ = ["MissingConfigError", "default_config_path", "work_root",
           "playback_root", "corpus", "describe", "summary", "as_yaml",
           "unfilled", "store", "merge", "inline_max_chars"]

#: Anything whose name says it is a credential.
_SECRET = re.compile(r"key|token|secret|password|authorization|bearer|cookie",
                     re.IGNORECASE)
#: The live profile's values, lifted onto llm by the loader. A reading, not a
#: storage slot: they duplicate whatever slot llm.backend names.
_LIFTED = ("llm.api_key", "llm.url", "llm.model", "llm.extra_headers")
#: One writer at a time on the config file: ``store`` reads, edits and
#: replaces it, and two of those interleaved keep only the second edit.
_STORE_LOCK = threading.Lock()


def _lifted(path: str) -> bool:
    """Is this path the lifted reading, or something under it?"""
    return path in _LIFTED or any(path.startswith(p + ".") for p in _LIFTED)


def _secret(path: str, key: str) -> bool:
    """A credential by name, or any relay header: a header's name says which
    relay, its value is as often as not the credential itself."""
    return bool(_SECRET.search(key)) or ".extra_headers." in path
#: The environment variable a deployment names its fixed knobs in, as
#: comma-separated config paths.
READ_ONLY_ENV = "ORRERY_READ_ONLY"


def _leaves(d: dict, prefix: str = "") -> set[str]:
    """Every leaf path of a nested config mapping."""
    out: set[str] = set()
    for k, v in d.items():
        p = f"{prefix}{k}"
        out |= _leaves(v, p + ".") if isinstance(v, dict) else {p}
    return out


def _read_only() -> tuple[str, ...]:
    """Facts about the machine that a console will not edit.

    None on a checkout, where the person at the page owns the machine and the
    settings panel is how a first run fills in the solver path. A deployment
    that fixes some of them names them in ORRERY_READ_ONLY: the container
    image fixes the solver it ships and the run directory on its volume, and
    a page that could move either would break every run after it. Raises
    ValueError on a name that is not a config key, since a misspelt lock is a
    lock that silently is not there.
    """
    names = tuple(p.strip() for p in os.environ.get(READ_ONLY_ENV, "").split(",")
                  if p.strip())
    unknown = [p for p in names if p not in _leaves(DEFAULTS)]
    if unknown:
        raise ValueError(
            f"{READ_ONLY_ENV} names {unknown}, which are not config keys; the "
            f"keys are the DEFAULTS table's leaves in pipeline/config.py")
    return names


def default_config_path() -> str:
    """The config file to serve when nobody named one — config.yaml at the
    project root, made from config.example.yaml the first time anyone asks."""
    return str(ensure_config())


def work_root(config_path: str | Path) -> Path:
    """Where the runs are, according to the config file.

    Loaded with ``require=False``, because reading a run needs no model and no
    solver: a config still missing its api_key must not keep a front end shut.
    The path comes back anchored to the project root.
    """
    cfg = load_config(config_path, require=False)
    return Path(cfg["paths"]["work_root"]).expanduser().resolve()


def playback_root(config_path: str | Path) -> Path:
    """Where the recorded runs are, according to the config file.

    Playback's own root rather than ``work_root``: it reads a tree of finished
    runs and writes nothing, and the recordings a published artifact ships are
    not the directory this checkout runs into. Read the same way as
    ``work_root`` and for the same reason — a config with no key still has to
    open the console.
    """
    cfg = load_config(config_path, require=False)
    return Path(cfg["paths"]["playback_root"]).expanduser().resolve()


def inline_max_chars() -> int:
    """The document size a run gives to the extraction steps whole — the
    boundary between a protocol that fits and one that has to be excerpted."""
    return DEFAULTS["document"]["inline_max_chars"]


def _knobs(cfg: dict, prefix: str = "") -> list[dict]:
    out: list[dict] = []
    for k, v in cfg.items():
        path = f"{prefix}{k}"
        # Before the descent: the lifted extra_headers is a mapping, and walked
        # it would come out as editable llm.extra_headers.<name> rows that
        # store back over the slot the loader lifted them from.
        if _lifted(path):
            continue
        if isinstance(v, dict):
            out += _knobs(v, f"{path}.")
            continue
        secret = _secret(path, k)
        choice = CHOICES.get(generic(path), {})
        out.append({
            "path": path,
            "group": path.split(".")[0],
            "value": ("(set)" if v not in (None, "", "???") else None) if secret else v,
            # Declared type wins: a knob whose value is null right now cannot
            # say what it is, and an editor needs to know before an edit.
            "type": choice.get("type") or ("boolean" if isinstance(v, bool)
                    else "number" if isinstance(v, (int, float)) else "string"),
            "choices": choice.get("values", []),
            # Which other knob decides this one's list, when one does.
            "depends_on": choice.get("depends_on"),
            "closed": bool(choice.get("closed")),
            "secret": secret,
            "locked": path in _read_only(),
            # What this knob is for, straight off the engine's declaration.
            "help": HELP.get(generic(path), ""),
            # Which backend's slot this row belongs to; None outside
            # llm.profiles.
            "profile": path.split(".")[2] if path.startswith("llm.profiles.")
                       else None,
        })
    return out


def describe(config_path: str | Path, runs_root: Path) -> dict:
    """Every knob, what it is for, and what state the config is in.

    ``require=False`` so an unfinished config still renders: on a fresh clone
    the api_key is the one thing a reader came here to fill in.
    """
    cfg = load_config(config_path, require=False)
    unfilled = missing_keys(cfg)
    return {
        "complete": not unfilled,
        "unfilled": unfilled,
        "knobs": _knobs(cfg),
        "backends": BACKENDS,
        # Which backends have a key filled in and can be switched to.
        "ready": sorted(b for b, slot in (cfg["llm"]["profiles"] or {}).items()
                        if slot and slot.get("api_key") not in (None, "", "???")),
        # Provenance: the file all of the above came from, and the example it
        # was seeded from, which is also what to restore from.
        "config_path": str(config_path),
        "example": str(EXAMPLE_PATH),
        "work_root": str(runs_root),
        # A work root nothing has written to yet does not exist, which is the
        # ordinary state of a fresh checkout: empty and absent are different
        # answers and are reported differently.
        "work_root_exists": runs_root.is_dir(),
    }


def store(config_path: str | Path, path: str, value) -> None:
    """Set one config value and keep it — write it into the config file.

    Written against the file rather than the effective config, so defaults do
    not get baked in and the lifted llm.* readings are never stored back.
    Comments do not survive the yaml round-trip; config.example.yaml is the
    annotated reference. The edited file goes through load_config before it
    lands, so a bad path, value or shape raises ValueError here.
    """
    if not path:
        raise ValueError("path is required, e.g. llm.backend")
    if _lifted(path):
        raise ValueError(
            f"{path} is where the live backend's slot is *read*, not where it "
            f"is stored. Set llm.profiles.<backend>.{path.split('.')[-1]}, or "
            f"move llm.backend.")
    if path in _read_only():
        raise ValueError(
            f"{path} is fixed by this deployment ({READ_ONLY_ENV}); it can be "
            f"changed in the config file, not from the page")
    if path in ("paths.work_root", "paths.playback_root"):
        # Both have to exist: a missing root surfaces later as an empty run
        # list, which reads exactly like a root with nothing in it.
        root = Path(str(value)).expanduser()
        if not root.is_dir():
            raise ValueError(f"not a directory: {root}")
        value = str(root.resolve())

    target = Path(config_path)
    with _STORE_LOCK:
        stored = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        node, *rest = path.split(".")
        cursor = stored
        for k in [node] + rest[:-1]:
            nxt = cursor.get(k)
            if not isinstance(nxt, dict):
                nxt = cursor[k] = {}
            cursor = nxt
        cursor[rest[-1] if rest else node] = value

        try:
            load_config(stored, require=False)
        except MissingConfigError as e:
            raise ValueError(f"{path} = {value!r} does not load: {e}") from None

        tmp = target.with_suffix(".yaml.tmp")
        # A header saying where the comments went, since this save drops them
        # all.
        tmp.write_text(
            f"# Written by the Orrery console. Comments do not survive a save;\n"
            f"# every option is explained in {EXAMPLE_PATH.name}, which is also\n"
            f"# what this file was made from and what to restore it from.\n"
            + yaml.safe_dump(stored, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        tmp.chmod(0o600)                    # it holds an API key
        tmp.replace(target)                 # atomic: never a half-written config


def _has_credential(cfg: dict) -> bool:
    """Is the live backend's key filled in? Every backend talks to a vendor, so
    without one there is nothing to run."""
    llm = cfg["llm"]
    return bool(llm.get("api_key")) and llm["api_key"] != "???"


def corpus(config_path: ConfigSource | Sequence[ConfigSource]) -> dict:
    """The corpus root this config names, and whether the live backend has a
    key — together, because they answer one question: is there anything to
    offer, and can it be started. The root does not have to exist; a checkout
    without a corpus beside it still renders.
    """
    cfg = load_config(config_path, require=False)
    return {"lib": Path(cfg["paths"]["lib_root"]).expanduser(),
            "credential": _has_credential(cfg)}


def merge(base: dict, overrides: dict) -> dict:
    """An already-loaded config with one more layer of overrides on top —
    config.py's third level, which a corpus overlay and a pinned work root
    travel in."""
    return load_config(base, overrides)


def summary(config_path: str | Path) -> dict:
    """The handful of facts a starting front end says out loud: which config
    file this is, where the runs go, which model and solver are live, what is
    still unfilled, and why the solver cannot run when it cannot."""
    cfg = load_config(config_path, require=False)
    llm = cfg["llm"]
    return {"config_path": str(config_path),
            "work_root": cfg["paths"]["work_root"],
            "backend": llm.get("backend"),
            "model": llm.get("model"),
            "proverif": cfg["proverif"]["executable"],
            "proverif_problem": solver_problem(cfg["proverif"]["executable"]),
            "missing": missing_keys(cfg)}


def unfilled(config_path: ConfigSource | Sequence[ConfigSource] | None = None,
             overrides: dict | None = None) -> list[str]:
    """Which required values are still ``???``, for a config read the way
    ``as_yaml`` reads it — a stack of ``--config`` layers, so the answer is a
    property of the merge rather than of any one layer.
    """
    return missing_keys(load_config(config_path or ensure_config(), overrides,
                                    require=False))


def as_yaml(config_path: ConfigSource | Sequence[ConfigSource] | None = None,
            overrides: dict | None = None) -> str:
    """The full effective config — built-in defaults, the user file and any
    overrides, merged — as YAML, with every credential masked.

    Masked by key name at any depth, since credentials sit one slot per
    backend; the first characters survive so a reader can tell which key is in
    the slot, and ``???`` passes through as itself. ``require=False``, so an
    incomplete config still renders.
    """
    cfg = deepcopy(load_config(config_path or ensure_config(), overrides,
                               require=False))

    def mask(node, prefix=""):
        if not isinstance(node, dict):
            return node
        return {k: (str(v)[:6] + "…" if _secret(f"{prefix}{k}", k) and v
                    and str(v) != "???" else mask(v, f"{prefix}{k}."))
                for k, v in node.items()}

    return yaml.safe_dump(mask(cfg), allow_unicode=True, sort_keys=False)
