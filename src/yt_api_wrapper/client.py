"""High-level unofficial YouTube client."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal, Sequence
from urllib.parse import quote

from .clients.innertube import InnerTube, extract_initial_data
from .errors import InvalidArgumentError, ParseError, UnavailableError
from .http import DEFAULT_RETRIES, DEFAULT_TIMEOUT, HttpClient, Transport
from .models import (
    CaptionTrack,
    ChannelDetails,
    ChannelLink,
    ChannelRef,
    Comment,
    CommunityPost,
    DurationFilter,
    FeatureFilter,
    LiveChatMessage,
    OEmbed,
    Page,
    PlaylistCompact,
    PlaylistDetails,
    SearchResult,
    SearchType,
    SortByFilter,
    StreamBundle,
    TranscriptSegment,
    UploadDateFilter,
    VideoCompact,
    VideoDetails,
)
from .parsers.comments import parse_comments
from .parsers.common import (
    find_all,
    find_first,
    parse_count,
    read_continuation,
    read_text,
    read_thumbnails,
    safe_int,
)
from .parsers.community import parse_community_posts, parse_live_chat_messages
from .parsers.filters import encode_search_filters
from .parsers.renderers import parse_list_items
from .parsers.video import (
    assert_playable,
    parse_caption_tracks,
    parse_streams,
    parse_transcript_xml,
    parse_video_details,
)
from .utils import (
    channel_url,
    parse_channel_input,
    parse_playlist_id,
    parse_video_id,
    playlist_url,
)

# Exact base64 protobuf `params` values youtube.com sends for each channel tab.
_CHANNEL_TAB_PARAMS: dict[str, str] = {
    "videos": "EgZ2aWRlb3PyBgQKAjoA",
    "shorts": "EgZzaG9ydHPyBgUKA5oBAA==",
    "streams": "EgdzdHJlYW1z8gYECgJ6AA==",
    "playlists": "EglwbGF5bGlzdHPyBgQKAkIA",
    "community": "Egljb21tdW5pdHnyBgQKAkoA",
}

# Client identities tried for `player`, in order of usefulness.
_PLAYER_CLIENTS: tuple[str, ...] = (
    "VISIONOS",
    "ANDROID",
    "IOS",
    "TV_EMBEDDED",
    "WEB",
)

_HANDLE_RE = re.compile(r"@[\w.-]+")
_CHANNEL_URL_RE = re.compile(r"/channel/(UC[\w-]+)")
_EXTERNAL_ID_RE = re.compile(r'"externalId":"(UC[\w-]{22})"')
_CANONICAL_CHANNEL_RE = re.compile(
    r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"'
)
_OG_CHANNEL_RE = re.compile(
    r'<meta property="og:url" content="https://www\.youtube\.com/channel/(UC[\w-]{22})"'
)
_LIVE_CHAT_TOKEN_RE = re.compile(r'"continuation":"([^"]{30,})"')


class YouTube:
    """Unofficial YouTube client.

    Every method works without an API key by talking to InnerTube, the private
    JSON API that youtube.com and the mobile apps use.

    Example::

        yt = YouTube(region="JP", language="ja")
        video = yt.get_video("dQw4w9WgXcQ")
    """

    def __init__(
        self,
        *,
        region: str = "US",
        language: str = "en",
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        cookie: str | None = None,
        headers: dict[str, str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._http = HttpClient(
            timeout=timeout,
            retries=retries,
            headers=headers,
            transport=transport,
        )
        self._innertube = InnerTube(
            http=self._http,
            region=region,
            language=language,
            cookie=cookie,
        )

    # ---------------------------------------------------------------- videos

    def get_video(self, input_str: str, *, with_streams: bool = False) -> VideoDetails:
        """Fetch full metadata for a video by id or URL."""
        video_id = parse_video_id(input_str)

        def _fetch_next() -> Any:
            try:
                return self._innertube.call("next", {"videoId": video_id})
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            player_fut = pool.submit(self._fetch_player, video_id)
            next_fut = pool.submit(_fetch_next)
            player = player_fut.result()
            next_resp = next_fut.result()

        assert_playable(player, video_id)
        details = parse_video_details(player, next_resp, video_id)

        if with_streams:
            details.streams = self.get_streams(video_id).formats
        return details

    def _fetch_player(self, video_id: str) -> Any:
        payload = {"videoId": video_id, "contentCheckOk": True, "racyCheckOk": True}
        last_player: Any = None

        for client_name in _PLAYER_CLIENTS:
            try:
                player = self._innertube.with_client(client_name).call("player", payload)
            except Exception:
                continue
            if not player:
                continue
            last_player = player
            status = (player.get("playabilityStatus") or {}).get("status")
            if status in ("OK", "LIVE_STREAM_OFFLINE"):
                return player

        if last_player is not None:
            return last_player
        raise UnavailableError(f"no client could load video {video_id}")

    def get_streams(self, input_str: str) -> StreamBundle:
        """Resolve playable / downloadable stream URLs."""
        video_id = parse_video_id(input_str)
        player = self._fetch_player(video_id)
        assert_playable(player, video_id)

        bundle = parse_streams(player, video_id)
        if not bundle.formats and not bundle.hls_manifest_url and not bundle.dash_manifest_url:
            raise UnavailableError(f"no playable streams found for {video_id}")
        return bundle

    def get_related(self, input_str: str, *, limit: int = 20) -> list[VideoCompact]:
        """Videos YouTube suggests alongside a given video."""
        video_id = parse_video_id(input_str)
        response = self._innertube.call("next", {"videoId": video_id})

        sec = find_first(response, "secondaryResults")
        container = (
            sec.get("secondaryResults")
            if isinstance(sec, dict) and isinstance(sec.get("secondaryResults"), dict)
            else (sec if isinstance(sec, dict) else response)
        )

        results: list[VideoCompact] = []
        items: list[Any] = (container.get("results") if isinstance(container, dict) else None) or []
        continuation = read_continuation(items)

        while len(results) < limit:
            for item in parse_list_items(items):
                if isinstance(item, VideoCompact):
                    results.append(item)
            if len(results) >= limit or not continuation:
                break

            response = self._innertube.continue_("next", continuation)
            items = _flatten(find_all(response, "continuationItems"))
            continuation = read_continuation(items)
            if not items:
                break

        return results[:limit]

    # ---------------------------------------------------------------- search

    def search(
        self,
        query: str,
        *,
        type: SearchType | None = None,
        upload_date: UploadDateFilter | None = None,
        duration: DurationFilter | None = None,
        sort_by: SortByFilter | None = None,
        features: Sequence[FeatureFilter] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Search YouTube. Returns videos, channels and playlists unless filtered."""
        if not query.strip():
            raise InvalidArgumentError("search query must not be empty")

        params = encode_search_filters(
            type=type,
            upload_date=upload_date,
            duration=duration,
            sort_by=sort_by,
            features=features,
        )
        payload: dict[str, Any] = {"query": query}
        if params:
            payload["params"] = params

        response = self._innertube.call("search", payload)
        results: list[SearchResult] = []
        items = _collect_search_items(response)
        continuation = read_continuation(response)

        while len(results) < limit:
            results.extend(parse_list_items(items))
            if len(results) >= limit or not continuation:
                break

            response = self._innertube.continue_("search", continuation)
            items = _flatten(find_all(response, "continuationItems"))
            continuation = read_continuation(response)
            if not items:
                break

        return results[:limit]

    def search_videos(
        self,
        query: str,
        *,
        upload_date: UploadDateFilter | None = None,
        duration: DurationFilter | None = None,
        sort_by: SortByFilter | None = None,
        features: Sequence[FeatureFilter] | None = None,
        limit: int = 20,
    ) -> list[VideoCompact]:
        """Search restricted to videos."""
        results = self.search(
            query,
            type="video",
            upload_date=upload_date,
            duration=duration,
            sort_by=sort_by,
            features=features,
            limit=limit,
        )
        return [item for item in results if isinstance(item, VideoCompact)]

    def get_suggestions(self, query: str) -> list[str]:
        """YouTube's autocomplete suggestions for a partial query."""
        url = (
            "https://suggestqueries-clients6.youtube.com/complete/search"
            f"?client=youtube&ds=yt&oe=utf-8&q={quote(query)}"
            f"&hl={self._innertube.language}&gl={self._innertube.region}"
        )
        body = self._http.text(url)
        start = body.find("(")
        end = body.rfind(")")
        if start == -1 or end == -1 or end <= start:
            raise ParseError("failed to parse suggestion response")
        raw_json = body[start + 1 : end]

        try:
            parsed = json.loads(raw_json)
            entries = parsed[1] if isinstance(parsed, list) and len(parsed) > 1 else []
            return [
                entry[0]
                for entry in entries
                if isinstance(entry, list) and entry and isinstance(entry[0], str)
            ]
        except Exception as err:
            raise ParseError("failed to parse suggestion response", cause=err) from err

    # --------------------------------------------------------------- channel

    def get_channel(self, input_str: str) -> ChannelDetails:
        """Fetch channel metadata by id, @handle, vanity name or URL."""
        channel_id = self.resolve_channel_id(input_str)
        response = self._innertube.call("browse", {"browseId": channel_id})

        has_memberships = "sponsorships-button" in json.dumps(response)

        metadata = (response.get("metadata") or {}).get("channelMetadataRenderer") or {}
        header = (
            find_first(response, "c4TabbedHeaderRenderer")
            or find_first(response, "pageHeaderRenderer")
            or {}
        )
        micro = (response.get("microformat") or {}).get("microformatDataRenderer") or {}

        meta_vm = find_first(header, "contentMetadataViewModel") or {}
        meta_rows = meta_vm.get("metadataRows")
        alt_sub_node = None
        if isinstance(meta_rows, list) and len(meta_rows) > 1 and isinstance(meta_rows[1], dict):
            parts = meta_rows[1].get("metadataParts")
            if isinstance(parts, list) and parts and isinstance(parts[0], dict):
                alt_sub_node = parts[0].get("text")

        subscriber_text = read_text(header.get("subscriberCountText")) or read_text(alt_sub_node)

        vanity = metadata.get("vanityChannelUrl")
        handle_match = _HANDLE_RE.search(vanity) if isinstance(vanity, str) else None

        keywords_str = metadata.get("keywords")
        keywords = keywords_str.split() if isinstance(keywords_str, str) else []

        links: list[ChannelLink] = []
        for links_vm in find_all(response, "channelHeaderLinksViewModel"):
            if not isinstance(links_vm, dict):
                continue
            candidates = []
            if links_vm.get("firstLink"):
                candidates.append(links_vm["firstLink"])
            if links_vm.get("more"):
                candidates.append(links_vm["more"])
            for link in candidates:
                if not isinstance(link, dict):
                    continue
                cmd_runs = link.get("commandRuns")
                link_url = ""
                if isinstance(cmd_runs, list) and cmd_runs and isinstance(cmd_runs[0], dict):
                    link_url = (
                        ((cmd_runs[0].get("onTap") or {}).get("innertubeCommand") or {})
                        .get("urlEndpoint", {})
                        .get("url", "")
                    )
                if link_url:
                    links.append(ChannelLink(title=read_text(link) or "", url=link_url))

        joined_nodes = find_all(response, "joinedDateText")
        view_nodes = find_all(response, "viewCountText")

        tabs_raw = (
            (response.get("contents") or {})
            .get("twoColumnBrowseResultsRenderer", {})
            .get("tabs")
            or []
        )
        tabs = [
            title
            for tab in tabs_raw
            if isinstance(tab, dict)
            and isinstance((title := (tab.get("tabRenderer") or {}).get("title")), str)
        ]

        verified = any(
            isinstance(badge, dict)
            and "VERIFIED" in str((badge.get("metadataBadgeRenderer") or {}).get("style", ""))
            for badge in (header.get("badges") or [])
        )

        family_safe = micro.get("familySafe")
        is_family_safe = family_safe if isinstance(family_safe, bool) else None

        return ChannelDetails(
            id=metadata.get("externalId") or channel_id,
            name=metadata.get("title") or read_text(header.get("title")) or "(unnamed)",
            url=metadata.get("channelUrl") or channel_url(channel_id),
            handle=handle_match.group(0) if handle_match else None,
            thumbnails=read_thumbnails(metadata.get("avatar") or header.get("avatar")),
            banners=read_thumbnails(header.get("banner")),
            subscriber_count=parse_count(subscriber_text),
            subscriber_count_text=subscriber_text,
            video_count_text=read_text(header.get("videosCountText")),
            description=metadata.get("description") or micro.get("description") or None,
            keywords=keywords,
            links=links,
            country=read_text(find_first(response, "country")),
            joined_date=read_text(joined_nodes[0]) if joined_nodes else None,
            view_count=parse_count(read_text(view_nodes[0])) if view_nodes else None,
            is_family_safe=is_family_safe,
            has_memberships=has_memberships,
            tabs=tabs,
            verified=verified,
        )

    def get_channel_videos(self, input_str: str, *, limit: int = 50) -> list[VideoCompact]:
        """Uploads from a channel, newest first."""
        return self._browse_channel_tab(input_str, "videos", limit=limit)

    def get_channel_shorts(self, input_str: str, *, limit: int = 50) -> list[VideoCompact]:
        """Shorts posted by a channel."""
        return self._browse_channel_tab(input_str, "shorts", limit=limit)

    def get_channel_streams(self, input_str: str, *, limit: int = 50) -> list[VideoCompact]:
        """Live streams (past and current) from a channel."""
        return self._browse_channel_tab(input_str, "streams", limit=limit)

    def resolve_channel_id(self, input_str: str) -> str:
        """Resolve any channel reference to a ``UC...`` id."""
        parsed = parse_channel_input(input_str)
        if parsed.kind == "id":
            return parsed.value

        path = f"/@{parsed.value}" if parsed.kind == "handle" else f"/c/{parsed.value}"
        response = self._innertube.call(
            "navigation/resolve_url", {"url": f"https://www.youtube.com{path}"}
        )

        endpoint = response.get("endpoint") or {}
        browse_id = (endpoint.get("browseEndpoint") or {}).get("browseId")
        if not isinstance(browse_id, str):
            web_url = (
                (endpoint.get("commandMetadata") or {})
                .get("webCommandMetadata", {})
                .get("url", "")
            )
            if isinstance(web_url, str):
                match = _CHANNEL_URL_RE.search(web_url)
                if match:
                    browse_id = match.group(1)

        if isinstance(browse_id, str) and browse_id.startswith("UC"):
            return browse_id

        redirect = (endpoint.get("urlEndpoint") or {}).get("url") or (
            (endpoint.get("commandMetadata") or {}).get("webCommandMetadata", {}).get("url")
        )
        target = redirect if isinstance(redirect, str) and "youtube.com" in redirect else path
        html = self._innertube.page(target)

        for pattern in (_EXTERNAL_ID_RE, _CANONICAL_CHANNEL_RE, _OG_CHANNEL_RE):
            match = pattern.search(html)
            if match:
                return match.group(1)

        raise UnavailableError(f"could not resolve channel: {input_str}")

    def get_channel_playlists(self, input_str: str, *, limit: int = 50) -> list[PlaylistCompact]:
        """Channel playlists tab."""
        channel_id = self.resolve_channel_id(input_str)
        response = self._innertube.call(
            "browse",
            {"browseId": channel_id, "params": _CHANNEL_TAB_PARAMS["playlists"]},
        )
        items = _collect_tab_items(response)
        continuation = read_continuation(response)

        playlists: list[PlaylistCompact] = []
        while len(playlists) < limit:
            for item in parse_list_items(items):
                if isinstance(item, PlaylistCompact):
                    playlists.append(item)
            if len(playlists) >= limit or not continuation:
                break

            response = self._innertube.continue_("browse", continuation)
            items = _flatten(find_all(response, "continuationItems"))
            continuation = read_continuation(response)
            if not items:
                break

        return playlists[:limit]

    def get_community_posts(self, input_str: str, *, limit: int = 30) -> list[CommunityPost]:
        """Community (posts) tab."""
        channel_id = self.resolve_channel_id(input_str)
        response = self._innertube.call(
            "browse",
            {"browseId": channel_id, "params": _CHANNEL_TAB_PARAMS["community"]},
        )

        posts: list[CommunityPost] = []
        continuation = read_continuation(response)

        while len(posts) < limit:
            posts.extend(parse_community_posts(response))
            if len(posts) >= limit or not continuation:
                break

            next_page = self._innertube.continue_("browse", continuation)
            if not parse_community_posts(next_page):
                break
            response = next_page
            continuation = read_continuation(response)

        return posts[:limit]

    # ------------------------------------------------------------- live chat

    def get_live_chat(
        self, input_str: str, continuation: str | None = None
    ) -> Page[LiveChatMessage]:
        """Read a batch of messages from a live stream's chat (live or replay)."""
        video_id = parse_video_id(input_str)
        if continuation:
            return self._read_live_chat_page(continuation)

        try:
            html = self._innertube.page(f"/live_chat?is_popout=1&v={video_id}")
        except Exception:
            html = None

        tokens = _LIVE_CHAT_TOKEN_RE.findall(html) if html else []
        if not tokens:
            raise UnavailableError(
                f"video {video_id} has no live chat (not a stream, or its replay is unavailable)"
            )

        best: Page[LiveChatMessage] | None = None
        seen_tokens: set[str] = set()
        for token in tokens:
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            try:
                page = self._read_live_chat_page(token)
            except Exception:
                continue
            if best is None or len(page.items) > len(best.items):
                best = page

        if best is not None:
            return best
        raise UnavailableError(f"video {video_id} has no readable live chat")

    def _read_live_chat_page(self, continuation: str) -> Page[LiveChatMessage]:
        response: Any = None
        for endpoint in ("live_chat/get_live_chat_replay", "live_chat/get_live_chat"):
            try:
                response = self._innertube.call(endpoint, {"continuation": continuation})
                if response:
                    break
            except Exception:
                continue
        if not response:
            raise UnavailableError("live chat continuation was rejected")

        live = (response.get("continuationContents") or {}).get("liveChatContinuation") or {}
        next_token = None
        for key in (
            "liveChatReplayContinuationData",
            "invalidationContinuationData",
            "timedContinuationData",
            "reloadContinuationData",
        ):
            found = find_all(live, key)
            if found and isinstance(found[0], dict) and found[0].get("continuation"):
                next_token = found[0]["continuation"]
                break

        return Page(items=parse_live_chat_messages(response), continuation=next_token)

    def _browse_channel_tab(
        self,
        input_str: str,
        tab: Literal["videos", "shorts", "streams"],
        *,
        limit: int = 50,
    ) -> list[VideoCompact]:
        channel_id = self.resolve_channel_id(input_str)
        response = self._innertube.call(
            "browse",
            {"browseId": channel_id, "params": _CHANNEL_TAB_PARAMS[tab]},
        )
        items = _collect_tab_items(response)
        continuation = read_continuation(response)

        videos: list[VideoCompact] = []
        while len(videos) < limit:
            for item in parse_list_items(items):
                if isinstance(item, VideoCompact):
                    videos.append(item)
            if len(videos) >= limit or not continuation:
                break

            response = self._innertube.continue_("browse", continuation)
            items = _flatten(find_all(response, "continuationItems"))
            continuation = read_continuation(response)
            if not items:
                break

        return videos[:limit]

    # -------------------------------------------------------------- playlist

    def get_playlist(self, input_str: str, *, limit: int = 100) -> PlaylistDetails:
        """Fetch a playlist and its videos."""
        playlist_id = parse_playlist_id(input_str)
        response = self._innertube.call("browse", {"browseId": f"VL{playlist_id}"})

        header = (
            find_first(response, "playlistHeaderRenderer")
            or find_first(response, "pageHeaderRenderer")
            or {}
        )
        sidebar = find_first(response, "playlistSidebarPrimaryInfoRenderer") or {}

        items = _collect_tab_items(response)
        continuation = read_continuation(response)
        videos: list[VideoCompact] = []

        while len(videos) < limit:
            for item in parse_list_items(items):
                if isinstance(item, VideoCompact):
                    videos.append(item)
            if len(videos) >= limit or not continuation:
                break

            response = self._innertube.continue_("browse", continuation)
            items = _flatten(find_all(response, "continuationItems"))
            continuation = read_continuation(response)
            if not items:
                break

        stats = sidebar.get("stats") if isinstance(sidebar.get("stats"), list) else []
        stat0 = stats[0] if len(stats) > 0 else None
        stat1 = stats[1] if len(stats) > 1 else None
        stat2 = stats[2] if len(stats) > 2 else None

        title = read_text(header.get("title")) or read_text(sidebar.get("title")) or "(untitled)"
        count_text = read_text(header.get("numVideosText")) or read_text(stat0)
        owner_renderer = find_first(response, "videoOwnerRenderer") or {}
        owner_id = (
            (owner_renderer.get("navigationEndpoint") or {}).get("browseEndpoint") or {}
        ).get("browseId")
        owner_name = read_text(header.get("ownerText")) or read_text(owner_renderer.get("title"))

        hero_thumb = (
            (header.get("playlistHeaderBanner") or {}).get("heroPlaylistThumbnailRenderer") or {}
        ).get("thumbnail")
        thumbs = read_thumbnails(hero_thumb)
        if videos:
            thumbs = (thumbs + videos[0].thumbnails)[:4]
        else:
            thumbs = thumbs[:4]

        channel = (
            ChannelRef(
                id=owner_id,
                name=owner_name,
                url=channel_url(owner_id) if owner_id else None,
                thumbnails=[],
                verified=False,
            )
            if owner_name
            else None
        )

        parsed_count = parse_count(count_text)
        return PlaylistDetails(
            id=playlist_id,
            title=title,
            url=playlist_url(playlist_id),
            thumbnails=thumbs,
            video_count=parsed_count if parsed_count is not None else len(videos),
            channel=channel,
            description=(
                read_text(header.get("descriptionText")) or read_text(sidebar.get("description"))
            ),
            view_count=parse_count(read_text(header.get("viewCountText")) or read_text(stat1)),
            last_updated_text=read_text(stat2),
            videos=videos[:limit],
        )

    # -------------------------------------------------------------- comments

    def get_comments(
        self,
        input_str: str,
        *,
        limit: int = 50,
        sort_by: Literal["top", "newest"] = "top",
    ) -> list[Comment]:
        """Fetch top-level comments for a video."""
        video_id = parse_video_id(input_str)
        next_resp = self._innertube.call("next", {"videoId": video_id})

        section = next(
            (
                s
                for s in find_all(next_resp, "itemSectionRenderer")
                if isinstance(s, dict) and s.get("sectionIdentifier") == "comment-item-section"
            ),
            None,
        )
        continuation = read_continuation(section) if section else None
        if not continuation:
            return []

        response = self._innertube.continue_("next", continuation)

        if sort_by == "newest":
            menus = find_all(response, "sortFilterSubMenuRenderer")
            sub_items = (menus[0].get("subMenuItems") if menus and isinstance(menus[0], dict) else None) or []
            sort_token = (
                ((sub_items[1].get("serviceEndpoint") or {}).get("continuationCommand") or {}).get("token")
                if len(sub_items) > 1 and isinstance(sub_items[1], dict)
                else None
            )
            if isinstance(sort_token, str) and sort_token:
                response = self._innertube.continue_("next", sort_token)

        comments: list[Comment] = []
        while len(comments) < limit:
            comments.extend(parse_comments(response))
            cont_items = find_all(response, "continuationItemRenderer")
            continuation = read_continuation(cont_items[-1]) if cont_items else None
            if len(comments) >= limit or not continuation:
                break

            next_page = self._innertube.continue_("next", continuation)
            if not parse_comments(next_page):
                break
            response = next_page

        return comments[:limit]

    def get_comment_replies(self, token: str, *, limit: int = 50) -> list[Comment]:
        """Fetch replies to a comment using its ``replies_token``."""
        if not token:
            raise InvalidArgumentError("a replies_token is required")

        replies: list[Comment] = []
        continuation: str | None = token

        while continuation and len(replies) < limit:
            response = self._innertube.continue_("next", continuation)
            page = parse_comments(response)
            if not page:
                break
            replies.extend(page)
            cont_items = find_all(response, "continuationItemRenderer")
            continuation = read_continuation(cont_items[-1]) if cont_items else None

        return replies[:limit]

    # -------------------------------------------------------------- captions

    def get_captions(self, input_str: str) -> list[CaptionTrack]:
        """List the caption tracks available for a video."""
        video_id = parse_video_id(input_str)
        player = self._fetch_player(video_id)
        assert_playable(player, video_id)
        return parse_caption_tracks(player)

    def get_transcript(
        self, input_str: str, language: str | None = None
    ) -> list[TranscriptSegment]:
        """Fetch a transcript. Picks ``language`` when available, otherwise the first
        manual track, otherwise the first auto-generated one.
        """
        tracks = self.get_captions(input_str)
        if not tracks:
            raise UnavailableError(f"no captions available for {parse_video_id(input_str)}")

        track = None
        if language:
            track = next((t for t in tracks if t.language_code == language), None)
        if track is None:
            track = next((t for t in tracks if not t.is_auto_generated), None)
        if track is None:
            track = tracks[0]

        xml = self._http.text(
            track.url,
            headers={"User-Agent": self._innertube.client.user_agent},
            timeout=5.0,
            retries=5,
        )
        segments = parse_transcript_xml(xml)
        if not segments:
            raise ParseError(f"transcript for {track.language_code} came back empty")
        return segments

    # -------------------------------------------------------------- trending

    def get_trending(
        self,
        category: Literal["now", "music", "gaming", "movies"] = "now",
        *,
        limit: int = 50,
    ) -> list[VideoCompact]:
        """Most-popular videos for a category from YouTube's official chart playlists."""
        region = self._innertube.region.upper()
        candidates: dict[str, list[str]] = {
            "now": ["PLrEnWoR732-BHrPp_Pm8_VleD68f9s14-", "PLFgquLnL59alW3xmYiWRaoz0oM3H17Lth"],
            "music": ["PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"],
            "gaming": ["PLFgquLnL59alF0GjxEs0V_XvpZWpAv1VP"],
            "movies": ["PLFgquLnL59amjZuAjZfHKlkNSTQVdPvOo"],
        }
        if category not in candidates:
            raise InvalidArgumentError(f"invalid trending category: {category}")

        last_error: BaseException | None = None
        for playlist_id in candidates[category]:
            try:
                playlist = self.get_playlist(playlist_id, limit=limit)
                if playlist.videos:
                    return playlist.videos[:limit]
            except Exception as err:
                last_error = err

        suffix = f": {last_error}" if last_error else ""
        raise UnavailableError(
            f"no trending chart available for {category} in region {region}{suffix}"
        )

    # ------------------------------------------------------------------ misc

    def get_oembed(self, input_str: str) -> OEmbed:
        """Resolve oEmbed metadata — the cheapest way to check a video exists."""
        video_id = parse_video_id(input_str)
        url = (
            "https://www.youtube.com/oembed?format=json"
            f"&url=https://www.youtube.com/watch?v={video_id}"
        )
        data = self._http.json(url)
        return OEmbed(
            title=data.get("title") or "",
            author_name=data.get("author_name") or "",
            author_url=data.get("author_url") or "",
            thumbnail_url=data.get("thumbnail_url") or "",
            width=safe_int(data.get("width")) or 0,
            height=safe_int(data.get("height")) or 0,
        )

    def get_raw_page_data(self, path: str, variable: str = "ytInitialData") -> Any:
        """Scrape a youtube.com page and return its ``ytInitialData`` blob."""
        html = self._innertube.page(path)
        return extract_initial_data(html, variable)

    def raw(self, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        """Call any InnerTube endpoint directly. Escape hatch for advanced use."""
        return self._innertube.call(endpoint, payload)


def _flatten(lists: list[Any]) -> list[Any]:
    out: list[Any] = []
    for entry in lists:
        if isinstance(entry, list):
            out.extend(entry)
        else:
            out.append(entry)
    return out


def _collect_search_items(response: Any) -> list[Any]:
    sections = (
        ((response.get("contents") or {}).get("twoColumnSearchResultsRenderer") or {})
        .get("primaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents")
    )
    if not isinstance(sections, list):
        found = find_all(response, "sectionListRenderer")
        sections = found[0].get("contents") if found and isinstance(found[0], dict) else []

    items: list[Any] = []
    for section in sections or []:
        if isinstance(section, dict):
            contents = (section.get("itemSectionRenderer") or {}).get("contents")
            if isinstance(contents, list):
                items.extend(contents)
    return items


def _collect_tab_items(response: Any) -> list[Any]:
    tabs = (
        (response.get("contents") or {})
        .get("twoColumnBrowseResultsRenderer", {})
        .get("tabs")
        or []
    )
    selected = next(
        (t for t in tabs if isinstance(t, dict) and (t.get("tabRenderer") or {}).get("selected")),
        tabs[0] if tabs else None,
    )
    content = (selected.get("tabRenderer") or {}).get("content") if isinstance(selected, dict) else None

    direct: list[Any] = []
    if isinstance(content, dict):
        rich_contents = (content.get("richGridRenderer") or {}).get("contents")
        if isinstance(rich_contents, list):
            direct = rich_contents
        else:
            sec_contents = (content.get("sectionListRenderer") or {}).get("contents") or []
            for section in sec_contents:
                if not isinstance(section, dict):
                    continue
                for inner in (section.get("itemSectionRenderer") or {}).get("contents") or []:
                    if not isinstance(inner, dict):
                        continue
                    extracted = (
                        (inner.get("playlistVideoListRenderer") or {}).get("contents")
                        or (inner.get("gridRenderer") or {}).get("items")
                        or (
                            ((inner.get("shelfRenderer") or {}).get("content") or {}).get(
                                "expandedShelfContentsRenderer"
                            )
                            or {}
                        ).get("items")
                    )
                    if isinstance(extracted, list):
                        direct.extend(extracted)
                    else:
                        direct.append(inner)

    if direct:
        return direct

    fallback = _flatten(find_all(response, "contents")) + _flatten(find_all(response, "items"))
    return [item for item in fallback if isinstance(item, dict)]
