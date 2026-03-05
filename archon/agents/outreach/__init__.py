"""Outreach agents."""

from archon.agents.outreach.email_agent import (
    EmailAgent,
    SMTPBackend,
    SendGridBackend,
    SendResult,
    UnsubscribeStore,
    build_unsubscribe_footer,
    personalize,
)

__all__ = [
    "EmailAgent",
    "SMTPBackend",
    "SendGridBackend",
    "SendResult",
    "UnsubscribeStore",
    "personalize",
    "build_unsubscribe_footer",
]
