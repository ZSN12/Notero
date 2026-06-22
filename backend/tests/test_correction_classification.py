"""Tests for LLM exception classification."""

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ["SKIP_ASR_PRELOAD"] = "1"

from app.services.term_corrector import classify_correction_exception


class FakeOpenAIError(Exception):
    """Base for fake OpenAI errors."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def test_status_code_400_is_invalid_response():
    exc = FakeOpenAIError("bad request", status_code=400)
    code, message, retryable = classify_correction_exception(exc)
    assert code == "invalid_response"
    assert retryable is False


def test_status_code_401_is_authentication():
    exc = FakeOpenAIError("unauthorized", status_code=401)
    code, message, retryable = classify_correction_exception(exc)
    assert code == "authentication"
    assert retryable is False


def test_status_code_403_is_authentication():
    exc = FakeOpenAIError("forbidden", status_code=403)
    code, message, retryable = classify_correction_exception(exc)
    assert code == "authentication"
    assert retryable is False


def test_status_code_429_is_rate_limit():
    exc = FakeOpenAIError("rate limit", status_code=429)
    code, message, retryable = classify_correction_exception(exc)
    assert code == "rate_limit"
    assert retryable is True


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_status_code_5xx_is_server_error(status_code):
    exc = FakeOpenAIError("server error", status_code=status_code)
    code, message, retryable = classify_correction_exception(exc)
    assert code == "server_error"
    assert retryable is True


def test_bad_request_subclass_before_api_status_error():
    """BadRequestError (400) must not be swallowed by parent APIStatusError."""
    try:
        import openai
    except Exception:  # pragma: no cover
        pytest.skip("openai not installed")

    from unittest.mock import MagicMock
    response = MagicMock()
    response.status_code = 400
    exc = openai.BadRequestError(
        "Invalid parameter",
        response=response,
        body=None,
    )
    # openai errors may not have a real response, but the class hierarchy must
    # be checked in the right order.
    code, message, retryable = classify_correction_exception(exc)
    assert code == "invalid_response"
    assert retryable is False
