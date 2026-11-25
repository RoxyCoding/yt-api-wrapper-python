"""URL and ID parsing helpers for YouTube resources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

from .errors import InvalidArgumentError

_VIDEO_ID = re.compile(r"^[\w-]{11}$")
_CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")
_PLAYLIST_ID = re.compile(r"^(?:PL|UU|LL|RD|OL|FL|TL|WL)[\w-]+$")

_THUMBNAIL_NAMES = {
    "max": "maxresdefault",
    "sd": "sddefault",
    "hq": "hqdefault",
    "mq": "mqdefault",
    "default": "default",
}


@dataclass(frozen=True)
class ChannelInput:
    """Parsed channel reference."""

    kind: Literal["id", "handle", "vanity"]
    value: str


def _parse_url(value: str):
    raw = value if value.startswith(("http://", "https://")) else f"https://{value}"
    parsed = urlparse(raw)
    if not parsed.netloc:
        raise ValueError("missing host")
    return parsed


def parse_video_id(input_str: str) -> str:
    """Accept a bare video id or any YouTube URL shape (watch, youtu.be, shorts,
    embed, live) and return the 11-character id.
    """
    value = input_str.strip()
    if _VIDEO_ID.match(value):
        return value

    try:
        url = _parse_url(value)
    except ValueError as exc:
        raise InvalidArgumentError(f"not a valid video id or URL: {input_str}") from exc

    query_v = parse_qs(url.query).get("v")
    if query_v and _VIDEO_ID.match(query_v[0]):
        return query_v[0]

    segments = [s for s in url.path.split("/") if s]
    hostname = (url.hostname or "").lower()
    if hostname.endswith("youtu.be") and segments and _VIDEO_ID.match(segments[0]):
        return segments[0]

    if len(segments) >= 2 and segments[0] in ("shorts", "embed", "live", "v"):
        if _VIDEO_ID.match(segments[1]):
            return segments[1]

    raise InvalidArgumentError(f"could not find a video id in: {input_str}")


def parse_channel_input(input_str: str) -> ChannelInput:
    """Accept a channel id, @handle, /c/ vanity name, or channel URL."""
    value = input_str.strip()
    if _CHANNEL_ID.match(value):
        return ChannelInput(kind="id", value=value)
    if value.startswith("@"):
        return ChannelInput(kind="handle", value=value[1:])
    if "/" not in value:
        return ChannelInput(kind="vanity", value=value)

    try:
        url = _parse_url(value)
    except ValueError as exc:
        raise InvalidArgumentError(f"not a valid channel id or URL: {input_str}") from exc

    segments = [s for s in url.path.split("/") if s]
    if len(segments) >= 2 and segments[0] == "channel":
        if not _CHANNEL_ID.match(segments[1]):
            raise InvalidArgumentError(f"malformed channel id: {segments[1]}")
        return ChannelInput(kind="id", value=segments[1])
    if segments and segments[0].startswith("@"):
        return ChannelInput(kind="handle", value=segments[0][1:])
    if len(segments) >= 2 and segments[0] in ("c", "user"):
        return ChannelInput(kind="vanity", value=segments[1])

    raise InvalidArgumentError(f"could not find a channel in: {input_str}")


def parse_playlist_id(input_str: str) -> str:
    """Accept a playlist id or any URL containing ``list=``."""
    value = input_str.strip()
    if _PLAYLIST_ID.match(value) and "/" not in value:
        return value

    try:
        url = _parse_url(value)
        list_vals = parse_qs(url.query).get("list")
        if list_vals and list_vals[0]:
            return list_vals[0]
        segments = [s for s in url.path.split("/") if s]
        if len(segments) >= 2 and segments[0] == "playlist":
            return segments[1]
    except ValueError:
        pass

    raise InvalidArgumentError(f"could not find a playlist id in: {input_str}")


def video_url(video_id: str) -> str:
    """Canonical watch URL for a video id."""
    return f"https://www.youtube.com/watch?v={video_id}"


def playlist_url(playlist_id: str) -> str:
    """Canonical playlist URL."""
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def channel_url(channel_id: str) -> str:
    """Canonical channel URL."""
    return f"https://www.youtube.com/channel/{channel_id}"


def thumbnail_url(
    video_id: str,
    quality: Literal["max", "sd", "hq", "mq", "default"] = "hq",
) -> str:
    """Thumbnail URL for a video without a network round trip."""
    return f"https://i.ytimg.com/vi/{video_id}/{_THUMBNAIL_NAMES[quality]}.jpg"
