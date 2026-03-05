"""Outbound communication agents."""

from archon.agents.outbound.email_agent import (
    EmailAgent,
    EmailSendResult,
    EmailTransport,
    OutboundEmail,
    SendGridConfig,
    SendGridEmailTransport,
    SMTPConfig,
    SMTPEmailTransport,
    build_email_transport_from_env,
)
from archon.agents.outbound.webchat_agent import (
    WebChatAgent,
    WebChatMessage,
    WebChatSendResult,
    WebChatTransport,
    WebhookWebChatConfig,
    WebhookWebChatTransport,
    build_webchat_transport_from_env,
)

__all__ = [
    "EmailAgent",
    "EmailTransport",
    "OutboundEmail",
    "EmailSendResult",
    "SMTPConfig",
    "SMTPEmailTransport",
    "SendGridConfig",
    "SendGridEmailTransport",
    "build_email_transport_from_env",
    "WebChatAgent",
    "WebChatMessage",
    "WebChatSendResult",
    "WebChatTransport",
    "WebhookWebChatConfig",
    "WebhookWebChatTransport",
    "build_webchat_transport_from_env",
]
