"""Zero-dependency HTTP client with timeout, retry-with-backoff, and consistent errors."""

from __future__ import annotations

import gzip
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .errors import NetworkError

DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 3


@dataclass
class HttpResponse:
    """Minimal HTTP response returned by custom or default transports."""

    status: int
    body: bytes
    headers: dict[str, str]

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")


Transport = Callable[
    [str, str, dict[str, str], bytes | None, float],
    HttpResponse,
]


def _default_transport(
    url: str,
    method: str,
    headers: dict[str, str],
    data: bytes | None,
    timeout: float,
) -> HttpResponse:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            if resp_headers.get("content-encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            return HttpResponse(status=resp.status, body=raw, headers=resp_headers)
    except urllib.error.HTTPError as err:
        raw = b""
        try:
            raw = err.read()
        except Exception:
            pass
        resp_headers = {k.lower(): v for k, v in err.headers.items()} if err.headers else {}
        return HttpResponse(status=err.code, body=raw, headers=resp_headers)


class HttpClient:
    """Thin urllib wrapper with timeout, retry-with-backoff and consistent errors.

    YouTube rate-limits aggressively, so transient 429/5xx are retried.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        headers: dict[str, str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.base_headers: dict[str, str] = dict(headers) if headers else {}
        self._transport: Transport = transport or _default_transport

    def text(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | bytes | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> str:
        """Fetch ``url`` and return the response body as text."""
        effective_timeout = self.timeout if timeout is None else timeout
        effective_retries = self.retries if retries is None else retries
        merged_headers = {**self.base_headers, **(headers or {})}
        data = body.encode("utf-8") if isinstance(body, str) else body

        last_error: BaseException | None = None

        for attempt in range(effective_retries + 1):
            try:
                response = self._transport(
                    url, method, merged_headers, data, effective_timeout
                )

                # 4xx other than 429 will not get better by retrying.
                if response.status != 429 and response.status < 500 and not response.ok:
                    raise NetworkError(
                        f"YouTube responded {response.status}", status=response.status
                    )

                if response.status == 429 or response.status >= 500:
                    last_error = NetworkError(
                        f"YouTube responded {response.status}", status=response.status
                    )
                    if attempt < effective_retries:
                        time.sleep(_backoff_seconds(attempt))
                        continue
                    raise last_error

                return response.text()
            except NetworkError as err:
                if (
                    err.status is not None
                    and err.status < 500
                    and err.status != 429
                ):
                    raise
                last_error = err
                if attempt < effective_retries:
                    time.sleep(_backoff_seconds(attempt))
                    continue
            except Exception as err:
                last_error = err
                if attempt < effective_retries:
                    time.sleep(_backoff_seconds(attempt))
                    continue

        if isinstance(last_error, NetworkError):
            raise last_error
        raise NetworkError(f"request to {url} failed", cause=last_error)

    def json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | bytes | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> Any:
        """Fetch ``url`` and parse the response body as JSON."""
        raw = self.text(
            url,
            method=method,
            headers=headers,
            body=body,
            timeout=timeout,
            retries=retries,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as err:
            raise NetworkError(
                f"YouTube returned a non-JSON response for {url}", cause=err
            ) from err

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | bytes | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        """Escape hatch for callers that need the raw ``HttpResponse``."""
        effective_timeout = self.timeout if timeout is None else timeout
        merged_headers = {**self.base_headers, **(headers or {})}
        data = body.encode("utf-8") if isinstance(body, str) else body
        response = self._transport(url, method, merged_headers, data, effective_timeout)
        if not response.ok:
            raise NetworkError(
                f"YouTube responded {response.status}", status=response.status
            )
        return response


def _backoff_seconds(attempt: int) -> float:
    """0.5s, 1.5s, 4.5s ... with jitter so parallel callers desynchronise."""
    return 0.5 * (3**attempt) + random.uniform(0.0, 0.4)
