"""Tests for URL and ID parsing utilities."""

import pytest

from yt_api_wrapper import (
    ChannelInput,
    InvalidArgumentError,
    channel_url,
    parse_channel_input,
    parse_playlist_id,
    parse_video_id,
    playlist_url,
    thumbnail_url,
    video_url,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("  dQw4w9WgXcQ  ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_parse_video_id_valid(raw: str, expected: str) -> None:
    assert parse_video_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "short", "https://example.com/nope", "not a url"])
def test_parse_video_id_invalid(raw: str) -> None:
    with pytest.raises(InvalidArgumentError):
        parse_video_id(raw)


def test_parse_channel_input() -> None:
    uc = "UCX6OQ3DkcsbYNE6H8uQQuVA"
    assert parse_channel_input(uc) == ChannelInput(kind="id", value=uc)
    assert parse_channel_input("@MrBeast") == ChannelInput(kind="handle", value="MrBeast")
    assert parse_channel_input("veritasium") == ChannelInput(kind="vanity", value="veritasium")
    assert parse_channel_input(f"https://www.youtube.com/channel/{uc}") == ChannelInput(
        kind="id", value=uc
    )
    assert parse_channel_input("https://www.youtube.com/@MrBeast/videos") == ChannelInput(
        kind="handle", value="MrBeast"
    )
    assert parse_channel_input("https://www.youtube.com/c/HikakinTV") == ChannelInput(
        kind="vanity", value="HikakinTV"
    )
    assert parse_channel_input("https://www.youtube.com/user/PewDiePie") == ChannelInput(
        kind="vanity", value="PewDiePie"
    )

    with pytest.raises(InvalidArgumentError):
        parse_channel_input("https://www.youtube.com/channel/badid")


def test_parse_playlist_id() -> None:
    assert parse_playlist_id("PL1234567890abcdef") == "PL1234567890abcdef"
    assert (
        parse_playlist_id("https://www.youtube.com/playlist?list=PL1234567890abcdef")
        == "PL1234567890abcdef"
    )
    assert (
        parse_playlist_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ")
        == "RDdQw4w9WgXcQ"
    )
    with pytest.raises(InvalidArgumentError):
        parse_playlist_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


def test_url_builders() -> None:
    assert video_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert playlist_url("PL123") == "https://www.youtube.com/playlist?list=PL123"
    assert channel_url("UC123") == "https://www.youtube.com/channel/UC123"
    assert thumbnail_url("dQw4w9WgXcQ") == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert (
        thumbnail_url("dQw4w9WgXcQ", "max")
        == "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
    )
