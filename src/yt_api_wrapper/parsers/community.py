"""Parsers for community posts and live chat messages."""

from __future__ import annotations

import re
from typing import Any

from ..models import (
    ChannelRef,
    ChatEmoji,
    CommunityPost,
    LiveChatMessage,
    PlaylistCompact,
    VideoCompact,
)
from ..utils import channel_url
from .common import find_all, read_text, read_thumbnails, safe_int
from .renderers import parse_playlist_renderer, parse_video_renderer

_DIGITS_RE = re.compile(r"(\d+)")
_YEAR_RE = re.compile(r"年|year", re.IGNORECASE)


def parse_community_posts(response: Any) -> list[CommunityPost]:
    """Parse every community post in a browse response."""
    posts: list[CommunityPost] = []
    renderers = [
        *find_all(response, "backstagePostRenderer"),
        *find_all(response, "postRenderer"),
    ]
    seen: set[str] = set()

    for renderer in renderers:
        if not isinstance(renderer, dict):
            continue
        post_id = renderer.get("postId")
        if not isinstance(post_id, str):
            continue
        if post_id in seen:
            continue
        seen.add(post_id)

        author_id = (
            (renderer.get("authorEndpoint") or {}).get("browseEndpoint") or {}
        ).get("browseId")
        attachment = renderer.get("backstageAttachment") or {}

        reply_btn_text = (
            (
                ((renderer.get("actionButtons") or {}).get("commentActionButtonsRenderer") or {})
                .get("replyButton")
                or {}
            ).get("buttonRenderer")
            or {}
        ).get("text")

        multi_images = (attachment.get("postMultiImageRenderer") or {}).get("images")
        first_multi_img = (
            (multi_images[0].get("backstageImageRenderer") or {}).get("image")
            if isinstance(multi_images, list)
            and multi_images
            and isinstance(multi_images[0], dict)
            else None
        )
        image_node = (attachment.get("backstageImageRenderer") or {}).get(
            "image"
        ) or first_multi_img

        poll_choices = [
            text
            for choice in ((attachment.get("pollRenderer") or {}).get("choices") or [])
            if isinstance(choice, dict)
            and isinstance((text := read_text(choice.get("text"))), str)
        ]

        posts.append(
            CommunityPost(
                id=post_id,
                text=read_text(renderer.get("contentText")) or "",
                author=ChannelRef(
                    id=author_id,
                    name=read_text(renderer.get("authorText")) or "(unknown)",
                    url=channel_url(author_id) if author_id else None,
                    thumbnails=read_thumbnails(renderer.get("authorThumbnail")),
                    verified=False,
                ),
                published_text=read_text(renderer.get("publishedTimeText")),
                like_count_text=read_text(renderer.get("voteCount")),
                reply_count_text=read_text(reply_btn_text),
                images=read_thumbnails(image_node),
                attachment=_parse_attachment(attachment),
                poll_choices=poll_choices,
            )
        )

    return posts


def _parse_attachment(attachment: Any) -> VideoCompact | PlaylistCompact | None:
    if not isinstance(attachment, dict):
        return None
    if attachment.get("videoRenderer"):
        return parse_video_renderer(attachment["videoRenderer"])
    if attachment.get("playlistRenderer"):
        return parse_playlist_renderer(attachment["playlistRenderer"])
    return None


def _read_chat_text(node: Any) -> str | None:
    if node is None:
        return None
    if not isinstance(node, dict) or not isinstance(node.get("runs"), list):
        return read_text(node)

    parts: list[str] = []
    for run in node["runs"]:
        if not isinstance(run, dict):
            continue
        if isinstance(run.get("text"), str):
            parts.append(run["text"])
            continue
        emoji = run.get("emoji")
        if isinstance(emoji, dict):
            shortcuts = emoji.get("shortcuts")
            if isinstance(shortcuts, list) and shortcuts and isinstance(shortcuts[0], str):
                parts.append(shortcuts[0])
            elif isinstance(emoji.get("emojiId"), str):
                parts.append(emoji["emojiId"])

    joined = "".join(parts)
    return joined if joined else None


def _read_chat_emojis(node: Any) -> list[ChatEmoji]:
    if not isinstance(node, dict) or not isinstance(node.get("runs"), list):
        return []

    emojis: list[ChatEmoji] = []
    for run in node["runs"]:
        if not isinstance(run, dict):
            continue
        emoji = run.get("emoji")
        if not isinstance(emoji, dict):
            continue
        emoji_id = emoji.get("emojiId") if isinstance(emoji.get("emojiId"), str) else ""
        shortcuts = emoji.get("shortcuts")
        shortcut = (
            shortcuts[0]
            if isinstance(shortcuts, list) and shortcuts and isinstance(shortcuts[0], str)
            else emoji_id
        )
        emojis.append(
            ChatEmoji(
                shortcut=shortcut,
                id=emoji_id,
                is_custom=emoji.get("isCustomEmoji") is True or "/" in emoji_id,
                thumbnails=read_thumbnails(emoji.get("image")),
            )
        )
    return emojis


def _parse_member_months(badge: str | None) -> int | None:
    if not badge:
        return None
    match = _DIGITS_RE.search(badge)
    if not match:
        return None
    value = int(match.group(1), 10)
    return value * 12 if _YEAR_RE.search(badge) else value


def parse_live_chat_messages(response: Any) -> list[LiveChatMessage]:
    """Parse a ``live_chat/get_live_chat`` response into :class:`LiveChatMessage` entries."""
    messages: list[LiveChatMessage] = []

    for action in find_all(response, "addChatItemAction"):
        if not isinstance(action, dict):
            continue
        item = action.get("item") or {}
        if not isinstance(item, dict):
            continue

        renderer = (
            item.get("liveChatTextMessageRenderer")
            or item.get("liveChatPaidMessageRenderer")
            or item.get("liveChatPaidStickerRenderer")
            or item.get("liveChatMembershipItemRenderer")
        )
        if not isinstance(renderer, dict) or not renderer.get("id"):
            continue

        author_id = renderer.get("authorExternalChannelId") or None
        badge_renderers = [
            badge["liveChatAuthorBadgeRenderer"]
            for badge in (renderer.get("authorBadges") or [])
            if isinstance(badge, dict) and isinstance(badge.get("liveChatAuthorBadgeRenderer"), dict)
        ]

        icon_types = [
            icon_type
            for b in badge_renderers
            if isinstance((icon_type := (b.get("icon") or {}).get("iconType")), str) and icon_type
        ]
        member_badge_renderer = next(
            (
                b
                for b in badge_renderers
                if b.get("customThumbnail") and not (b.get("icon") or {}).get("iconType")
            ),
            None,
        )
        member_badge = None
        if member_badge_renderer is not None:
            member_badge = (
                member_badge_renderer.get("tooltip")
                or ((member_badge_renderer.get("accessibility") or {}).get("accessibilityData") or {})
                .get("label")
            )

        messages.append(
            LiveChatMessage(
                id=str(renderer["id"]),
                text=(
                    _read_chat_text(renderer.get("message"))
                    or _read_chat_text(renderer.get("headerSubtext"))
                    or read_text(renderer.get("purchaseAmountText"))
                    or ""
                ),
                author=ChannelRef(
                    id=author_id,
                    name=read_text(renderer.get("authorName")) or "(unknown)",
                    url=channel_url(author_id) if author_id else None,
                    thumbnails=read_thumbnails(renderer.get("authorPhoto")),
                    verified="VERIFIED" in icon_types,
                ),
                timestamp_usec=safe_int(renderer.get("timestampUsec")) or 0,
                purchase_amount=read_text(renderer.get("purchaseAmountText")),
                is_moderator="MODERATOR" in icon_types,
                is_owner="OWNER" in icon_types,
                is_member=(
                    member_badge is not None
                    or item.get("liveChatMembershipItemRenderer") is not None
                ),
                member_badge=member_badge,
                member_months=_parse_member_months(member_badge),
                member_badge_thumbnails=read_thumbnails(
                    member_badge_renderer.get("customThumbnail") if member_badge_renderer else None
                ),
                emojis=_read_chat_emojis(renderer.get("message")),
            )
        )

    return messages
