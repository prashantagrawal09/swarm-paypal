"""Typed PayPal errors.

Every failure from the real or simulated gateway is raised as a `PayPalError` subclass that
keeps PayPal's own `name`, `debug_id` and issue codes (for example
`MAX_CAPTURE_AMOUNT_EXCEEDED`), so the money engine can react to specific business errors
and support can trace any call in the PayPal dashboard by its debug ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PayPalIssue:
    issue: str
    description: str = ""
    field: str | None = None


@dataclass(eq=False)
class PayPalError(Exception):
    """Base class. `retryable` tells callers whether the same request may be sent again."""

    message: str
    status_code: int | None = None
    name: str | None = None
    debug_id: str | None = None
    details: list[PayPalIssue] = field(default_factory=list)
    operation: str | None = None
    raw: Any = None

    retryable = False

    def __post_init__(self) -> None:
        super().__init__(self.message)

    @property
    def issues(self) -> list[str]:
        return [detail.issue for detail in self.details]

    def has_issue(self, code: str) -> bool:
        return code in self.issues or self.name == code

    def __str__(self) -> str:
        parts = [self.message]
        if self.operation:
            parts.insert(0, f"[{self.operation}]")
        if self.name:
            parts.append(f"name={self.name}")
        if self.issues:
            parts.append(f"issues={','.join(self.issues)}")
        if self.debug_id:
            parts.append(f"debug_id={self.debug_id}")
        if self.status_code:
            parts.append(f"http={self.status_code}")
        return " ".join(parts)


class PayPalConfigError(PayPalError):
    """Missing credentials or an unsafe configuration (for example the live environment)."""


class PayPalAuthError(PayPalError):
    """401/403: bad credentials, expired token, or the app lacks a permission."""


class PayPalValidationError(PayPalError):
    """400: the request was malformed. Fix the request; do not retry."""


class PayPalUnprocessableError(PayPalError):
    """422: valid request that breaks a business rule (capture too large, too soon, ...)."""


class PayPalNotFoundError(PayPalError):
    """404: the resource does not exist (or belongs to another account)."""


class PayPalConflictError(PayPalError):
    """409: for example PREVIOUS_REQUEST_IN_PROGRESS. Safe to retry with the same request ID."""

    retryable = True


class PayPalRateLimitError(PayPalError):
    """429: too many requests."""

    retryable = True


class PayPalServerError(PayPalError):
    """5xx: PayPal-side failure. Safe to retry with the same request ID."""

    retryable = True


class PayPalTransportError(PayPalError):
    """Network failure or timeout before PayPal answered."""

    retryable = True


def error_class_for_status(status_code: int) -> type[PayPalError]:
    if status_code in (401, 403):
        return PayPalAuthError
    if status_code == 404:
        return PayPalNotFoundError
    if status_code == 409:
        return PayPalConflictError
    if status_code == 422:
        return PayPalUnprocessableError
    if status_code == 429:
        return PayPalRateLimitError
    if status_code >= 500:
        return PayPalServerError
    return PayPalValidationError


def error_from_response(
    status_code: int, body: Any, *, operation: str | None = None
) -> PayPalError:
    """Build a typed error from a PayPal error body.

    Handles the REST shape (`name`, `message`, `debug_id`, `details[]`) and the OAuth shape
    (`error`, `error_description`).
    """
    cls = error_class_for_status(status_code)
    if not isinstance(body, dict):
        return cls(
            message=f"PayPal returned HTTP {status_code}",
            status_code=status_code,
            operation=operation,
            raw=body,
        )
    details = [
        PayPalIssue(
            issue=str(item.get("issue", "")),
            description=str(item.get("description", "")),
            field=item.get("field"),
        )
        for item in body.get("details") or []
        if isinstance(item, dict)
    ]
    return cls(
        message=str(
            body.get("message")
            or body.get("error_description")
            or f"PayPal returned HTTP {status_code}"
        ),
        status_code=status_code,
        name=body.get("name") or body.get("error"),
        debug_id=body.get("debug_id"),
        details=details,
        operation=operation,
        raw=body,
    )
