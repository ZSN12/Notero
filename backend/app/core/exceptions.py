"""Unified exception hierarchy for Notero.

All service-layer exceptions should inherit from NoteroServiceError.
API layer catches these and converts to appropriate HTTP responses.
"""

from typing import Optional


class NoteroServiceError(Exception):
    """Base exception for all domain/service errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        code: str = "internal_error",
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code}, status={self.status_code}, message={self.message!r})"


# -- Authentication & Authorization --

class AuthenticationError(NoteroServiceError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401, code="authentication_failed")


class AuthorizationError(NoteroServiceError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(message, status_code=403, code="access_denied")


# -- Resource Not Found --

class ResourceNotFoundError(NoteroServiceError):
    def __init__(self, resource: str = "Resource", identifier: Optional[str] = None):
        msg = f"{resource} not found"
        if identifier:
            msg = f"{resource} '{identifier}' not found"
        super().__init__(msg, status_code=404, code="resource_not_found")


# -- Validation --

class ValidationError(NoteroServiceError):
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message, status_code=400, code="validation_error")
        self.field = field


# -- LLM / AI Provider --

class LLMUnavailableError(NoteroServiceError):
    def __init__(self, message: str = "AI service is currently unavailable"):
        super().__init__(message, status_code=503, code="llm_unavailable")


class LLMTimeoutError(NoteroServiceError):
    def __init__(self, message: str = "AI service timed out"):
        super().__init__(message, status_code=504, code="llm_timeout")


class LLMContentRejectedError(NoteroServiceError):
    def __init__(self, message: str = "AI output was rejected by safety filter"):
        super().__init__(message, status_code=422, code="llm_content_rejected")


# -- External Services --

class ExternalServiceError(NoteroServiceError):
    def __init__(self, service: str, message: str):
        super().__init__(
            f"{service} error: {message}",
            status_code=502,
            code="external_service_error",
        )
        self.service = service


# -- Processing / State --

class ProcessingError(NoteroServiceError):
    def __init__(self, message: str = "Processing failed"):
        super().__init__(message, status_code=500, code="processing_error")


class StateConflictError(NoteroServiceError):
    def __init__(self, message: str = "State conflict"):
        super().__init__(message, status_code=409, code="state_conflict")
