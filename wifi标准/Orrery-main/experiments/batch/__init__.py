"""How a set of protocols is run, and nothing about what running them means.

`common.py` is the scheduler: one child process per protocol at a configured
concurrency, with the pid, log and state that let one run be inspected,
interrupted or resumed alone. `orrery.py` and `baseline.py` each give it a
`Runner` (start command, output hook, run-directory reader) it applies as is.
"""
