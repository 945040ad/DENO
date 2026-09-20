"""Domain exceptions. Transport-agnostic: the API maps `code` to an HTTP status.

`message` is safe to show to users. Internal detail belongs in logs, never in
the exception message.
"""

from __future__ import annotations


class DenoError(Exception):
    code = "internal_error"
    message = "Something went wrong on our side."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class NotFound(DenoError):
    code = "not_found"
    message = "Not found."


class PermissionDenied(DenoError):
    code = "permission_denied"
    message = "You don't have access to this."


class InvalidInput(DenoError):
    code = "invalid_input"
    message = "The request is invalid."


class Conflict(DenoError):
    code = "conflict"
    message = "That conflicts with the current state."


class QuotaExceeded(DenoError):
    code = "quota_exceeded"
    message = "You've reached your plan's limit."


class RateLimited(DenoError):
    code = "rate_limited"
    message = "Too many requests. Slow down and try again shortly."


class UpstreamUnavailable(DenoError):
    code = "upstream_unavailable"
    message = "A service we depend on is unavailable. Try again shortly."
