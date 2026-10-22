"""Everything about running experiments; nothing about what a run produces.

`batches.py` holds each experiment's config overrides, `protocols.yaml` the
targets, `config.yaml` this machine's paths and concurrency (a separate file
from the root `config.yaml`); `batch/` runs them, `oneshot/` is the baseline,
`reproduce.py` writes the tables. Results land in `work_root` on the run host.
"""
