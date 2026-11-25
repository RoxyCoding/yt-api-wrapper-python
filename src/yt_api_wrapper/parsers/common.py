"""Common traversal and text/count/duration parsing helpers."""

from __future__ import annotations

import math
import re
from typing import Any

from ..models import ChannelRef, Thumbnail

_COUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMBkmb万億千]?)")
_CHANNEL_URL_RE = re.compile(r"/channel/(UC[\w-]+)")

_MULTIPLIERS: dict[str, float] = {
    "K": 1e3,
    "k": 1e3,
    "M": 1e6,
    "m": 1e6,
    "B": 1e9,
    "b": 1e9,
    "千": 1e3,
    "万": 1e4,
    "億": 1e8,
}


def read_text(node: Any) -> str | None:
    """Flatten YouTube's ``{ simpleText }`` / ``{ runs: [...] }`` text shapes to a string."""
    if node is None:
        return None
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    if isinstance(node.get("simpleText"), str):
        return node["simpleText"]
    runs = node.get("runs")
    if isinstance(runs, list):
        return "".join(
            run.get("text", "") if isinstance(run, dict) and isinstance(run.get("text"), str) else ""
            for run in runs
        )
    if node.get("content") is not None:
        return read_text(node["content"])
    return None


def read_text_or(node: Any, fallback: str = "") -> str:
    """Same as :func:`read_text` but never returns ``None``."""
    result = read_text(node)
    return fallback if result is None else result


def read_thumbnails(node: Any) -> list[Thumbnail]:
    """Normalise a thumbnail container into a width-ascending list."""
    items: Any = None
    if isinstance(node, list):
        items = node
    elif isinstance(node, dict):
        if isinstance(node.get("thumbnails"), list):
            items = node["thumbnails"]
        elif isinstance(node.get("thumbnail"), dict) and isinstance(
            node["thumbnail"].get("thumbnails"), list
        ):
            items = node["thumbnail"]["thumbnails"]
        elif isinstance(node.get("sources"), list):
            items = node["sources"]

    if not isinstance(items, list):
        return []

    thumbnails: list[Thumbnail] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str):
            continue
        if url.startswith("//"):
            url = f"https:{url}"
        thumbnails.append(
            Thumbnail(
                url=url,
                width=safe_int(item.get("width")) or 0,
                height=safe_int(item.get("height")) or 0,
            )
        )

    thumbnails.sort(key=lambda t: t.width)
    return thumbnails


def parse_count(text: str | int | None) -> int | None:
    """Parse counts YouTube renders as prose: ``"1,234,567 views"``, ``"1.2M subscribers"``,
    ``"2.3万 回視聴"``. Returns ``None`` when no number can be recovered.
    """
    if text is None:
        return None
    if isinstance(text, int) and not isinstance(text, bool):
        return text
    if not isinstance(text, str) or not text:
        return None

    cleaned = text.replace(",", "").replace("\u00a0", " ")
    match = _COUNT_RE.search(cleaned)
    if not match:
        return None

    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None

    multiplier = _MULTIPLIERS.get(match.group(2), 1.0)
    return int(round(value * multiplier))


def parse_duration(text: str | None) -> int | None:
    """Parse ``"1:02:03"`` / ``"4:05"`` / ``"45"`` into seconds."""
    if not text:
        return None
    parts = text.strip().split(":")
    total = 0
    for part in parts:
        try:
            num = int(part, 10)
        except ValueError:
            return None
        total = total * 60 + num
    return total


def format_duration(seconds: int | float) -> str:
    """Format seconds back into ``"1:02:03"`` or ``"4:05"``."""
    s = max(0, int(seconds))
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def safe_int(value: Any) -> int | None:
    """Safely parse an integer from a string or number, or return ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return int(value, 10)
        except ValueError:
            return None
    return None


def read_channel_id(node: Any) -> str | None:
    """Pull a channel id out of any of the navigation shapes YouTube uses."""
    if not isinstance(node, dict):
        return None

    nav = node.get("navigationEndpoint")
    if isinstance(nav, dict):
        browse = nav.get("browseEndpoint")
        if isinstance(browse, dict) and isinstance(browse.get("browseId"), str):
            return browse["browseId"]

    browse = node.get("browseEndpoint")
    if isinstance(browse, dict) and isinstance(browse.get("browseId"), str):
        return browse["browseId"]

    if isinstance(nav, dict):
        web_meta = nav.get("commandMetadata", {}).get("webCommandMetadata", {})
        url = web_meta.get("url") if isinstance(web_meta, dict) else None
        if isinstance(url, str):
            match = _CHANNEL_URL_RE.search(url)
            if match:
                return match.group(1)

    return None


def read_canonical_url(node: Any) -> str | None:
    """Resolve a renderer's navigation endpoint to an absolute youtube.com URL."""
    if not isinstance(node, dict):
        return None

    nav = node.get("navigationEndpoint")
    path = None
    if isinstance(nav, dict):
        cmd = nav.get("commandMetadata")
        if isinstance(cmd, dict):
            web = cmd.get("webCommandMetadata")
            if isinstance(web, dict):
                path = web.get("url")
    if path is None:
        cmd = node.get("commandMetadata")
        if isinstance(cmd, dict):
            web = cmd.get("webCommandMetadata")
            if isinstance(web, dict):
                path = web.get("url")

    if not isinstance(path, str):
        return None
    return path if path.startswith("http") else f"https://www.youtube.com{path}"


def has_verified_badge(badges: Any) -> bool:
    """True when any badge marks the channel as verified or an official artist."""
    if not isinstance(badges, list):
        return False
    for badge in badges:
        if not isinstance(badge, dict):
            continue
        style = (badge.get("metadataBadgeRenderer") or {}).get("style", "")
        if isinstance(style, str) and ("VERIFIED" in style or "OFFICIAL_ARTIST" in style):
            return True
    return False


def read_channel_ref(node: Any, thumbnails: Any = None) -> ChannelRef | None:
    """Build a :class:`ChannelRef` from an owner/byline renderer."""
    if not node:
        return None

    runs = node.get("runs") if isinstance(node, dict) else None
    run = runs[0] if isinstance(runs, list) and runs else node
    name = read_text(node) or read_text(run.get("text") if isinstance(run, dict) else None)
    if not name:
        return None

    channel_id = read_channel_id(run) or read_channel_id(node)
    url = read_canonical_url(run) or (
        f"https://www.youtube.com/channel/{channel_id}" if channel_id else None
    )

    badges = None
    if isinstance(node, dict):
        badges = node.get("badges") or node.get("ownerBadges")

    return ChannelRef(
        id=channel_id,
        name=name,
        url=url,
        thumbnails=read_thumbnails(thumbnails),
        verified=has_verified_badge(badges),
    )


def find_all(root: Any, key: str, limit: int | None = None) -> list[Any]:
    """Depth-first search for every value stored under ``key`` anywhere in ``root``."""
    found: list[Any] = []
    stack: list[Any] = [root]

    while stack and (limit is None or len(found) < limit):
        node = stack.pop()
        if isinstance(node, list):
            for i in range(len(node) - 1, -1, -1):
                stack.append(node[i])
            continue
        if not isinstance(node, dict):
            continue

        children: list[Any] = []
        for k, value in node.items():
            if k == key:
                found.append(value)
                if limit is not None and len(found) >= limit:
                    break
            if isinstance(value, (dict, list)):
                children.append(value)
        for child in reversed(children):
            stack.append(child)

    return found


def find_first(root: Any, key: str) -> Any:
    """First match of :func:`find_all`, or ``None``."""
    results = find_all(root, key, limit=1)
    return results[0] if results else None


def read_continuation(node: Any) -> str | None:
    """Collect the first continuation token reachable from a response fragment."""
    for item in find_all(node, "continuationCommand", limit=1):
        if isinstance(item, dict):
            token = item.get("token")
            if isinstance(token, str) and token:
                return token
    for item in find_all(node, "nextContinuationData", limit=1):
        if isinstance(item, dict):
            token = item.get("continuation")
            if isinstance(token, str) and token:
                return token
    for item in find_all(node, "continuationEndpoint", limit=1):
        if isinstance(item, dict):
            cmd = item.get("continuationCommand")
            if isinstance(cmd, dict):
                token = cmd.get("token")
                if isinstance(token, str) and token:
                    return token
    return None
