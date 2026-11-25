"""Parsers for video details, streams, captions, chapters, and transcripts."""

from __future__ import annotations

import html as html_mod
import re
from datetime import datetime
from typing import Any, Literal

from ..errors import MembersOnlyError, UnavailableError
from ..models import (
    CaptionTrack,
    ChannelRef,
    Chapter,
    StreamBundle,
    StreamFormat,
    TranscriptSegment,
    VideoDetails,
)
from ..utils import channel_url, video_url
from .common import (
    find_all,
    find_first,
    has_verified_badge,
    parse_count,
    read_text,
    read_thumbnails,
    safe_int,
)

_FATAL_STATUSES = {"ERROR", "LOGIN_REQUIRED", "UNPLAYABLE", "AGE_VERIFICATION_REQUIRED"}
_MEMBERS_SUB_RE = re.compile(r"member|メンバー", re.IGNORECASE)
_MEMBERS_DETAIL_RE = re.compile(
    r"members[- ]only|member of this channel|メンバー(?:限定|が対象|になって)",
    re.IGNORECASE,
)
_TIER_JA_RE = re.compile(r"レベル\s*(.+?)\s*以上のメンバー")
_TIER_EN_RE = re.compile(r"level\s+(.+?)\s+or higher", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_PREFIX_RE = re.compile(
    r"^(?:Premiered|Streamed live on|Started streaming on)\s+", re.IGNORECASE
)
_CODECS_RE = re.compile(r'codecs="([^"]+)"')
_P_TAG_RE = re.compile(r'<p\s+t="(\d+)"(?:\s+d="(\d+)")?[^>]*>([\s\S]*?)</p>')
_TEXT_TAG_RE = re.compile(r'<text\s+start="([\d.]+)"(?:\s+dur="([\d.]+)")?[^>]*>([\s\S]*?)</text>')
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def assert_playable(player: Any, video_id: str) -> None:
    """Raise a descriptive error when the player response says the video is unusable."""
    status = player.get("playabilityStatus") if isinstance(player, dict) else None
    if not isinstance(status, dict):
        raise UnavailableError(f"no playability status for {video_id}")

    status_code = status.get("status")
    if status_code in _FATAL_STATUSES:
        err_screen = status.get("errorScreen")
        err_renderer = (
            err_screen.get("playerErrorMessageRenderer")
            if isinstance(err_screen, dict)
            else None
        )
        detail = (
            read_text(status.get("reason"))
            or read_text(err_renderer.get("reason") if isinstance(err_renderer, dict) else None)
            or str(status_code)
        )

        if _is_members_only(status, detail):
            raise MembersOnlyError(
                f"video {video_id} is members-only: {detail}",
                required_tier=_read_tier(detail),
            )

        raise UnavailableError(
            f"video {video_id} is unavailable: {detail}", reason=str(status_code)
        )


def _is_members_only(status: dict[str, Any], detail: str) -> bool:
    err_screen = status.get("errorScreen")
    if isinstance(err_screen, dict):
        renderer = err_screen.get("playerErrorMessageRenderer")
        if isinstance(renderer, dict) and renderer.get("subreason") is not None:
            sub = read_text(renderer["subreason"]) or ""
            if _MEMBERS_SUB_RE.search(sub):
                return True
    return bool(_MEMBERS_DETAIL_RE.search(detail))


def _read_tier(detail: str) -> str | None:
    match = _TIER_JA_RE.search(detail) or _TIER_EN_RE.search(detail)
    return match.group(1).strip() if match else None


def parse_video_details(player: Any, next_resp: Any, video_id: str) -> VideoDetails:
    """Merge ``player`` and ``next`` responses into one :class:`VideoDetails`."""
    details = (player.get("videoDetails") if isinstance(player, dict) else None) or {}
    micro = (
        (player.get("microformat") or {}).get("playerMicroformatRenderer")
        if isinstance(player, dict)
        else None
    ) or {}

    duration_raw = details.get("lengthSeconds") or micro.get("lengthSeconds")
    duration_seconds = safe_int(duration_raw)
    if duration_seconds is not None and duration_seconds <= 0:
        duration_seconds = None

    is_live = details.get("isLiveContent") is True and details.get("isLive") is not False

    primary_info = find_first(next_resp, "videoPrimaryInfoRenderer") or {}
    secondary_info = find_first(next_resp, "videoSecondaryInfoRenderer") or {}

    description = (
        read_text(secondary_info.get("attributedDescription"))
        or read_text(secondary_info.get("description"))
        or details.get("shortDescription")
        or ""
    )

    channel_id = details.get("channelId") or micro.get("externalChannelId") or None
    owner_renderer = find_first(secondary_info, "videoOwnerRenderer") or {}

    view_count_node = (
        (primary_info.get("viewCount") or {}).get("videoViewCountRenderer") or {}
    ).get("viewCount")
    view_count_text = read_text(view_count_node)
    view_count = parse_count(details.get("viewCount"))
    if view_count is None:
        view_count = parse_count(view_count_text)

    live_viewers_renderer = find_first(primary_info, "videoViewCountRenderer") or {}
    live_viewers = parse_count(read_text(live_viewers_renderer.get("viewCount")))

    keywords_raw = details.get("keywords")
    keywords = [k for k in keywords_raw if isinstance(k, str)] if isinstance(keywords_raw, list) else []

    is_family_safe = micro.get("isFamilySafe")
    if not isinstance(is_family_safe, bool):
        is_family_safe = None

    return VideoDetails(
        id=video_id,
        title=details.get("title") or read_text(primary_info.get("title")) or "(untitled)",
        url=video_url(video_id),
        thumbnails=read_thumbnails(details.get("thumbnail") or micro.get("thumbnail")),
        duration_seconds=duration_seconds,
        duration_text=None,
        view_count=view_count,
        view_count_text=view_count_text,
        channel=ChannelRef(
            id=channel_id,
            name=details.get("author") or micro.get("ownerChannelName") or "(unknown)",
            url=channel_url(channel_id) if channel_id else None,
            thumbnails=read_thumbnails(owner_renderer.get("thumbnail")),
            verified=has_verified_badge(owner_renderer.get("badges")),
        ),
        description=description,
        publish_date=micro.get("publishDate") or _parse_date_from_next(next_resp),
        upload_date=micro.get("uploadDate") or micro.get("publishDate") or None,
        keywords=keywords,
        category=micro.get("category") or None,
        like_count=_parse_like_count(next_resp),
        live_viewers=live_viewers,
        is_family_safe=is_family_safe,
        is_private=details.get("isPrivate") is True,
        is_unlisted=micro.get("isUnlisted") is True,
        allow_ratings=details.get("allowRatings") is not False,
        available_captions=parse_caption_tracks(player),
        chapters=parse_chapters(next_resp),
        is_live=is_live,
        is_upcoming=details.get("isUpcoming") is True,
    )


def _parse_date_from_next(next_resp: Any) -> str | None:
    if not next_resp:
        return None
    for row in find_all(next_resp, "factoid"):
        if isinstance(row, dict):
            value = read_text((row.get("factoidRenderer") or {}).get("value"))
            if value and _ISO_DATE_RE.match(value):
                return value

    date_text = read_text(find_first(next_resp, "dateText")) or read_text(
        find_first(next_resp, "relativeDateText")
    )
    if not date_text:
        return None

    cleaned = _DATE_PREFIX_RE.sub("", date_text).strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_like_count(next_resp: Any) -> int | None:
    if not next_resp:
        return None

    for button in find_all(next_resp, "toggleButtonRenderer"):
        if not isinstance(button, dict):
            continue
        label = (
            ((button.get("defaultText") or {}).get("accessibility") or {})
            .get("accessibilityData", {})
            .get("label")
            or (button.get("accessibilityData") or {})
            .get("accessibilityData", {})
            .get("label")
        )
        if isinstance(label, str) and "like" in label.lower():
            cleaned = re.sub(r"[^\d.,KMBkmb万億千]", " ", label)
            count = parse_count(cleaned)
            if count is not None:
                return count

    for view in find_all(next_resp, "likeButtonViewModel"):
        if not isinstance(view, dict):
            continue
        label = (
            (((view.get("toggleButtonViewModel") or {}).get("toggleButtonViewModel") or {})
             .get("defaultButtonViewModel") or {})
            .get("buttonViewModel", {})
            .get("accessibilityText")
        )
        if isinstance(label, str):
            count = parse_count(label)
            if count is not None:
                return count

    return None


def parse_chapters(next_resp: Any) -> list[Chapter]:
    """Extract chapter markers from the description-derived macro markers shelf."""
    if not next_resp:
        return []
    chapters: list[Chapter] = []
    for renderer in find_all(next_resp, "chapterRenderer"):
        if not isinstance(renderer, dict):
            continue
        start_ms = safe_int(renderer.get("timeRangeStartMillis"))
        if start_ms is None:
            continue
        chapters.append(
            Chapter(
                title=read_text(renderer.get("title")) or "(untitled chapter)",
                start_seconds=int(round(start_ms / 1000)),
                thumbnails=read_thumbnails(renderer.get("thumbnail")),
            )
        )
    chapters.sort(key=lambda c: c.start_seconds)
    return chapters


def parse_caption_tracks(player: Any) -> list[CaptionTrack]:
    """List the caption tracks advertised in the player response."""
    if not isinstance(player, dict):
        return []
    tracks = (
        (player.get("captions") or {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks")
    )
    if not isinstance(tracks, list):
        return []

    result: list[CaptionTrack] = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        base_url = track.get("baseUrl")
        if not isinstance(base_url, str):
            continue
        lang_code = track.get("languageCode") or ""
        result.append(
            CaptionTrack(
                language_code=lang_code,
                language_name=read_text(track.get("name")) or lang_code,
                url=base_url,
                is_auto_generated=track.get("kind") == "asr",
                is_translatable=track.get("isTranslatable") is True,
            )
        )
    return result


def parse_streams(player: Any, video_id: str) -> StreamBundle:
    """Turn the player's ``streamingData`` into a normalised :class:`StreamBundle`."""
    streaming = (player.get("streamingData") if isinstance(player, dict) else None) or {}
    progressive = [
        _parse_format(f, is_adaptive=False)
        for f in (streaming.get("formats") or [])
        if isinstance(f, dict)
    ]
    adaptive = [
        _parse_format(f, is_adaptive=True)
        for f in (streaming.get("adaptiveFormats") or [])
        if isinstance(f, dict)
    ]

    return StreamBundle(
        video_id=video_id,
        formats=[*progressive, *adaptive],
        progressive=progressive,
        adaptive=adaptive,
        hls_manifest_url=streaming.get("hlsManifestUrl") or None,
        dash_manifest_url=streaming.get("dashManifestUrl") or None,
        expires_in_seconds=safe_int(streaming.get("expiresInSeconds")),
    )


def _parse_format(fmt: dict[str, Any], *, is_adaptive: bool) -> StreamFormat:
    mime_type = fmt.get("mimeType") or ""
    codecs_match = _CODECS_RE.search(mime_type)
    codecs = codecs_match.group(1) if codecs_match else ""
    container = mime_type.split(";")[0] if mime_type else ""

    has_video = container.startswith("video") and fmt.get("width") is not None
    has_audio = container.startswith("audio") or fmt.get("audioQuality") is not None

    kind: Literal["video", "audio", "video+audio"]
    if container.startswith("audio"):
        kind = "audio"
    elif is_adaptive:
        kind = "video"
    elif has_video and has_audio:
        kind = "video+audio"
    elif has_video:
        kind = "video"
    else:
        kind = "audio"

    url = fmt.get("url") if isinstance(fmt.get("url"), str) else None
    requires_cipher = url is None and (
        fmt.get("signatureCipher") is not None or fmt.get("cipher") is not None
    )

    return StreamFormat(
        itag=safe_int(fmt.get("itag")) or 0,
        url=url,
        mime_type=container,
        kind=kind,
        codecs=codecs,
        bitrate=safe_int(fmt.get("bitrate")),
        width=safe_int(fmt.get("width")),
        height=safe_int(fmt.get("height")),
        fps=safe_int(fmt.get("fps")),
        quality_label=fmt.get("qualityLabel") or fmt.get("quality") or None,
        audio_quality=fmt.get("audioQuality") or None,
        audio_sample_rate=safe_int(fmt.get("audioSampleRate")),
        audio_channels=safe_int(fmt.get("audioChannels")),
        content_length=safe_int(fmt.get("contentLength")),
        duration_ms=safe_int(fmt.get("approxDurationMs")),
        requires_cipher=requires_cipher,
        is_adaptive=is_adaptive,
    )


def parse_transcript_xml(xml: str) -> list[TranscriptSegment]:
    """Parse a timedtext XML document into :class:`TranscriptSegment` entries."""
    segments: list[TranscriptSegment] = []

    # Current format="3": integer milliseconds in <p t="ms" d="ms">.
    for match in _P_TAG_RE.finditer(xml):
        text = _clean_cue_text(match.group(3))
        if not text:
            continue
        start_ms = int(match.group(1), 10)
        dur_ms = int(match.group(2), 10) if match.group(2) else 0
        segments.append(
            TranscriptSegment(
                text=text,
                start_seconds=start_ms / 1000.0,
                duration_seconds=dur_ms / 1000.0,
            )
        )
    if segments:
        return segments

    # Legacy format: fractional seconds in <text start="s" dur="s">.
    for match in _TEXT_TAG_RE.finditer(xml):
        text = _clean_cue_text(match.group(3))
        if not text:
            continue
        try:
            start_s = float(match.group(1))
        except ValueError:
            start_s = 0.0
        try:
            dur_s = float(match.group(2)) if match.group(2) else 0.0
        except ValueError:
            dur_s = 0.0
        segments.append(
            TranscriptSegment(
                text=text,
                start_seconds=start_s,
                duration_seconds=dur_s,
            )
        )

    return segments


def _clean_cue_text(raw: str) -> str:
    stripped = _HTML_TAG_RE.sub("", raw)
    decoded = _decode_xml_entities(stripped)
    return _WHITESPACE_RE.sub(" ", decoded).strip()


def _decode_xml_entities(text: str) -> str:
    """timedtext double-encodes entities, so decode until stable."""
    prev = text
    for _ in range(4):
        curr = html_mod.unescape(prev)
        if curr == prev:
            return curr
        prev = curr
    return prev
