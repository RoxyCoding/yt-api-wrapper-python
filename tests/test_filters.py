"""Tests for protobuf search filter encoding."""

import base64

from yt_api_wrapper.parsers.filters import encode_search_filters


def test_encode_empty_returns_none() -> None:
    assert encode_search_filters() is None
    assert encode_search_filters(type="all", sort_by="relevance") is None


def test_encode_video_filter() -> None:
    # Field 2 (submessage): field 2 = 1 -> [0x12, 0x02, 0x10, 0x01] -> "EgIQAQ"
    assert encode_search_filters(type="video") == "EgIQAQ"


def test_encode_sort_by_views() -> None:
    # Field 1 = 2 -> [0x08, 0x02] -> "CAI"
    assert encode_search_filters(sort_by="views") == "CAI"


def test_encode_combined_filters() -> None:
    sp = encode_search_filters(
        type="video",
        upload_date="week",
        duration="long",
        sort_by="views",
        features=["hd", "4k", "subtitles"],
    )
    assert sp is not None
    padded = sp + "=" * (-len(sp) % 4)
    raw = base64.urlsafe_b64decode(padded)
    # Must start with field 1 = 2 (0x08, 0x02) then field 2 length-delimited (0x12)
    assert raw[:3] == bytes([0x08, 0x02, 0x12])
