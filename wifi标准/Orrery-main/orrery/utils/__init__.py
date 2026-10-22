"""Developer-facing utilities that ship with the package but sit outside the
pipeline: nothing under `orrery/` imports them, and they import freely from the
layers below. One of them: `prompts`, the preview behind `orrery prompt`, which
renders every request the pipeline can send without paying for a run.
"""
