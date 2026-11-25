"""Parsers for list renderers (videos, channels, playlists, lockups)."""

from __future__ import annotations

import re
from typing import Any

from ..models import ChannelCompact, ChannelRef, PlaylistCompact, SearchResult, VideoCompact
from ..utils import channel_url, playlist_url, video_url
from .common import (
    find_all,
    has_verified_badge,
    parse_count,
    parse_duration,
    read_canonical_url,
    read_channel_id,
    read_channel_ref,
    read_text,
    read_text_or,
    read_thumbnails,
)

_VIDEO_RENDERERS = (
    "videoRenderer",
    "compactVideoRenderer",
    "gridVideoRenderer",
    "playlistVideoRenderer",
    "playlistPanelVideoRenderer",
    "reelItemRenderer",
)

_DIGIT_RE = re.compile(r"\d")


def parse_list_item(item: Any) -> SearchResult | None:
    """Turn one search/list item wrapper into a typed result, or ``None`` if unknown."""
    if not isinstance(item, dict):
        return None

    for key in _VIDEO_RENDERERS:
        if item.get(key):
            return parse_video_renderer(item[key])

    channel = item.get("channelRenderer") or item.get("gridChannelRenderer")
    if channel:
        return parse_channel_renderer(channel)

    playlist = (
        item.get("playlistRenderer")
        or item.get("gridPlaylistRenderer")
        or item.get("compactPlaylistRenderer")
    )
    if playlist:
        return parse_playlist_renderer(playlist)

    if item.get("lockupViewModel"):
        return _parse_lockup(item["lockupViewModel"])

    return None


def parse_list_items(items: Any) -> list[SearchResult]:
    """Expand shelves/sections and parse every item inside them."""
    if not isinstance(items, list):
        return []

    results: list[SearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        shelf_content = (item.get("shelfRenderer") or {}).get("content") or {}
        shelf_items = (
            (shelf_content.get("verticalListRenderer") or {}).get("items")
            or (shelf_content.get("horizontalListRenderer") or {}).get("items")
            or (item.get("reelShelfRenderer") or {}).get("items")
            or (
                ((item.get("richSectionRenderer") or {}).get("content") or {}).get(
                    "richShelfRenderer"
                )
                or {}
            ).get("contents")
        )

        if isinstance(shelf_items, list):
            results.extend(parse_list_items(shelf_items))
            continue

        rich_content = (item.get("richItemRenderer") or {}).get("content")
        if rich_content is not None:
            parsed = parse_list_item(rich_content)
            if parsed is not None:
                results.append(parsed)
            continue

        parsed = parse_list_item(item)
        if parsed is not None:
            results.append(parsed)

    return results


def parse_video_renderer(renderer: Any) -> VideoCompact | None:
    """Parse any of the video renderer variants into a :class:`VideoCompact`."""
    if not isinstance(renderer, dict):
        return None
    video_id = renderer.get("videoId")
    if not isinstance(video_id, str):
        return None

    badges = [
        (b.get("metadataBadgeRenderer") or {}).get("style", "")
        for b in (renderer.get("badges") or [])
        if isinstance(b, dict)
    ]
    overlays = renderer.get("thumbnailOverlays") or []
    is_live = any("LIVE" in style for style in badges if isinstance(style, str)) or any(
        isinstance(o, dict)
        and (o.get("thumbnailOverlayTimeStatusRenderer") or {}).get("style") == "LIVE"
        for o in overlays
    )
    is_upcoming = renderer.get("upcomingEventData") is not None

    overlay_duration = None
    for overlay in overlays:
        if isinstance(overlay, dict) and overlay.get("thumbnailOverlayTimeStatusRenderer"):
            overlay_duration = read_text(
                overlay["thumbnailOverlayTimeStatusRenderer"].get("text")
            )
            break

    duration_text = read_text(renderer.get("lengthText")) or overlay_duration

    view_count_text = (
        read_text(renderer.get("viewCountText"))
        or read_text(renderer.get("shortViewCountText"))
        or read_text(renderer.get("videoInfo"))
    )

    owner_node = (
        renderer.get("ownerText")
        or renderer.get("longBylineText")
        or renderer.get("shortBylineText")
        or (renderer.get("videoOwnerRenderer") or {}).get("title")
    )
    channel_name = read_text(owner_node)
    owner_runs = owner_node.get("runs") if isinstance(owner_node, dict) else None
    thumb_renderer = (renderer.get("channelThumbnailSupportedRenderers") or {}).get(
        "channelThumbnailWithLinkRenderer"
    ) or {}
    channel_id = (
        read_channel_id(owner_runs[0] if isinstance(owner_runs, list) and owner_runs else None)
        or ((thumb_renderer.get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get(
            "browseId"
        )
        or None
    )

    channel = (
        ChannelRef(
            id=channel_id,
            name=channel_name,
            url=channel_url(channel_id) if channel_id else None,
            thumbnails=read_thumbnails(
                thumb_renderer.get("thumbnail") or renderer.get("channelThumbnail")
            ),
            verified=has_verified_badge(renderer.get("ownerBadges")),
        )
        if channel_name
        else None
    )

    snippets = renderer.get("detailedMetadataSnippets")
    first_snippet = (
        snippets[0].get("snippetText")
        if isinstance(snippets, list) and snippets and isinstance(snippets[0], dict)
        else None
    )
    description = read_text(first_snippet) or read_text(renderer.get("descriptionSnippet"))

    return VideoCompact(
        id=video_id,
        title=read_text_or(renderer.get("title"), "(untitled)"),
        url=video_url(video_id),
        thumbnails=read_thumbnails(renderer.get("thumbnail")),
        duration_seconds=None if is_live else parse_duration(duration_text),
        duration_text=duration_text,
        view_count=parse_count(view_count_text),
        view_count_text=view_count_text,
        published_text=read_text(renderer.get("publishedTimeText")),
        channel=channel,
        description=description,
        is_live=is_live,
        is_upcoming=is_upcoming,
    )


def parse_channel_renderer(renderer: Any) -> ChannelCompact | None:
    """Parse a ``channelRenderer`` into a :class:`ChannelCompact`."""
    if not isinstance(renderer, dict):
        return None
    channel_id = renderer.get("channelId")
    if not isinstance(channel_id, str):
        return None

    sub_raw = read_text(renderer.get("subscriberCountText"))
    video_count_text = read_text(renderer.get("videoCountText"))
    subscriber_text = sub_raw or video_count_text
    handle = sub_raw if isinstance(sub_raw, str) and sub_raw.startswith("@") else None

    effective_sub_text = video_count_text if handle else subscriber_text

    return ChannelCompact(
        id=channel_id,
        name=read_text_or(renderer.get("title"), "(unnamed)"),
        url=read_canonical_url(renderer) or channel_url(channel_id),
        handle=handle,
        thumbnails=read_thumbnails(renderer.get("thumbnail")),
        subscriber_count=parse_count(effective_sub_text),
        subscriber_count_text=effective_sub_text,
        video_count_text=video_count_text,
        description=read_text(renderer.get("descriptionSnippet")),
        verified=has_verified_badge(renderer.get("ownerBadges")),
    )


def parse_playlist_renderer(renderer: Any) -> PlaylistCompact | None:
    """Parse any playlist renderer variant into a :class:`PlaylistCompact`."""
    if not isinstance(renderer, dict):
        return None
    playlist_id = renderer.get("playlistId")
    if not isinstance(playlist_id, str):
        return None

    count_text = (
        read_text(renderer.get("videoCountText"))
        or read_text(renderer.get("videoCountShortText"))
        or read_text(renderer.get("thumbnailText"))
    )
    owner_node = renderer.get("longBylineText") or renderer.get("shortBylineText")
    channel_name = read_text(owner_node)
    owner_runs = owner_node.get("runs") if isinstance(owner_node, dict) else None
    channel_id = read_channel_id(
        owner_runs[0] if isinstance(owner_runs, list) and owner_runs else None
    )

    thumbs_list = renderer.get("thumbnails")
    thumb_source = (
        thumbs_list[0]
        if isinstance(thumbs_list, list) and thumbs_list
        else renderer.get("thumbnail") or renderer.get("thumbnailRenderer")
    )

    channel = (
        ChannelRef(
            id=channel_id,
            name=channel_name,
            url=channel_url(channel_id) if channel_id else None,
            thumbnails=[],
            verified=has_verified_badge(renderer.get("ownerBadges")),
        )
        if channel_name
        else None
    )

    return PlaylistCompact(
        id=playlist_id,
        title=read_text_or(renderer.get("title"), "(untitled)"),
        url=playlist_url(playlist_id),
        thumbnails=read_thumbnails(thumb_source),
        video_count=parse_count(count_text),
        channel=channel,
    )


def _parse_lockup(lockup: Any) -> SearchResult | None:
    if not isinstance(lockup, dict):
        return None
    content_id = lockup.get("contentId")
    if not isinstance(content_id, str):
        return None

    meta = (lockup.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = read_text(meta.get("title")) or "(untitled)"

    content_image = lockup.get("contentImage") or {}
    thumb_image = (content_image.get("thumbnailViewModel") or {}).get("image") or (
        (
            (content_image.get("collectionThumbnailViewModel") or {}).get("primaryThumbnail")
            or {}
        ).get("thumbnailViewModel")
        or {}
    ).get("image")
    thumbnails = read_thumbnails(thumb_image)

    content_type = lockup.get("contentType")
    if content_type in ("LOCKUP_CONTENT_TYPE_PLAYLIST", "LOCKUP_CONTENT_TYPE_PODCAST"):
        overlay_text = None
        for badge_group in find_all(content_image, "thumbnailOverlayBadgeViewModel"):
            if not isinstance(badge_group, dict):
                continue
            for badge in badge_group.get("thumbnailBadges") or []:
                if not isinstance(badge, dict):
                    continue
                text = (badge.get("thumbnailBadgeViewModel") or {}).get("text")
                if isinstance(text, str) and _DIGIT_RE.search(text):
                    overlay_text = text
                    break
            if overlay_text is not None:
                break

        return PlaylistCompact(
            id=content_id,
            title=title,
            url=playlist_url(content_id),
            thumbnails=thumbnails,
            video_count=parse_count(overlay_text),
            channel=read_channel_ref(meta.get("metadata")),
        )

    return VideoCompact(
        id=content_id,
        title=title,
        url=video_url(content_id),
        thumbnails=thumbnails,
    )
