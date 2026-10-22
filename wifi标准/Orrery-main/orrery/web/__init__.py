"""The web console: a FastAPI app over the run registry, plus the static page
that reads its event stream.

Every fact about the engine — the vocabulary, a run's files, the config's
shape, how a run is started — comes from ``orrery.api``; what lives here is
HTTP shapes, SSE framing and the page. Conventions: the ``web-console`` skill.
"""
