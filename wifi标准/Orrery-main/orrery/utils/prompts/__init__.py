"""Every request the pipeline can send, rendered to one file each. The command
is `orrery prompt`; the work is in `render`.
"""

from orrery.utils.prompts.render import (
    GROUPS, OUT_DEFAULT, apply_requests, as_markdown, expert_requests,
    extraction_requests, inject_requests, write_all,
)

__all__ = ["GROUPS", "OUT_DEFAULT", "apply_requests", "as_markdown",
           "expert_requests", "extraction_requests", "inject_requests",
           "write_all"]
