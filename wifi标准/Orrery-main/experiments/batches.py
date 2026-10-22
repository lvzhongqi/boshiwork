"""The paper's three batches, as config-override dicts.

A batch is which protocols (``protocols.yaml``), what settings they run
under (this file), and whose credential pays (``config.yaml``, per machine).
The settings reach a run as a Python dict handed to ``launch(overrides=...)``,
so only a batch's name crosses the process boundary. ``llm`` and ``paths``
belong to the machine that runs it and are not settable here.
"""

from __future__ import annotations

#: What the paper's numbers were produced under. Neither is a setting: the
#: runner prints each beside whatever is actually live, so a reader comparing
#: their own numbers with the paper's can see whether the comparison is like
#: with like.
PAPER_MODEL = "gpt-5.6-sol"
#: The solver version matters as much as the model: `outcome.py::classify` reads
#: ProVerif's own prose, so a reworded answer changes a verdict silently, and a
#: query that fits the timeout under one release can exhaust it under another.
#: It lives here because ProVerif prints no banner and the runs carry no version.
PAPER_PROVERIF = "2.05"


#: What all three batches ran under, pinned here so it keeps stating what the
#: paper's runs used as the built-in defaults move on.
_SHARED = {
    "proverif": {"timeout_s": 300},     # the built-in default is 180
    "agent": {"max_tool_calls": 120},   # the built-in default is 40
    "prompt_lang": "en",                # unset by default; these ran in English
}

#: The main line: the full node pipeline, extraction through cross-check. The
#: corpus states the claims and the pipeline answers them; everything else about
#: the model is extracted.
MAIN = _SHARED | {
    "inputs": {
        "lib_principals": False,        # extracted, not supplied
        "lib_flow": False,              # extracted, not supplied
        "lib_claims": True,             # the corpus states the claims
        "end_point": "scenarios",       # run the whole table
    },
}

#: Claims extraction measured on its own: the pipeline is handed the corpus's
#: principals and flow and stops as soon as claims are out, so the measurement
#: covers the claims step rather than the four steps that would feed it.
CLAIMS = _SHARED | {
    "inputs": {
        "lib_principals": True,         # supplied, not extracted
        "lib_flow": True,               # supplied, not extracted
        "lib_claims": False,            # this is what the batch measures
        "end_point": "claims",          # stop here; the rest is main's job
    },
}

#: The one-shot control group. It carries no ``inputs``: the baseline reads the
#: corpus's claims files directly and has no node table to stop, and
#: ``agent.max_tool_calls`` is inert -- one prompt, one reply, no tool loop.
#: This one ran in two waves, so 114 of the 162 published baseline runs
#: had a 180 s ProVerif budget and 48 had the 300 s pinned here; each run records
#: the budget it had in its own ``config.yaml``.
BASELINE = dict(_SHARED)

#: Which runner executes a batch, by module name under ``batch/``. It is part
#: of what a batch is: `baseline` is the control group because the one-shot
#: runner drives it, while `main` and `claims` are two batches over one engine.
#: The value is a module name, so this file stays dependency-free -- the
#: `batch/` runner imports this module, and the dependency runs only that way.
RUNNERS = {
    "main": "orrery",
    "claims": "orrery",
    "baseline": "baseline",
}

#: The name a command line takes, and the directory name under ``work_root``.
#: Adding a batch is one entry here and one in ``RUNNERS``.
BATCHES = {
    "main": MAIN,
    "claims": CLAIMS,
    "baseline": BASELINE,
}

assert set(RUNNERS) == set(BATCHES), "every batch needs a runner"
