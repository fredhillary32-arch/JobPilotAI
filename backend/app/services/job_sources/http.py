"""Shared, host-pinned HTTP fetching for job-source adapters.

Each adapter names the only HTTPS hosts it may reach. Redirects elsewhere are
refused, responses are size-bounded, and transient failures (timeouts, HTTP 429
and 5xx) are retried a bounded number of times with backoff.
"""
import json
import socket
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.services.job_discovery import SourceFetchError

REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 30.0
USER_AGENT = "JobPilotAI/0.1 (personal local job search)"


class PinnedHostRedirectHandler(HTTPRedirectHandler):
    """Follow redirects only to HTTPS URLs on the allowed hosts."""

    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.hostname not in self.allowed_hosts:
            if fp is not None:
                fp.close()
            raise SourceFetchError("invalid_response")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(request: Request, *, timeout: float, allowed_hosts: frozenset[str]):
    """Network seam; tests replace this function."""
    return build_opener(PinnedHostRedirectHandler(allowed_hosts)).open(request, timeout=timeout)


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after.strip()), MAX_RETRY_AFTER_SECONDS)
    return BACKOFF_SECONDS * (2 ** (attempt - 1))


def fetch_bytes(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in allowed_hosts:
        raise SourceFetchError("invalid_response")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_error = "unavailable"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        retry_after = None
        try:
            with open_url(request, timeout=REQUEST_TIMEOUT_SECONDS, allowed_hosts=allowed_hosts) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise SourceFetchError("too_large")
            return body
        except HTTPError as exc:
            if exc.code == 404:
                raise SourceFetchError("not_found") from None
            if exc.code == 429:
                last_error, retry_after = "rate_limited", exc.headers.get("Retry-After") if exc.headers else None
            elif exc.code >= 500:
                last_error = "unavailable"
            else:
                raise SourceFetchError("unavailable") from None
        except (TimeoutError, socket.timeout):
            last_error = "timeout"
        except URLError as exc:
            if not isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise SourceFetchError("unavailable") from None
            last_error = "timeout"
        if attempt < MAX_ATTEMPTS:
            sleep(_retry_delay(attempt, retry_after))
    raise SourceFetchError(last_error)


def fetch_json(url: str, *, allowed_hosts: frozenset[str], sleep: Callable[[float], None] = time.sleep) -> Any:
    body = fetch_bytes(url, allowed_hosts=allowed_hosts, sleep=sleep)
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SourceFetchError("invalid_response") from None
