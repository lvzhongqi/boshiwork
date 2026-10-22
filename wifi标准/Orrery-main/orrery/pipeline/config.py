"""Config loading: built-in defaults < the user's config file(s) < programmatic
overrides.

The user level is a stack — each file is merged over the one before, so a later
file states only what it changes. The defaults are ``DEFAULTS`` below; no
resource file inside the package is read. ``config.yaml`` at the project root is
seeded on first use by copying ``config.example.yaml``, which carries a comment
for every option. A required value is written ``???`` and left unfilled it is an
explicit error naming its key path.
"""

from __future__ import annotations

import copy
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

import yaml

#: The environment variable naming the directory an installation keeps its
#: data in: the default config.yaml, and the anchor for every relative path in
#: it.
HOME_ENV = "ORRERY_HOME"


def _source_root() -> Path:
    """The source tree this package was loaded from. Under the documented
    ``pip install -e .`` that is the checkout, which holds config.example.yaml;
    under a plain install it is site-packages, which does not."""
    return Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    """The directory holding the project's data — corpus, runs, config.

    ORRERY_HOME when it is set: an installed copy (the container image, a
    plain ``pip install .``) keeps its data where that names, not beside the
    code in site-packages. Otherwise the checkout itself, anchored to this
    package so the answer does not depend on where a command was typed.
    Raises RuntimeError when ORRERY_HOME names no directory: every default
    path would then point into nothing.
    """
    home = os.environ.get(HOME_ENV)
    if home:
        p = Path(home).expanduser().resolve()
        if not p.is_dir():
            raise RuntimeError(
                f"{HOME_ENV}={home!r} is not a directory; it names where this "
                f"installation keeps its config and runs")
        return p
    return _source_root()


#: The project root. See ``_project_root``.
PROJECT_ROOT = _project_root()
#: The config this installation uses by default. Gitignored in a checkout — it
#: holds an API key.
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
#: The reference copy, in git: every option with its default and its
#: explanation, and the seed for a new config.yaml. It belongs to the source,
#: not to the data, so ORRERY_HOME does not move it.
EXAMPLE_PATH = _source_root() / "config.example.yaml"

# Per-backend model suggestions, for a console offering known values. A model id
# is only meaningful to the adapter that sends it, so the list and the default
# switch with the backend. The list is a suggestion, not a constraint: an
# unlisted id a gateway answers to is still accepted, and only the backend name
# itself is closed, because the factory switches on it.
BACKENDS = {
    "remote-claude": {
        "default": "claude-opus-5",
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-fable-5",
                   "claude-sonnet-4-6"],
    },
    "remote-gemini": {
        "default": "gemini-3.1-pro-preview",
        "models": ["gemini-3.7-flash", "gemini-3.1-pro-preview",
                   "gemini-3-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
    },
    "remote-openai-responses": {
        "default": "gpt-5.6-sol",
        "models": ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.5"],
    },
    # Everything else speaking the OpenAI protocol, in practice a relay in front
    # of somebody else's models, so the list is every family measured over one.
    # deepseek and qwen answer /v1/chat/completions and land here: a backend is
    # an adapter, not a vendor.
    "remote-openai-compatible": {
        "default": "claude-sonnet-5",
        "models": ["claude-sonnet-5", "claude-opus-5", "gpt-5.6-sol",
                   "gemini-3.1-pro-preview", "glm-4.5-flash",
                   "deepseek-v4-pro", "deepseek-v4-flash",
                   "qwen3.7-max", "qwen3.6-plus", "qwen3.5-plus"],
    },
}

# What a console may offer for a setting whose useful values are known.
# Declared here so the console renders what the engine says exists rather than
# deriving it from a value it happened to see.
CHOICES = {
    "llm.backend": {"closed": True, "values": list(BACKENDS)},
    # Model has no list of its own: it follows whatever llm.backend is. Declared
    # for the slot as well as for the lifted reading, since the slot is what a
    # console actually edits.
    "llm.model": {"closed": False, "depends_on": "llm.backend"},
    "llm.profiles.*.model": {"closed": False, "depends_on": "llm.backend"},
    "pipeline.mode": {"closed": True, "values": ["auto", "manual"]},
    # Nullable numbers: the value on disk may be None, so the type is declared
    # rather than guessed from the value.
    "expert.max_rounds": {"type": "number", "closed": False, "values": []},
    "expert.max_tool_calls": {"type": "number", "closed": False, "values": []},
}

# One sentence per knob, for a console that shows it on hover — the short form
# of the comments beside DEFAULTS. A contract test fails if a knob has no entry.
HELP = {
    "paths.work_root": "Where runs are written: <work_root>/<protocol>/<run>/. Relative paths are relative to the project, not to the shell you started from.",
    "paths.playback_root": "The recorded runs the console replays, in the same layout as work_root: <playback_root>/<protocol>/<run>/. It is one batch directory, not the directory holding the batches. Read only, and used only in recorded mode; the run root box in the launch panel writes here.",
    "paths.lib_root": "The protocol corpus the New run panel scans. The default is a corpus inside the project, which is where a published artifact keeps one; point it wherever yours is. Only scanned once a backend with a credential is live.",

    "inputs.lib_principals": "Hand the run the protocol's own semantic flow/principals.json instead of extracting it. On its own it measures flow extraction: the model is written from the corpus's principals and stable values, with nothing else supplied.",
    "inputs.lib_flow": "Hand the run the protocol's own flow/flow.pv. It needs inputs.lib_principals with it because the mother model and its stable value/dependency contract travel together.",
    "inputs.lib_claims": "Hand the run the protocol's own claims/ files (assumptions, properties, claims) instead of extracting them. One switch for the three because claims.json references entries of the other two. Independent of the model switches: pinning the question is what makes a flow-extraction run comparable.",
    "inputs.end_point": "Where the run stops: after principals, after the flow model, after the claims, or scenarios for the rest of the table (build_world through reproduce_attacks). It must leave at least one step for the run to do.",
    "inputs.flow": "An explicit path to a mother model .pv, for one that does not live in the corpus. Given, it wins over inputs.start_point; it needs inputs.principals with it.",
    "inputs.principals": "The semantic principals.json the explicit mother model is written on. Its stable value/dependency contract and the model are one input and travel together.",

    "llm.backend": "Which adapter, and so which profile below is live. Each backend keeps its own key, url and model, so switching away and back costs nothing.",
    "llm.profiles.*.model": "The model id sent to this backend. The list is what this repo has actually talked to; a gateway may answer to others.",
    "llm.profiles.*.api_key": "This backend's credential. Required for whichever backend is live. Never leaves the server — the page only shows whether one is set.",
    "llm.profiles.*.url": "This backend's gateway address. Empty connects to the vendor's official endpoint.",
    "llm.profiles.*.extra_headers": "Headers sent verbatim with every request to this gateway, and the only way any header reaches the wire. Some relays need specific ones before prompt caching or tool_choice behave.",
    "llm.cache_ttl": "Prompt-cache lifetime for the shared corpus block (claude backend only). Empty is the 5-minute default; \"1h\" holds it across repeat runs at twice the write cost.",
    "llm.timeout_s": "Hard ceiling on one model call. Raise this before raising any step's effort — a deeper think needs a longer budget, not a shorter reply.",

    "proverif.executable": "The ProVerif binary. A bare name is looked up on PATH; anything with a separator is a path, relative ones to the project. Required.",
    "proverif.timeout_s": "Ceiling on one ProVerif invocation. A timeout is its own outcome and never triggers a repair round.",

    "pipeline.mode": "auto runs straight through; manual stops at every step boundary and waits for you to release it.",
    "pipeline.approval_timeout_s": "How long manual mode waits for release. Empty waits forever; a timeout is treated as an interrupt.",
    "pipeline.gap_budget": "How many times one run may roll back to an earlier step because a model reported something missing upstream.",
    "pipeline.gap_reject_limit": "How many rejected gap reports a run tolerates before failing. A rejection re-runs the reporting step, so an unbounded loop burns tokens.",
    "pipeline.max_scenarios_concurrency": "How many scenarios one run works on at once. Work inside each scenario expands independently and is not capped by this setting.",

    "document.inline_max_chars": "A protocol document under this size is given to the extraction steps whole; a larger one has to be cut into sections first.",

    "agent.max_rounds": "Ceiling on ordinary model calls for one pipeline task, repair rounds included. Pending framework feedback may receive one terminal-only finalization call.",
    "agent.max_tool_calls": "Ceiling on tool calls for one pipeline task.",
    "agent.max_repairs": "How many repair rounds a step gets after its checks fail before the run gives up on it.",
    "agent.tool_return_chars": "How much of a tool's output is handed back. Past it the return is cut and says how much is left.",

    "expert.max_rounds": "Model calls for one expert message. Empty means no ceiling — how much evidence a question needs is the question's business.",
    "expert.max_tool_calls": "Readings for one expert message. Empty means no ceiling; reads cost no model call.",

    "scenarios.inject_cells_per_call": "How many cells one inject call may cover within a family. 1 degrades to one call per cell.",

    "solve.trace_retry_timeout_s": "Seconds one provisional goal gets after bounded trace reconstruction is restored. Each retry contains only that goal.",
    "solve.precise_actions_retry": "After the trace retry still returns cannot_be_proved, give that goal one final retry with ProVerif's preciseActions set.",
    "solve.precise_retry_timeout_s": "Seconds one final preciseActions retry gets. Its own budget, because it solves one query and is meant to fail fast.",
    "solve.vacuity_check": "Ask whether a proved goal's observation point is reachable at all; record the unreachable ones vacuous rather than true.",
    "solve.vacuity_timeout_s": "Seconds the vacuity pass gets. No verdict there changes nothing, so this budget only decides how long the question is worth asking.",

    "attacks.enabled": "After the verdicts, replay the attack behind each false cell as a step-by-step script you can watch. Off leaves the step with nothing to do.",
    "attacks.auto_cells": "How many false cells are replayed on their own. Past it the step goes round the broken goals first, and the rest wait for you to ask for them in the console.",
    "attacks.long_timeout_s": "Seconds for re-running a false cell under ProVerif's long trace display, which prints each session's bindings and every check it made. Past it the cell is re-run under the default display, which draws the same attack without those rows.",
}


def generic(path: str) -> str:
    """A knob path with the backend name in a profile slot replaced by ``*``.

    Every slot carries the same four settings, so CHOICES and HELP declare them
    once against the generic path; a backend added to BACKENDS then arrives with
    its declarations already in place.
    """
    parts = path.split(".")
    if len(parts) == 4 and parts[:2] == ["llm", "profiles"]:
        return f"llm.profiles.*.{parts[3]}"
    return path


DEFAULTS: dict = {
    # Where things are. A relative value is anchored to the project root, never
    # to the shell's directory — see _anchor_paths.
    "paths": {
        "work_root": "./a_runs",         # runs are written here: <work_root>/<protocol>/<run>/
        "lib_root": "./VerdictBench",    # the protocol corpus to scan for runnable protocols
        # Playback reads a tree of finished runs and never writes, so it has its
        # own root rather than borrowing work_root: the recordings a published
        # artifact ships are not the directory this checkout runs into.
        "playback_root": "./runs/main",  # recorded runs to replay: <playback_root>/<protocol>/<run>/
    },
    # What a run is handed rather than extracting for itself. Pinning an
    # artifact to the corpus's own copy is what makes two runs comparable: a
    # difference further down is then one the change made, not one this pass's
    # extraction introduced.
    "inputs": {
        # One choice per artifact: take the corpus's copy, or extract it. The
        # only coupling is lib_flow needing lib_principals — flow_fixed_parts
        # checks the model's role signatures against the template rendered from
        # that principals.json, so a model over somebody else's initial
        # knowledge fails by construction. The three claim files are one switch
        # because claims.json references entries of the other two.
        "lib_principals": False,   # use <protocol>/flow/principals.json
        "lib_flow": False,         # use <protocol>/flow/flow.pv — needs lib_principals
        "lib_claims": True,        # use <protocol>/claims/{assumptions,properties,claims}.json
        # Where the run stops: the artifact after which there is nothing left to
        # do, or `scenarios` for the rest of the table.
        "end_point": "scenarios",  # principals | flow | claims | scenarios

        # Explicit paths, for a model that does not live in the corpus. Given,
        # they win over the chain's own resolution. principals on its own is
        # legal and leaves the model to be extracted on it.
        "flow": None,           # path to a .pv mother model
        "principals": None,     # path to the principals.json it is written on
    },
    "llm": {
        # Every backend talks to a vendor, so a fresh checkout runs nothing
        # until a key is pasted into the live slot below.
        "backend": "remote-openai-responses",  # which profile below is live
        # One slot per backend, each holding everything needed to reach that one
        # gateway. Address and credential are a single unit: a key sent to the
        # wrong url fails at request time with an error that reads like a model
        # fault. Only the live slot has to be filled, and its values are lifted
        # onto llm.api_key / llm.url / llm.model / llm.extra_headers when the
        # config loads, which is where everything downstream reads them.
        "profiles": {
            name: {
                "model": spec["default"],   # model id; anything the gateway answers to
                "api_key": "???",    # required for the live backend, and must be non-empty: given no key every vendor SDK falls back to its own env var (ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY) and the run goes out under a credential this file does not name. `api_key:` with nothing after it is YAML for null and is rejected
                "url": None,         # gateway address; None connects to that backend's official endpoint
                "extra_headers": None,      # sent verbatim, and the only way a header reaches the wire. Some relays need specific ones before prompt caching or tool_choice behave
            }
            for name, spec in BACKENDS.items()
        },
        "cache_ttl": None,           # prompt-cache lifetime for the system blocks (claude backend): None = 5m default, "1h" holds the corpus across repeat runs at 2x write cost
        "timeout_s": 600,            # hard ceiling on one model call. It does not size max_tokens: the claude backend must send one and uses a fixed default, chosen so truncation (recoverable, one repair round) bites before this timeout (unrecoverable, the run ends)
        # temperature is never sent: the request uses the model's default, which
        # the newest model families require (they 400 on any temperature). A
        # caller wanting a specific value passes it to invoke().
    },
    "proverif": {
        "executable": "proverif",    # the proverif binary; a bare name is looked up on PATH, so set a full path when it is not there
        "timeout_s": 180,            # timeout per run in seconds; a timeout is the TIMEOUT outcome and never triggers a repair round
    },
    "pipeline": {
        "mode": "auto",              # auto runs straight through; manual waits for the host to release at each node boundary
        "approval_timeout_s": None,  # how long manual waits for release, in seconds; None waits forever, and a timeout is treated as an interrupt
        "gap_budget": 3,             # how many cross-node rollbacks one run may accept
        "gap_reject_limit": 2,       # how many rejected gap reports one run tolerates before failing: a rejection re-runs the reporting node, so an unbounded loop burns tokens
        "max_scenarios_concurrency": 4,  # how many scenarios this run works on at once; work inside one scenario expands independently
    },
    "document": {
        # Inline corpus limit (characters). A main document within it is inlined
        # whole into the extraction nodes' shared corpus block; a larger one is
        # cut to its flow-tagged sections; reference documents are never
        # inlined. The reading tools stay available as the fallback either way.
        "inline_max_chars": 30000,
    },
    "agent": {
        "max_rounds": 12,            # ceiling on ordinary model calls per task (repair rounds count); one terminal-only finalization call may follow pending feedback
        "max_tool_calls": 40,
        "max_repairs": 6,            # ceiling on repair rounds after a failed must-level check
        "tool_return_chars": 20000,  # tool return budget: truncate past it and state how much is left
    },
    "expert": {
        # One chat message, not one pipeline task. Every tool return the expert
        # collects stays in the conversation and is re-sent with every later
        # message, so max_tool_calls is what bounds that growth.
        "max_rounds": None,          # model calls for one message; None = no ceiling, since how much evidence a question needs is the question's business
        "max_tool_calls": None,      # readings for one message (artifacts, sessions, document); None = no ceiling, since reads cost no model call
    },
    "scenarios": {
        "inject_cells_per_call": 4,  # cells one inject call may cover, within one family; 1 degrades to one call per cell
    },
    "solve": {
        "trace_retry_timeout_s": 100,   # first pass carries reconstructTrace=false; each provisional goal then gets this bounded, goal-only retry with ProVerif's default trace reconstruction restored
        "precise_actions_retry": True,  # if that trace retry is still cannot_be_proved, give the goal one final retry with set preciseActions
        "vacuity_check": True,         # a goal proved on an unreachable observation point is recorded vacuous, not true
        "vacuity_timeout_s": 120,      # seconds for the pass. It asks reachability only, so it carries reconstructTrace=false and is far cheaper than the solve; no answer leaves every verdict alone
        "precise_retry_timeout_s": 100, # seconds per retry, separate from proverif.timeout_s: that budget covers a whole cell of goals, while this run carries one query and exists to fail fast
    },
    "attacks": {
        "enabled": True,     # after the verdicts, replay the attack behind each false cell as a step-by-step script
        "auto_cells": 10,    # how many false cells are replayed on their own; the rest wait for someone to ask in the console
        "long_timeout_s": 300,  # seconds for the long-display re-run, which prints every session's bindings and checks; past it the cell is re-run under the default display within solve.trace_retry_timeout_s
    },
}


class MissingConfigError(RuntimeError):
    """A config that cannot be run from: a required value left ``???``, an
    unreadable file, or a key written in a shape this loader has dropped."""
    pass


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


#: Lifted from the live profile onto ``llm`` itself, so every consumer reads
#: llm.api_key / llm.url / llm.model directly.
_LIFTED = ("api_key", "url", "model", "extra_headers")


def _resolve_profile(cfg: dict, force: bool = False) -> None:
    """Lift the live backend's profile onto ``llm`` itself, in place.

    The slots are storage; ``llm.api_key`` and friends are the reading. A slot
    naming no model falls back to that backend's default. Only absent keys are
    filled unless ``force``, so a config resolved twice keeps a one-off
    ``llm.model``; ``force`` is for an override that moved llm.backend, where
    the whole slot has to come up together. Raises MissingConfigError when the
    backend has no slot.
    """
    llm = cfg["llm"]
    backend = llm.get("backend")
    profiles = llm.get("profiles") or {}
    if backend not in profiles:
        raise MissingConfigError(
            f"llm.backend is {backend!r}, which has no slot under llm.profiles. "
            f"Declared: {sorted(profiles)}. Add a slot with its api_key, or "
            f"point llm.backend at one of those.")
    slot = profiles[backend] or {}
    for k in _LIFTED:
        if force or k not in llm:
            llm[k] = slot.get(k)
    if not llm.get("model"):
        llm["model"] = BACKENDS.get(backend, {}).get("default")


def _anchor_paths(cfg: dict) -> None:
    """Anchor the relative paths in ``cfg`` to the project root, in place.

    Covers paths.*, the two explicit inputs.* paths and proverif.executable. The
    defaults are written relative so the example file stays portable; what they
    mean must not depend on which directory the process was started in, or the
    console and the CLI read two different trees on one machine.
    """
    for k, v in cfg["paths"].items():
        if not v:
            continue
        path = Path(v).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        # Normalised: these strings are shown to a reader and compared against
        # each other, so a `..` must not survive in one of them.
        cfg["paths"][k] = str(Path(os.path.normpath(path)))
    for k in ("flow", "principals"):
        v = cfg["inputs"].get(k)
        if not v:
            continue
        path = Path(v).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        cfg["inputs"][k] = str(Path(os.path.normpath(path)))
    # A bare solver name means "look it up on PATH" and is left alone; anything
    # with a separator in it is a path and gets anchored.
    exe = cfg["proverif"].get("executable")
    if exe and "/" in exe and not Path(exe).is_absolute():
        cfg["proverif"]["executable"] = str(Path(os.path.normpath(PROJECT_ROOT / exe)))


def _find_missing(node, path: str) -> list[str]:
    # The profile slots are skipped whole: only the live one has to be filled,
    # and it is checked through the lifted llm.* values instead.
    if path == "llm.profiles":
        return []
    if node == "???":
        return [path]
    if isinstance(node, dict):
        return [m for k, v in node.items()
                for m in _find_missing(v, f"{path}.{k}" if path else k)]
    return []


def _reject_legacy(d: dict, source: str, stored: bool = True) -> None:
    """Raise on a key written in a shape this loader has dropped.

    ``source`` names the layer for the message. Every error shows the current
    form, because a stale key merged silently would leave the run doing
    something other than what the file says. ``stored`` is False for the
    override level, where a flat ``llm.model`` is a deliberate one-off.
    """
    if "infra" in d:
        raise MissingConfigError(
            f"{source}: the top-level key 'infra' is the old shape; llm and proverif "
            f"are now top-level sections: llm: {{backend, model, api_key, url}} / "
            f"proverif: {{executable}}"
        )
    if isinstance(d.get("pipeline"), dict) and "work_root" in d["pipeline"]:
        raise MissingConfigError(
            f"{source}: pipeline.work_root has moved to paths.work_root, "
            f"alongside paths.lib_root, at the top of the config")

    if isinstance(d.get("pipeline"), dict) and "max_concurrency" in d["pipeline"]:
        raise MissingConfigError(
            f"{source}: pipeline.max_concurrency has been replaced by "
            "pipeline.max_scenarios_concurrency. The setting now controls only "
            "how many scenarios run at once; work inside a scenario is uncapped")

    if isinstance(d.get("llm"), dict) and "max_concurrency" in d["llm"]:
        raise MissingConfigError(
            f"{source}: llm.max_concurrency has been removed. LLM calls are not "
            "globally gated; the pipeline limits concurrent scenarios and a "
            "batch host limits concurrent runs")

    if (isinstance(d.get("proverif"), dict)
            and "max_concurrency" in d["proverif"]):
        raise MissingConfigError(
            f"{source}: proverif.max_concurrency has been removed. ProVerif "
            "subprocesses are not separately gated; the pipeline limits "
            "concurrent scenarios and a batch host limits concurrent runs")

    ins = d.get("inputs")
    if isinstance(ins, dict) and (stale := [k for k in ("start_point", "lib_model",
                                                        "lib_question")
                                            if k in ins]):
        raise MissingConfigError(
            f"{source}: inputs.{{{', '.join(stale)}}} is the chain shape, and "
            f"the chain was wrong: it made the question depend on the model. "
            f"Each artifact is now its own choice — inputs: {{lib_principals, "
            f"lib_flow, lib_claims}} — with one dependency, lib_flow needing "
            f"lib_principals. Where a run stops is inputs.end_point")

    llm = d.get("llm")
    if not isinstance(llm, dict):
        return
    if "name" in llm and "backend" not in llm:
        raise MissingConfigError(
            f"{source}: llm.name plus nested entries is the old model-library shape; "
            f"credentials now live one slot per backend: llm: {{backend: remote-claude, "
            f"profiles: {{remote-claude: {{api_key: ..., url: ..., model: ...}}}}}}"
        )
    # A flat llm.api_key in a stored file would be overwritten by the live slot
    # at resolve time, so the run would go out under a credential the file
    # appears to forbid.
    if (stored and "profiles" not in llm
            and (stale := [k for k in ("api_key", "url", "model") if k in llm])):
        raise MissingConfigError(
            f"{source}: llm.{{{', '.join(stale)}}} at the top of llm is the old flat "
            f"shape; each backend now carries its own, so switching away and back "
            f"keeps them: llm: {{backend: <name>, profiles: {{<name>: {{api_key: ..., "
            f"url: ..., model: ...}}}}}}"
        )


def ensure_config(path: Path | None = None,
                  example: Path | None = None) -> Path:
    """The config file this checkout uses, seeded from the example on first run.

    A fresh clone has no config.yaml, so the example is copied to one and that
    copy is what gets edited: it is gitignored, and the example never holds a
    key. A plain file copy, not a re-serialisation, so the example's comments
    survive. The pair is nameable because the batch runner has its own under
    ``experiments/``. Raises MissingConfigError when neither file exists.
    """
    path, example = path or CONFIG_PATH, example or EXAMPLE_PATH
    if path.exists():
        return path
    if not example.is_file():
        raise MissingConfigError(
            f"neither {path} nor {example} exists, so there is "
            f"nothing to run from and nothing to seed a config with")
    shutil.copyfile(example, path)
    path.chmod(0o600)                   # it is about to hold an API key
    return path


def missing_keys(cfg: dict) -> list[str]:
    """Which required values are still ``???``, by key path.

    Public because a console needs the list rather than the exception: on first
    run it marks the fields to fill instead of refusing to render. A lifted
    llm.* value is reported at the profile slot it is actually edited in, since
    ``llm.api_key`` is a reading and does not exist in the file.
    """
    at = f"llm.profiles.{cfg['llm'].get('backend')}"
    missing = [f"{at}.{m.split('.')[-1]}" if m.startswith("llm.") else m
               for m in _find_missing(cfg, "")]
    # An empty key is the same failure as an unfilled one and harder to
    # diagnose: every vendor SDK falls back to its own environment variable, so
    # the run goes out under a credential this file never names. `api_key:`
    # with nothing after it is YAML for null.
    if not cfg["llm"].get("api_key") and f"{at}.api_key" not in missing:
        missing.append(f"{at}.api_key")
    return missing


#: Keys the engine reads that DEFAULTS does not carry, so they are legal at
#: the top of a layer without being console knobs: ``prompt_lang`` is read by
#: the prompt builders with an ``en`` fallback and is deliberately not offered
#: on the settings panel (the zh retrieval is retired; TODO.md).
_EXTRA_TOP = ("prompt_lang",)


def _unknown_keys(layer: dict) -> list[str]:
    """The key paths in ``layer`` that no reader of the config knows.

    Shape follows DEFAULTS: a section is a mapping with the keys DEFAULTS
    gives it, a profile slot holds the lifted keys, ``extra_headers`` is a
    free mapping. The lifted keys are legal directly under ``llm`` too, since a
    resolved config is itself a layer (a host re-loads the config it holds),
    and the stored-file case is refused by ``_reject_legacy`` before this.
    """
    out: list[str] = []
    ref_top = {**DEFAULTS, **{k: None for k in _EXTRA_TOP}}

    def walk(d: dict, ref: dict, prefix: str) -> None:
        for k, v in d.items():
            path = f"{prefix}{k}"
            if prefix == "llm." and k in _LIFTED:
                continue
            if path == "llm.profiles":
                if not isinstance(v, dict):
                    out.append(f"{path} (must be a mapping of backend slots)")
                    continue
                # Slot names are not checked against BACKENDS: the live one
                # is (_resolve_profile), and a test's stub backend keeps a
                # slot of its own.
                for name, slot in v.items():
                    if isinstance(slot, dict):
                        out.extend(f"{path}.{name}.{sk}" for sk in slot
                                   if sk not in _LIFTED)
                    else:
                        out.append(f"{path}.{name} (must be a mapping)")
                continue
            if k not in ref:
                out.append(path)
                continue
            if isinstance(ref[k], dict):
                if isinstance(v, dict):
                    walk(v, ref[k], path + ".")
                else:
                    out.append(f"{path} (must be a mapping)")

    walk(layer, ref_top, "")
    return out


def _reject_unknown(layer: dict, source: str) -> None:
    """Raise on a key nothing reads. Merged silently, a misspelt knob leaves
    the run doing something other than what the file says, and a misspelt
    section leaves a whole block of settings at their defaults."""
    if unknown := _unknown_keys(layer):
        raise MissingConfigError(
            f"{source}: unknown config key(s) {unknown}. Every key must be one "
            f"the engine reads (the DEFAULTS table in pipeline/config.py "
            f"lists them); a key nobody reads would be merged and ignored")


#: Every numeric knob: path -> (kind, nullable, minimum). ``count`` is an
#: integer; ``seconds`` an integer or a float. A bool is neither.
_NUMBERS = {
    "llm.timeout_s": ("seconds", False, 1),
    "proverif.timeout_s": ("seconds", False, 1),
    "pipeline.approval_timeout_s": ("seconds", True, 1),
    "pipeline.gap_budget": ("count", False, 0),
    "pipeline.gap_reject_limit": ("count", False, 0),
    "pipeline.max_scenarios_concurrency": ("count", False, 1),
    "document.inline_max_chars": ("count", False, 1),
    "agent.max_rounds": ("count", True, 1),
    "agent.max_tool_calls": ("count", True, 0),
    "agent.max_repairs": ("count", False, 0),
    "agent.tool_return_chars": ("count", False, 1),
    "expert.max_rounds": ("count", True, 1),
    "expert.max_tool_calls": ("count", True, 0),
    "scenarios.inject_cells_per_call": ("count", False, 1),
    "solve.trace_retry_timeout_s": ("seconds", False, 1),
    "solve.vacuity_timeout_s": ("seconds", False, 1),
    "solve.precise_retry_timeout_s": ("seconds", False, 1),
    "attacks.auto_cells": ("count", False, 0),
    "attacks.long_timeout_s": ("seconds", False, 1),
}

#: Every switch: it is a bool or it is wrong (YAML's ``yes``/``on`` are bools
#: already; a string "true" is not).
_SWITCHES = ("inputs.lib_principals", "inputs.lib_flow", "inputs.lib_claims",
             "solve.precise_actions_retry", "solve.vacuity_check",
             "attacks.enabled")


def _validate_values(cfg: dict) -> None:
    """Reject a value of the wrong shape while reading the config, before a run
    has created a directory or paid for model work: a closed choice outside
    its list, a count or a timeout that is not a number (a string ``"12"``
    would reach the loop budget as text), a switch that is not a bool.
    """
    for path, spec in CHOICES.items():
        # llm.backend is closed for the console, not here: the loader only
        # needs the live backend to have a slot (_resolve_profile), and the
        # factory refuses an unknown name the moment a client is built, so a
        # pure-code run under a stub backend stays possible.
        if not spec.get("closed") or "*" in path or path == "llm.backend":
            continue
        section, key = path.split(".")
        value = cfg[section][key]
        if value not in spec["values"]:
            raise MissingConfigError(
                f"{path} must be one of {spec['values']}, got {value!r}")
    for path, (kind, nullable, minimum) in _NUMBERS.items():
        section, key = path.split(".")
        value = cfg[section][key]
        if value is None and nullable:
            continue
        ok_type = (int, float) if kind == "seconds" else (int,)
        if (isinstance(value, bool) or not isinstance(value, ok_type)
                or value < minimum):
            want = ("a number of seconds" if kind == "seconds" else "an integer")
            raise MissingConfigError(
                f"{path} must be {want} >= {minimum}"
                f"{' or null' if nullable else ''}, got {value!r}")
    for path in _SWITCHES:
        section, key = path.split(".")
        value = cfg[section][key]
        if not isinstance(value, bool):
            raise MissingConfigError(
                f"{path} must be true or false, got {value!r}")


#: One config source, or several. A sequence is a stack: later wins.
ConfigSource = dict | str | Path


def _layers(user: ConfigSource | Sequence[ConfigSource] | None) -> list:
    """The user level as a list, whether one source was given or several.

    A ``dict``, ``str`` or ``Path`` is one source, not a sequence of them; str
    is also iterable and would otherwise be taken apart per character.
    """
    if user is None:
        return []
    if isinstance(user, (str, Path, dict)):
        return [user]
    return list(user)


def load_config(user: ConfigSource | Sequence[ConfigSource] | None = None,
                overrides: dict | None = None,
                require: bool = True) -> dict:
    """Merge the levels, resolve the live profile, and demand completeness.

    ``user`` is one source or a stack of them, each merged over the last; only
    the result has to be complete. ``require=False`` returns the merged config
    with required values still unfilled, which is the console's first-run state;
    anything that runs a model leaves it True. Raises MissingConfigError on a
    legacy shape, a bad scheduling value, or a required value left ``???``.
    """
    cfg = copy.deepcopy(DEFAULTS)       # deep, so a caller mutating the result cannot pollute the defaults table
    #: The file layers in merge order, kept so the completeness failure below
    #: can name a file to open.
    files: list[str] = []
    for layer in _layers(user):
        if isinstance(layer, (str, Path)):
            where = str(layer)
            files.append(where)
            layer = yaml.safe_load(Path(layer).read_text(encoding="utf-8")) or {}
        else:
            where = "config dict"
        # Per layer, so the complaint names the file carrying the legacy key
        # rather than the merged result, which is not a file anybody can open.
        _reject_legacy(layer, where)
        _reject_unknown(layer, where)
        cfg = _deep_merge(cfg, layer)
    # An override may do either of two things to llm, resolving in opposite
    # directions: fill a slot, which must then be lifted and so has to land
    # before resolution, or name llm.model as a one-off, which must survive
    # resolution and so is re-applied after. Merge order can satisfy only one.
    one_off = {k: v for k, v in (overrides.get("llm") or {}).items()
               if k in _LIFTED} if overrides else {}
    switched = bool(overrides) and "backend" in (overrides.get("llm") or {})
    if overrides:
        _reject_legacy(overrides, "overrides", stored=False)
        _reject_unknown(overrides, "overrides")
        cfg = _deep_merge(cfg, overrides)
    _resolve_profile(cfg, force=switched)
    cfg["llm"].update(one_off)
    _anchor_paths(cfg)
    _validate_values(cfg)
    if require and (missing := missing_keys(cfg)):
        # Name the file to open, not only the key: on a fresh checkout
        # ensure_config created config.yaml moments ago and the reader does not
        # yet know it exists. The first layer is the one to edit — a stack puts
        # the private file underneath, and the overlays above may carry no
        # credential.
        where = ""
        if files:
            where = f"; fill them in {Path(files[0]).resolve()}"
            if len(files) > 1:
                where += f" (the first of {len(files)} config files)"
        raise MissingConfigError(
            f"required config left unfilled (???): {missing}{where}")
    return cfg
