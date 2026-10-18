"""
Async HTTP base client for TonAPI.

Handles:
- Bearer authentication
- Connection and read timeouts
- Exponential backoff with jitter on transient failures
- Retry-After header respect
- Safe error messages (no credentials in exceptions)
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.logging_config import get_logger
from security.redaction import redact_url, safe_error_message

log = get_logger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, _RetryableHTTPError):
        return True
    return True
    
    
class _RetryableHTTPError(Exception):
    """Sentinel raised internally when a retryable status code is received."""
    
    def __init__(self, status_code: int, retry_after: float | None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"HTTP {status_code}")
        
        
class class ProviderError(Exception):
    """Non-retryable provider error surfaced to callers."""


class ProviderUnavailableError(ProviderError):
    """Provider returned a 5xx after retries were exhausted."""


class ProviderRateLimitError(ProviderError):
    """Provider returned 429 after retries were exhausted."""


class AccountNotFoundError(ProviderError):
    """Account does not exist on-chain (404)."""


class BaseHTTPClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BaseHTTPClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("Client must be used as an async context manager")
        return self._client

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """
        Perform a GET request with retry logic.

        Returns parsed JSON.
        Raises ProviderError subclasses on unrecoverable failure.
        """
        url = f"{self._base_url}{path}"

        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(4),
            wait=wait_exponential_jitter(initial=1, max=30, jitter=2),
            reraise=False,
        )
        async def _attempt() -> Any:
            try:
                resp = await self._http.get(path, params=params)
            except httpx.TimeoutException as exc:
                log.warning("provider_timeout", url=redact_url(url))
                raise

            if resp.status_code == 404:
                raise AccountNotFoundError(
                    f"Account not found: {redact_url(url)}"
                )

            if resp.status_code == 401:
                raise ProviderError(
                    "Provider authentication failed — check TONAPI_API_KEY"
                )

            if resp.status_code in _RETRYABLE_STATUS:
                retry_after_raw = resp.headers.get("Retry-After")
                retry_after = (
                    float(retry_after_raw) if retry_after_raw else None
                )
                if retry_after:
                    wait = min(retry_after, 60.0) + random.uniform(0, 1)
                    log.warning(
                        "provider_rate_limit",
                        status=resp.status_code,
                        retry_after_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                raise _RetryableHTTPError(resp.status_code, retry_after)

            if not resp.is_success:
                raise ProviderError(
                    f"Provider returned HTTP {resp.status_code}"
                )

            try:
                return resp.json()
            except Exception as exc:
                raise ProviderError(
                    f"Malformed provider response: {safe_error_message(exc)}"
                ) from exc

        try:
            return await _attempt()
        except RetryError as exc:
            cause = exc.last_attempt.exception()
            if isinstance(cause, _RetryableHTTPError):
                if cause.status_code == 429:
                    raise ProviderRateLimitError(
                        "Provider rate limit exceeded after retries"
                    ) from exc
                raise ProviderUnavailableError(
                    f"Provider unavailable after retries (HTTP {cause.status_code})"
                ) from exc
            raise ProviderUnavailableError(
                "Provider request failed after retries"
            ) from exc
        except AccountNotFoundError:
            raise
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(safe_error_message(exc)) from exc