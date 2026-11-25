"""Data models returned by yt-api-wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar, Union

T = TypeVar("T")


@dataclass
class Thumbnail:
    """A single image (thumbnail, avatar, banner) as returned by YouTube."""

    url: str
    width: int
    height: int


@dataclass
class ChannelRef:
    """Minimal channel reference embedded in videos, playlists and comments."""

    id: str | None
    name: str
    url: str | None
    thumbnails: list[Thumbnail] = field(default_factory=list)
    verified: bool = False


@dataclass
class VideoCompact:
    """A video as it appears in a list (search results, related, playlist, channel)."""

    id: str
    title: str
    url: str
    thumbnails: list[Thumbnail] = field(default_factory=list)
    duration_seconds: int | None = None
    duration_text: str | None = None
    view_count: int | None = None
    view_count_text: str | None = None
    published_text: str | None = None
    channel: ChannelRef | None = None
    description: str | None = None
    is_live: bool = False
    is_upcoming: bool = False
    type: Literal["video"] = "video"


@dataclass
class Chapter:
    """A chapter marker parsed out of the video description / macro markers."""

    title: str
    start_seconds: int
    thumbnails: list[Thumbnail] = field(default_factory=list)


@dataclass
class StreamFormat:
    """A downloadable / playable stream variant."""

    itag: int
    url: str | None
    mime_type: str
    kind: Literal["video", "audio", "video+audio"]
    codecs: str
    bitrate: int | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    quality_label: str | None = None
    audio_quality: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    content_length: int | None = None
    duration_ms: int | None = None
    requires_cipher: bool = False
    is_adaptive: bool = False


@dataclass
class StreamBundle:
    """Everything needed to play a video, including manifest URLs."""

    video_id: str
    formats: list[StreamFormat] = field(default_factory=list)
    progressive: list[StreamFormat] = field(default_factory=list)
    adaptive: list[StreamFormat] = field(default_factory=list)
    hls_manifest_url: str | None = None
    dash_manifest_url: str | None = None
    expires_in_seconds: int | None = None


@dataclass
class CaptionTrack:
    """A caption/subtitle track available for a video."""

    language_code: str
    language_name: str
    url: str
    is_auto_generated: bool = False
    is_translatable: bool = False


@dataclass
class TranscriptSegment:
    """One cue of a fetched transcript."""

    text: str
    start_seconds: float
    duration_seconds: float


@dataclass
class VideoDetails:
    """Full metadata for a single video."""

    id: str
    title: str
    url: str
    thumbnails: list[Thumbnail] = field(default_factory=list)
    duration_seconds: int | None = None
    duration_text: str | None = None
    view_count: int | None = None
    view_count_text: str | None = None
    channel: ChannelRef | None = None
    description: str = ""
    publish_date: str | None = None
    upload_date: str | None = None
    keywords: list[str] = field(default_factory=list)
    category: str | None = None
    like_count: int | None = None
    live_viewers: int | None = None
    is_family_safe: bool | None = None
    is_private: bool = False
    is_unlisted: bool = False
    allow_ratings: bool = True
    available_captions: list[CaptionTrack] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    is_live: bool = False
    is_upcoming: bool = False
    streams: list[StreamFormat] | None = None
    type: Literal["video"] = "video"


@dataclass
class ChannelLink:
    """External link shown on a channel's about page."""

    title: str
    url: str


@dataclass
class ChannelCompact:
    """A channel as it appears in a list."""

    id: str
    name: str
    url: str
    handle: str | None = None
    thumbnails: list[Thumbnail] = field(default_factory=list)
    subscriber_count: int | None = None
    subscriber_count_text: str | None = None
    video_count_text: str | None = None
    description: str | None = None
    verified: bool = False
    type: Literal["channel"] = "channel"


@dataclass
class ChannelDetails(ChannelCompact):
    """Full channel metadata."""

    banners: list[Thumbnail] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    links: list[ChannelLink] = field(default_factory=list)
    country: str | None = None
    joined_date: str | None = None
    view_count: int | None = None
    is_family_safe: bool | None = None
    tabs: list[str] = field(default_factory=list)
    has_memberships: bool = False


@dataclass
class PlaylistCompact:
    """A playlist as it appears in a list."""

    id: str
    title: str
    url: str
    thumbnails: list[Thumbnail] = field(default_factory=list)
    video_count: int | None = None
    channel: ChannelRef | None = None
    type: Literal["playlist"] = "playlist"


@dataclass
class PlaylistDetails(PlaylistCompact):
    """Full playlist metadata with its items."""

    description: str | None = None
    view_count: int | None = None
    last_updated_text: str | None = None
    videos: list[VideoCompact] = field(default_factory=list)


@dataclass
class Comment:
    """A top-level comment or a reply."""

    id: str
    text: str
    author: ChannelRef
    like_count: int | None = None
    published_text: str | None = None
    reply_count: int | None = None
    is_pinned: bool = False
    is_hearted: bool = False
    is_author_channel_owner: bool = False
    replies_token: str | None = None


SearchResult = Union[VideoCompact, ChannelCompact, PlaylistCompact]

SearchType = Literal["video", "channel", "playlist", "movie", "all"]
UploadDateFilter = Literal["hour", "today", "week", "month", "year"]
DurationFilter = Literal["short", "medium", "long"]
SortByFilter = Literal["relevance", "date", "views", "rating"]
FeatureFilter = Literal[
    "live", "hd", "4k", "subtitles", "creativeCommons", "360", "hdr", "vr180"
]


@dataclass
class Page(Generic[T]):
    """A lazily paginated list of results."""

    items: list[T] = field(default_factory=list)
    continuation: str | None = None


@dataclass
class CommunityPost:
    """A community (posts tab) entry."""

    id: str
    text: str
    author: ChannelRef
    published_text: str | None = None
    like_count_text: str | None = None
    reply_count_text: str | None = None
    images: list[Thumbnail] = field(default_factory=list)
    attachment: VideoCompact | PlaylistCompact | None = None
    poll_choices: list[str] = field(default_factory=list)


@dataclass
class ChatEmoji:
    """A standard emoji or a channel's custom sticker used in a chat message."""

    shortcut: str
    id: str
    is_custom: bool = False
    thumbnails: list[Thumbnail] = field(default_factory=list)


@dataclass
class LiveChatMessage:
    """One message from a live chat stream."""

    id: str
    text: str
    author: ChannelRef
    timestamp_usec: int = 0
    purchase_amount: str | None = None
    is_moderator: bool = False
    is_member: bool = False
    is_owner: bool = False
    member_badge: str | None = None
    member_months: int | None = None
    member_badge_thumbnails: list[Thumbnail] = field(default_factory=list)
    emojis: list[ChatEmoji] = field(default_factory=list)


@dataclass
class OEmbed:
    """Lightweight oEmbed metadata for a video."""

    title: str
    author_name: str
    author_url: str
    thumbnail_url: str
    width: int
    height: int
