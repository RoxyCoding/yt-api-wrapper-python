"""Tests for HttpClient and InnerTube transport."""

import json

import pytest

from yt_api_wrapper import HttpClient, HttpResponse, InnerTube, NetworkError, ParseError, extract_initial_data


def test_http_client_retries_on_500_then_succeeds() -> None:
    calls = 0

    def transport(url, method, headers, data, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return HttpResponse(status=503, body=b"busy", headers={})
        return HttpResponse(status=200, body=b'{"ok": true}', headers={})

    client = HttpClient(retries=2, transport=transport)
    assert client.json("https://example.com") == {"ok": True}
    assert calls == 2


def test_http_client_does_not_retry_404() -> None:
    calls = 0

    def transport(url, method, headers, data, timeout):
        nonlocal calls
        calls += 1
        return HttpResponse(status=404, body=b"not found", headers={})

    client = HttpClient(retries=3, transport=transport)
    with pytest.raises(NetworkError) as exc_info:
        client.text("https://example.com")
    assert exc_info.value.status == 404
    assert calls == 1


def test_http_client_non_json_raises_network_error() -> None:
    client = HttpClient(
        retries=0,
        transport=lambda *a: HttpResponse(status=200, body=b"<html>nope</html>", headers={}),
    )
    with pytest.raises(NetworkError):
        client.json("https://example.com")


def test_innertube_visitor_data_and_headers() -> None:
    seen_requests: list[tuple[str, dict[str, str], dict | None]] = []

    def transport(url, method, headers, data, timeout):
        if url == "https://www.youtube.com/":
            return HttpResponse(
                status=200,
                body=b'<html>"visitorData":"VISITOR_XYZ"</html>',
                headers={},
            )
        payload = json.loads(data.decode("utf-8")) if data else None
        seen_requests.append((url, headers, payload))
        return HttpResponse(status=200, body=b'{"playabilityStatus":{"status":"OK"}}', headers={})

    http = HttpClient(retries=0, transport=transport)
    it = InnerTube(http=http, client="VISIONOS", region="JP", language="ja")
    resp = it.call("player", {"videoId": "dQw4w9WgXcQ"})

    assert resp["playabilityStatus"]["status"] == "OK"
    assert len(seen_requests) == 1
    url, headers, payload = seen_requests[0]
    assert "/youtubei/v1/player?" in url
    assert headers["X-Goog-Visitor-Id"] == "VISITOR_XYZ"
    assert headers["X-YouTube-Client-Name"] == "101"
    assert payload is not None
    assert payload["context"]["client"]["visitorData"] == "VISITOR_XYZ"
    assert payload["context"]["client"]["gl"] == "JP"
    assert payload["context"]["client"]["hl"] == "ja"


def test_extract_initial_data_handles_braces_in_strings() -> None:
    html = '<html><script>var ytInitialData = {"text": "brace } \\" inside", "n": 42};</script></html>'
    data = extract_initial_data(html, "ytInitialData")
    assert data == {"text": 'brace } " inside', "n": 42}

    with pytest.raises(ParseError):
        extract_initial_data("<html>nothing</html>", "ytInitialData")
