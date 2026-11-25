"""Tests for all InnerTube and timedtext parsers."""

import pytest

from yt_api_wrapper import MembersOnlyError, UnavailableError, format_duration, parse_count, parse_duration
from yt_api_wrapper.parsers.comments import parse_comments
from yt_api_wrapper.parsers.common import find_all, read_continuation, read_text, read_thumbnails
from yt_api_wrapper.parsers.community import parse_community_posts, parse_live_chat_messages
from yt_api_wrapper.parsers.renderers import parse_list_items
from yt_api_wrapper.parsers.video import (
    assert_playable,
    parse_caption_tracks,
    parse_streams,
    parse_transcript_xml,
    parse_video_details,
)


def test_common_helpers() -> None:
    assert read_text({"simpleText": "hello"}) == "hello"
    assert read_text({"runs": [{"text": "a"}, {"text": "b"}]}) == "ab"
    assert read_text({"content": {"simpleText": "nested"}}) == "nested"
    assert read_text(None) is None

    assert parse_count("1,234,567 views") == 1234567
    assert parse_count("1.2M subscribers") == 1200000
    assert parse_count("2.3万 回視聴") == 23000
    assert parse_count("1.5億") == 150000000
    assert parse_count("no digits") is None

    assert parse_duration("1:02:03") == 3723
    assert parse_duration("4:05") == 245
    assert parse_duration("45") == 45
    assert parse_duration("LIVE") is None

    assert format_duration(3723) == "1:02:03"
    assert format_duration(245) == "4:05"
    assert format_duration(5) == "0:05"

    thumbs = read_thumbnails(
        {
            "thumbnails": [
                {"url": "//i.ytimg.com/b.jpg", "width": 320, "height": 180},
                {"url": "https://i.ytimg.com/a.jpg", "width": 120, "height": 90},
            ]
        }
    )
    assert [t.width for t in thumbs] == [120, 320]
    assert thumbs[1].url == "https://i.ytimg.com/b.jpg"

    tree = {"a": [{"k": 1}, {"nested": {"k": 2}}]}
    assert find_all(tree, "k") == [1, 2]
    assert read_continuation({"x": {"continuationCommand": {"token": "TOK123"}}}) == "TOK123"


def test_assert_playable_and_members_only() -> None:
    assert_playable({"playabilityStatus": {"status": "OK"}}, "dQw4w9WgXcQ")

    with pytest.raises(UnavailableError) as exc_info:
        assert_playable(
            {"playabilityStatus": {"status": "ERROR", "reason": "Video unavailable"}},
            "dQw4w9WgXcQ",
        )
    assert exc_info.value.reason == "ERROR"

    with pytest.raises(MembersOnlyError) as mem_info:
        assert_playable(
            {
                "playabilityStatus": {
                    "status": "UNPLAYABLE",
                    "reason": "Join this channel to get access to members-only content at level Gold Crew or higher.",
                }
            },
            "dQw4w9WgXcQ",
        )
    assert mem_info.value.required_tier == "Gold Crew"

    with pytest.raises(MembersOnlyError) as mem_ja:
        assert_playable(
            {
                "playabilityStatus": {
                    "status": "UNPLAYABLE",
                    "reason": "この動画はレベル プレミアム 以上のメンバー限定です。",
                }
            },
            "dQw4w9WgXcQ",
        )
    assert mem_ja.value.required_tier == "プレミアム"


def test_parse_video_details_and_streams() -> None:
    player = {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {
            "videoId": "dQw4w9WgXcQ",
            "title": "Test Video",
            "lengthSeconds": "212",
            "viewCount": "1500000",
            "author": "Test Channel",
            "channelId": "UC1234567890123456789012",
            "shortDescription": "short desc",
            "keywords": ["music", "pop"],
            "isLiveContent": False,
        },
        "microformat": {
            "playerMicroformatRenderer": {
                "publishDate": "2024-05-01",
                "category": "Music",
                "isFamilySafe": True,
            }
        },
        "captions": {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [
                    {
                        "languageCode": "en",
                        "name": {"simpleText": "English"},
                        "baseUrl": "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ",
                        "isTranslatable": True,
                    }
                ]
            }
        },
        "streamingData": {
            "expiresInSeconds": "21540",
            "formats": [
                {
                    "itag": 18,
                    "url": "https://example.com/prog.mp4",
                    "mimeType": 'video/mp4; codecs="avc1.42001E, mp4a.40.2"',
                    "width": 640,
                    "height": 360,
                    "audioQuality": "AUDIO_QUALITY_LOW",
                    "qualityLabel": "360p",
                }
            ],
            "adaptiveFormats": [
                {
                    "itag": 137,
                    "url": "https://example.com/1080p.mp4",
                    "mimeType": 'video/mp4; codecs="avc1.640028"',
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                    "qualityLabel": "1080p",
                },
                {
                    "itag": 251,
                    "url": "https://example.com/audio.webm",
                    "mimeType": 'audio/webm; codecs="opus"',
                    "bitrate": 160000,
                    "audioQuality": "AUDIO_QUALITY_MEDIUM",
                    "audioChannels": 2,
                },
            ],
        },
    }
    next_resp = {
        "videoPrimaryInfoRenderer": {
            "title": {"runs": [{"text": "Test Video"}]},
        },
        "videoSecondaryInfoRenderer": {
            "attributedDescription": {"content": "Full description here"},
        },
        "likeButtonViewModel": {
            "toggleButtonViewModel": {
                "toggleButtonViewModel": {
                    "defaultButtonViewModel": {
                        "buttonViewModel": {
                            "accessibilityText": "like this video along with 42,000 other people"
                        }
                    }
                }
            }
        },
        "chapters": [
            {"chapterRenderer": {"title": {"simpleText": "Intro"}, "timeRangeStartMillis": "0"}},
            {"chapterRenderer": {"title": {"simpleText": "Chorus"}, "timeRangeStartMillis": "45000"}},
        ],
    }

    details = parse_video_details(player, next_resp, "dQw4w9WgXcQ")
    assert details.title == "Test Video"
    assert details.duration_seconds == 212
    assert details.view_count == 1500000
    assert details.like_count == 42000
    assert details.description == "Full description here"
    assert details.publish_date == "2024-05-01"
    assert len(details.chapters) == 2
    assert details.chapters[1].start_seconds == 45
    assert len(details.available_captions) == 1

    tracks = parse_caption_tracks(player)
    assert tracks[0].language_code == "en"

    bundle = parse_streams(player, "dQw4w9WgXcQ")
    assert bundle.expires_in_seconds == 21540
    assert len(bundle.progressive) == 1
    assert bundle.progressive[0].kind == "video+audio"
    assert len(bundle.adaptive) == 2
    assert bundle.adaptive[0].kind == "video"
    assert bundle.adaptive[1].kind == "audio"


def test_parse_transcript_xml() -> None:
    modern = '<transcript><p t="1500" d="2500">Hello &amp;amp; <s>world</s></p></transcript>'
    segs = parse_transcript_xml(modern)
    assert len(segs) == 1
    assert segs[0].text == "Hello & world"
    assert segs[0].start_seconds == 1.5
    assert segs[0].duration_seconds == 2.5

    legacy = '<transcript><text start="1.25" dur="3.0">It&#39;s fine</text></transcript>'
    segs2 = parse_transcript_xml(legacy)
    assert len(segs2) == 1
    assert segs2[0].text == "It's fine"
    assert segs2[0].start_seconds == 1.25


def test_parse_list_items_and_comments_and_community() -> None:
    items = [
        {
            "videoRenderer": {
                "videoId": "dQw4w9WgXcQ",
                "title": {"runs": [{"text": "Rick"}]},
                "lengthText": {"simpleText": "3:33"},
                "viewCountText": {"simpleText": "1.5B views"},
            }
        },
        {
            "channelRenderer": {
                "channelId": "UC1234567890123456789012",
                "title": {"simpleText": "My Channel"},
                "subscriberCountText": {"simpleText": "@mychan"},
                "videoCountText": {"simpleText": "1.2M subscribers"},
            }
        },
        {
            "lockupViewModel": {
                "contentId": "PLabcdef",
                "contentType": "LOCKUP_CONTENT_TYPE_PLAYLIST",
                "metadata": {
                    "lockupMetadataViewModel": {"title": {"content": "My Playlist"}}
                },
            }
        },
    ]
    parsed = parse_list_items(items)
    assert [p.type for p in parsed] == ["video", "channel", "playlist"]
    assert parsed[0].duration_seconds == 213
    assert parsed[1].handle == "@mychan"
    assert parsed[1].subscriber_count == 1200000

    # View-model comment
    comment_resp = {
        "threads": [
            {
                "commentThreadRenderer": {
                    "commentViewModel": {"commentViewModel": {"commentKey": "KEY1"}},
                    "replies": {
                        "commentRepliesRenderer": {
                            "contents": [
                                {
                                    "continuationItemRenderer": {
                                        "continuationEndpoint": {
                                            "continuationCommand": {"token": "REPLY_TOK"}
                                        }
                                    }
                                }
                            ]
                        }
                    },
                }
            }
        ],
        "mutations": [
            {
                "entityKey": "KEY1",
                "payload": {
                    "commentEntityPayload": {
                        "properties": {
                            "commentId": "C1",
                            "content": {"content": "Nice video!"},
                            "publishedTime": "2 days ago",
                        },
                        "author": {
                            "channelId": "UC1234567890123456789012",
                            "displayName": "@alice",
                            "isVerified": True,
                            "isCreator": False,
                        },
                        "toolbar": {
                            "likeCountNotliked": "1.2K",
                            "replyCount": "5",
                            "heartState": "TOOLBAR_HEART_STATE_HEARTED",
                        },
                    }
                },
            }
        ],
    }
    comments = parse_comments(comment_resp)
    assert len(comments) == 1
    assert comments[0].text == "Nice video!"
    assert comments[0].like_count == 1200
    assert comments[0].is_hearted is True
    assert comments[0].replies_token == "REPLY_TOK"

    # Community posts
    post_resp = {
        "items": [
            {
                "backstagePostRenderer": {
                    "postId": "P1",
                    "contentText": {"runs": [{"text": "Poll time!"}]},
                    "authorText": {"runs": [{"text": "Creator"}]},
                    "backstageAttachment": {
                        "pollRenderer": {
                            "choices": [
                                {"text": {"runs": [{"text": "Option A"}]}},
                                {"text": {"runs": [{"text": "Option B"}]}},
                            ]
                        }
                    },
                }
            }
        ]
    }
    posts = parse_community_posts(post_resp)
    assert len(posts) == 1
    assert posts[0].poll_choices == ["Option A", "Option B"]

    # Live chat
    chat_resp = {
        "actions": [
            {
                "addChatItemAction": {
                    "item": {
                        "liveChatPaidMessageRenderer": {
                            "id": "M1",
                            "timestampUsec": "1700000000000000",
                            "authorName": {"simpleText": "Fan"},
                            "authorExternalChannelId": "UC1234567890123456789012",
                            "purchaseAmountText": {"simpleText": "¥500"},
                            "message": {
                                "runs": [
                                    {"text": "Great stream "},
                                    {
                                        "emoji": {
                                            "emojiId": "UC123/sticker1",
                                            "shortcuts": [":_nice:"],
                                            "isCustomEmoji": True,
                                        }
                                    },
                                ]
                            },
                            "authorBadges": [
                                {
                                    "liveChatAuthorBadgeRenderer": {
                                        "tooltip": "メンバー（2 年）",
                                        "customThumbnail": {
                                            "thumbnails": [{"url": "https://img/b.png", "width": 16, "height": 16}]
                                        },
                                    }
                                }
                            ],
                        }
                    }
                }
            }
        ]
    }
    msgs = parse_live_chat_messages(chat_resp)
    assert len(msgs) == 1
    assert msgs[0].text == "Great stream :_nice:"
    assert msgs[0].purchase_amount == "¥500"
    assert msgs[0].is_member is True
    assert msgs[0].member_months == 24
    assert msgs[0].emojis[0].is_custom is True
