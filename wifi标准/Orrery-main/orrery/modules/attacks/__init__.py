"""Attack reproduction: turn the attack ProVerif found behind a false verdict
into a step-by-step script a person can watch.

The solver already reconstructed a concrete execution when it answered false;
nothing here re-decides the verdict. ``locate`` finds the goal-only solver file
that answered, ``reproduce`` runs it once more with the long trace display and
``-graph``, ``graph`` reads the dot file that run writes, and ``script`` turns
it into lanes and steps. ``terms`` is the small amount of term structure all of
that needs.
"""
