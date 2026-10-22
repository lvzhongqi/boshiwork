"""The api layer: the only engine surface a front end may import.

``orrery/web`` and ``orrery/main.py`` ask this package for vocabulary, run
directories, config shape, corpus inputs and how a run is started;
``tests/contracts/test_layering.py`` enforces that they import nothing below
it. The event types are re-exported because ``Host.on_event`` hands them out.
"""

from orrery.api.host import Host
from orrery.services.events import (
    KNOWN, AwaitingApproval, AwaitingConfirm, Event, ExpertAsked,
    ExpertReplied, ReviewClosed,
)
from orrery.services.logs import setup_logger

__all__ = ["Host", "Event", "KNOWN", "AwaitingApproval", "AwaitingConfirm",
           "ExpertAsked", "ExpertReplied", "ReviewClosed", "setup_logger"]
