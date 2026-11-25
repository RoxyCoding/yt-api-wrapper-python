"""Low-level InnerTube JSON API transport."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from ..errors import ParseError
from ..http import HttpClient


@dataclass(frozen=True)
class InnerTubeClientConfig:
    """Client identity sent in the InnerTube context envelope."""

    client_name: str
    client_version: str
    client_name_id: int
    user_agent: str
    extra: dict[str, Any] = field(default_factory=dict)


CLIENTS: dict[str, InnerTubeClientConfig] = {
    "WEB": InnerTubeClientConfig(
        client_name="WEB",
        client_version="2.20260828.01.00",
        client_name_id=1,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
    ),
    "MWEB": InnerTubeClientConfig(
        client_name="MWEB",
        client_version="2.20260828.01.00",
        client_name_id=2,
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 "
            "Mobile/15E148 Safari/604.1"
        ),
    ),
    "ANDROID": InnerTubeClientConfig(
        client_name="ANDROID",
        client_version="20.10.38",
        client_name_id=3,
        user_agent="com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip",
        extra={
            "androidSdkVersion": 34,
            "osName": "Android",
            "osVersion": "14",
            "platform": "MOBILE",
        },
    ),
    "IOS": InnerTubeClientConfig(
        client_name="IOS",
        client_version="20.10.4",
        client_name_id=5,
        user_agent=(
            "com.google.ios.youtube/20.10.4 "
            "(iPhone16,2; U; CPU iOS 18_3 like Mac OS X)"
        ),
        extra={
            "osName": "iPhone",
            "osVersion": "18.3.0.22D63",
            "deviceMake": "Apple",
            "deviceModel": "iPhone16,2",
            "platform": "MOBILE",
        },
    ),
    "VISIONOS": InnerTubeClientConfig(
        client_name="VISIONOS",
        client_version="1.02",
        client_name_id=101,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/26.0 Safari/605.1.15"
        ),
        extra={
            "deviceMake": "Apple",
            "deviceModel": "RealityDevice17,1",
            "osName": "visionOS",
            "osVersion": "26.5.23O471",
        },
    ),
    "TV_EMBEDDED": InnerTubeClientConfig(
        client_name="TVHTML5_SIMPLY_EMBEDDED_PLAYER",
        client_version="2.0",
        client_name_id=85,
        user_agent=(
            "Mozilla/5.0 (PlayStation; PlayStation 4/12.00) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko)"
        ),
    ),
}

# Public InnerTube key shipped in every YouTube web page. Not a secret.
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
_BASE_URL = "https://www.youtube.com/youtubei/v1"
_VISITOR_RE = re.compile(r'"visitorData":"(.*?)"')


class InnerTube:
    """Low-level InnerTube transport: builds the context envelope and posts it."""

    def __init__(
        self,
        *,
        http: HttpClient,
        client: str = "WEB",
        region: str = "US",
        language: str = "en",
        cookie: str | None = None,
        visitor_data: str | None = None,
    ) -> None:
        self._http = http
        self.client: InnerTubeClientConfig = CLIENTS[client]
        self.region = region
        self.language = language
        self._cookie = cookie
        self._visitor_data: str | None = visitor_data
        self._visitor_lock = threading.Lock()

    def ensure_visitor_data(self) -> str | None:
        """Fetch (once) an anonymous visitor id from the YouTube homepage.

        Requests without it are treated as untrusted and get UNPLAYABLE back.
        Failure is non-fatal: browse/search still work without it.
        """
        if self._visitor_data:
            return self._visitor_data

        with self._visitor_lock:
            if self._visitor_data:
                return self._visitor_data
            try:
                html = self.page("/")
                match = _VISITOR_RE.search(html)
                self._visitor_data = match.group(1) if match else None
            except Exception:
                return None
            return self._visitor_data

    def with_client(self, client: str) -> InnerTube:
        """Return a copy of this transport bound to a different client identity."""
        return InnerTube(
            http=self._http,
            client=client,
            region=self.region,
            language=self.language,
            cookie=self._cookie,
            visitor_data=self._visitor_data,
        )

    def _build_context(self) -> dict[str, Any]:
        client_ctx: dict[str, Any] = {
            "clientName": self.client.client_name,
            "clientVersion": self.client.client_version,
            "hl": self.language,
            "gl": self.region,
            "userAgent": self.client.user_agent,
            **self.client.extra,
        }
        if self._visitor_data:
            client_ctx["visitorData"] = self._visitor_data
        return {
            "client": client_ctx,
            "user": {"lockedSafetyMode": False},
            "request": {"useSsl": True},
        }

    def call(self, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        """Post to an InnerTube endpoint such as ``player``, ``search``, or ``browse``."""
        if endpoint == "player":
            self.ensure_visitor_data()

        url = f"{_BASE_URL}/{endpoint}?key={INNERTUBE_KEY}&prettyPrint=false"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": self.client.user_agent,
            "X-YouTube-Client-Name": str(self.client.client_name_id),
            "X-YouTube-Client-Version": self.client.client_version,
            "Accept-Language": f"{self.language},en;q=0.9",
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        if self._visitor_data:
            headers["X-Goog-Visitor-Id"] = self._visitor_data

        body = json.dumps({"context": self._build_context(), **(payload or {})})
        data = self._http.json(url, method="POST", headers=headers, body=body)

        if not isinstance(data, dict):
            raise ParseError(f"InnerTube {endpoint} returned a non-object response")
        return data

    def page(self, path: str) -> str:
        """Fetch an ordinary youtube.com HTML page (used for ytInitialData scraping)."""
        url = path if path.startswith(("http://", "https://")) else f"https://www.youtube.com{path}"
        return self._http.text(
            url,
            headers={
                "User-Agent": CLIENTS["WEB"].user_agent,
                "Accept-Language": f"{self.language},en;q=0.9",
                "Cookie": self._cookie or f"PREF=hl={self.language}&gl={self.region}; SOCS=CAI",
            },
        )

    def continue_(self, endpoint: str, token: str) -> Any:
        """Follow a continuation token on any browsable endpoint."""
        return self.call(endpoint, {"continuation": token})


def extract_initial_data(html: str, variable: str) -> Any:
    """Extract ``ytInitialData`` / ``ytInitialPlayerResponse`` blobs from an HTML page."""
    marker = f"{variable} = "
    start = html.find(marker)
    if start == -1:
        raise ParseError(
            f"{variable} not found in page (YouTube markup may have changed)"
        )
    json_start = start + len(marker)
    raw_json = _slice_balanced_json(html, json_start)
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as err:
        raise ParseError(f"failed to parse {variable}", cause=err) from err


def _slice_balanced_json(source: str, start: int) -> str:
    if start >= len(source):
        raise ParseError("expected a JSON object or array")
    opening = source[start]
    if opening not in ("{", "["):
        raise ParseError("expected a JSON object or array")
    closing = "]" if opening == "[" else "}"

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(source)):
        ch = source[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return source[start : i + 1]

    raise ParseError("unterminated JSON blob in page")
