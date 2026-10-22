"""The batch runner's one entry point.

    python -m experiments.batch {run,status,stop} {main,claims,baseline}

`batches.py::RUNNERS` maps each batch to its runner. Only the `-m` form
puts the Orrery root on `sys.path`, which everything under `experiments/` needs.
"""

from experiments.batch.common import main

main()
