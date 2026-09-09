from __future__ import annotations


class AgentError(Exception):
    """Base for every failure the agent can surface to a user.

    `user_message` is written for a salesperson, not an engineer: it never
    leaks provider names beyond what the README documents, stack traces, or
    request internals.
    """

    code = "agent_error"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.user_message = message
        self.retryable = retryable


class ConfigurationError(AgentError):
    """A key is missing or rejected. Retrying will not help."""

    code = "configuration_error"


class RateLimitError(AgentError):
    """Provider asked us to slow down. Carries the server's own hint when given."""

    code = "rate_limited"

    def __init__(
        self, message: str, *, retry_after: float | None = None, retryable: bool = True
    ) -> None:
        super().__init__(message, retryable=retryable)
        self.retry_after = retry_after


class ProviderUnavailableError(AgentError):
    """Network failure, timeout, or 5xx from an upstream provider."""

    code = "provider_unavailable"


class InvalidResponseError(AgentError):
    """The model returned something we could not validate into a section."""

    code = "invalid_response"


class NoEvidenceError(AgentError):
    """Search found nothing usable, so there is nothing honest to report."""

    code = "no_evidence"
