"""Parsers for YouTube comments (classic commentRenderer and view-model shapes)."""

from __future__ import annotations

from typing import Any

from ..models import ChannelRef, Comment, Thumbnail
from ..utils import channel_url
from .common import find_all, parse_count, read_text, read_thumbnails, safe_int


def parse_comments(response: Any) -> list[Comment]:
    """Parse every comment in a ``next`` / continuation response."""
    comments: list[Comment] = []

    for thread in find_all(response, "commentThreadRenderer"):
        if not isinstance(thread, dict):
            continue
        classic = (thread.get("comment") or {}).get("commentRenderer")
        if isinstance(classic, dict) and classic.get("commentId"):
            parsed = _parse_comment_renderer(classic, thread)
        else:
            parsed = _parse_comment_view_model(thread, response)
        if parsed is not None:
            comments.append(parsed)

    # Reply continuations arrive without a thread wrapper, in either shape.
    if not comments:
        for renderer in find_all(response, "commentRenderer"):
            parsed = _parse_comment_renderer(renderer, None)
            if parsed is not None:
                comments.append(parsed)
        for view in find_all(response, "commentViewModel"):
            if not isinstance(view, dict) or not isinstance(view.get("commentKey"), str):
                continue
            parsed = _parse_comment_view_model({"commentViewModel": view}, response)
            if parsed is not None:
                comments.append(parsed)

    return comments


def _extract_reply_token(thread: dict[str, Any] | None) -> str | None:
    if not isinstance(thread, dict):
        return None
    contents = ((thread.get("replies") or {}).get("commentRepliesRenderer") or {}).get("contents")
    if not isinstance(contents, list) or not contents:
        return None
    first = contents[0]
    if not isinstance(first, dict):
        return None
    token = (
        ((first.get("continuationItemRenderer") or {}).get("continuationEndpoint") or {})
        .get("continuationCommand", {})
        .get("token")
    )
    return token if isinstance(token, str) and token else None


def _parse_comment_renderer(renderer: Any, thread: dict[str, Any] | None) -> Comment | None:
    if not isinstance(renderer, dict):
        return None
    comment_id = renderer.get("commentId")
    if not isinstance(comment_id, str):
        return None

    author_id = (
        (renderer.get("authorEndpoint") or {}).get("browseEndpoint") or {}
    ).get("browseId")
    reply_token = _extract_reply_token(thread)

    badge_tooltip = (
        (renderer.get("authorCommentBadge") or {}).get("authorCommentBadgeRenderer") or {}
    ).get("iconTooltip", "")
    verified = isinstance(badge_tooltip, str) and "verified" in badge_tooltip.lower()

    reply_count_val = safe_int(renderer.get("replyCount"))
    reply_count = reply_count_val if reply_count_val is not None else (None if reply_token else 0)

    is_hearted = (
        (renderer.get("actionButtons") or {}).get("commentActionButtonsRenderer") or {}
    ).get("creatorHeart") is not None

    return Comment(
        id=comment_id,
        text=read_text(renderer.get("contentText")) or "",
        author=ChannelRef(
            id=author_id,
            name=read_text(renderer.get("authorText")) or "(unknown)",
            url=channel_url(author_id) if author_id else None,
            thumbnails=read_thumbnails(renderer.get("authorThumbnail")),
            verified=verified,
        ),
        like_count=parse_count(read_text(renderer.get("voteCount"))),
        published_text=read_text(renderer.get("publishedTimeText")),
        reply_count=reply_count,
        is_pinned=renderer.get("pinnedCommentBadge") is not None,
        is_hearted=is_hearted,
        is_author_channel_owner=renderer.get("authorIsChannelOwner") is True,
        replies_token=reply_token,
    )


def _parse_comment_view_model(thread: dict[str, Any], response: Any) -> Comment | None:
    raw_vm = thread.get("commentViewModel")
    view = (
        raw_vm.get("commentViewModel")
        if isinstance(raw_vm, dict) and isinstance(raw_vm.get("commentViewModel"), dict)
        else raw_vm
    )
    if not isinstance(view, dict):
        return None
    key = view.get("commentKey")
    if not isinstance(key, str):
        return None

    entity = None
    for mutation_list in find_all(response, "mutations"):
        if not isinstance(mutation_list, list):
            continue
        for mutation in mutation_list:
            if isinstance(mutation, dict) and mutation.get("entityKey") == key:
                entity = (mutation.get("payload") or {}).get("commentEntityPayload")
                break
        if entity is not None:
            break

    if not isinstance(entity, dict):
        return None

    author = entity.get("author") or {}
    props = entity.get("properties") or {}
    toolbar = entity.get("toolbar") or {}

    author_id = author.get("channelId") or None
    avatar_url = author.get("avatarThumbnailUrl")
    thumbnails = (
        [Thumbnail(url=avatar_url, width=88, height=88)]
        if isinstance(avatar_url, str) and avatar_url
        else []
    )

    content = props.get("content")
    text = content.get("content", "") if isinstance(content, dict) else ""

    return Comment(
        id=props.get("commentId") or key,
        text=text if isinstance(text, str) else "",
        author=ChannelRef(
            id=author_id,
            name=author.get("displayName") or "(unknown)",
            url=channel_url(author_id) if author_id else None,
            thumbnails=thumbnails,
            verified=author.get("isVerified") is True,
        ),
        like_count=parse_count(toolbar.get("likeCountLiked") or toolbar.get("likeCountNotliked")),
        published_text=props.get("publishedTime") or None,
        reply_count=parse_count(toolbar.get("replyCount")),
        is_pinned=props.get("pinnedText") is not None,
        is_hearted=toolbar.get("heartState") == "TOOLBAR_HEART_STATE_HEARTED",
        is_author_channel_owner=author.get("isCreator") is True,
        replies_token=_extract_reply_token(thread),
    )
