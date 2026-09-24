"""The one error type of the review layer: a stable API error code plus its HTTP status."""
from __future__ import annotations


class DecisionError(Exception):
    """A review action that cannot happen. `code` is a contract ErrorCode (contract.ts)."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def invalid() -> DecisionError:
    return DecisionError("invalid_decision", 422)


def not_found() -> DecisionError:
    return DecisionError("document_not_found", 404)
