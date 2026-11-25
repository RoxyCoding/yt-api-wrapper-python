"""Tests for YouTube client methods and CLI using a mocked transport."""

import json

from yt_api_wrapper import HttpResponse, YouTube
from yt_api_wrapper.cli import run as cli_run


def _make_mock_transport():
    def transport(url, method, headers, data, timeout):
        if url == "https://www.youtube.com/":
            return HttpResponse(status=200, body=b'"visitorData":"V1"', headers={})

        if "suggestqueries-clients6.youtube.com" in url:
            body = 'window.google.ac.h(["py",[["python",0],["pytest",0]]])'
            return HttpResponse(status=200, body=body.encode("utf-8"), headers={})

        if "/oembed?" in url:
            body = json.dumps(
                {
                    "title": "Never Gonna Give You Up",
                    "author_name": "Rick Astley",
                    "author_url": "https://www.youtube.com/@RickAstleyYT",
                    "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                    "width": 200,
                    "height": 113,
                }
            )
            return HttpResponse(status=200, body=body.encode("utf-8"), headers={})

        if "/youtubei/v1/player?" in url:
            body = json.dumps(
                {
                    "playabilityStatus": {"status": "OK"},
                    "videoDetails": {
                        "videoId": "dQw4w9WgXcQ",
                        "title": "Never Gonna Give You Up",
                        "lengthSeconds": "213",
                        "viewCount": "1500000000",
                        "author": "Rick Astley",
                        "channelId": "UCuAXFkgsw1L7xaCfnd5JJOw",
                    },
                    "streamingData": {
                        "expiresInSeconds": "21540",
                        "formats": [
                            {
                                "itag": 18,
                                "url": "https://example.com/v.mp4",
                                "mimeType": 'video/mp4; codecs="avc1.42001E, mp4a.40.2"',
                                "width": 640,
                                "height": 360,
                                "audioQuality": "AUDIO_QUALITY_LOW",
                                "qualityLabel": "360p",
                            }
                        ],
                    },
                }
            )
            return HttpResponse(status=200, body=body.encode("utf-8"), headers={})

        if "/youtubei/v1/next?" in url:
            body = json.dumps(
                {
                    "videoPrimaryInfoRenderer": {
                        "title": {"runs": [{"text": "Never Gonna Give You Up"}]}
                    }
                }
            )
            return HttpResponse(status=200, body=body.encode("utf-8"), headers={})

        if "/youtubei/v1/search?" in url:
            body = json.dumps(
                {
                    "contents": {
                        "twoColumnSearchResultsRenderer": {
                            "primaryContents": {
                                "sectionListRenderer": {
                                    "contents": [
                                        {
                                            "itemSectionRenderer": {
                                                "contents": [
                                                    {
                                                        "videoRenderer": {
                                                            "videoId": "dQw4w9WgXcQ",
                                                            "title": {"runs": [{"text": "Lofi Mix"}]},
                                                            "lengthText": {"simpleText": "10:00"},
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }
            )
            return HttpResponse(status=200, body=body.encode("utf-8"), headers={})

        if "/youtubei/v1/navigation/resolve_url?" in url:
            body = json.dumps(
                {"endpoint": {"browseEndpoint": {"browseId": "UCX6OQ3DkcsbYNE6H8uQQuVA"}}}
            )
            return HttpResponse(status=200, body=body.encode("utf-8"), headers={})

        if "/youtubei/v1/browse?" in url:
            body = json.dumps(
                {
                    "metadata": {
                        "channelMetadataRenderer": {
                            "externalId": "UCX6OQ3DkcsbYNE6H8uQQuVA",
                            "title": "MrBeast",
                            "channelUrl": "https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA",
                            "vanityChannelUrl": "http://www.youtube.com/@MrBeast",
                        }
                    },
                    "c4TabbedHeaderRenderer": {
                        "subscriberCountText": {"simpleText": "300M subscribers"}
                    },
                }
            )
            return HttpResponse(status=200, body=body.encode("utf-8"), headers={})

        return HttpResponse(status=404, body=b"{}", headers={})

    return transport


def test_youtube_client_end_to_end_mocked() -> None:
    yt = YouTube(region="JP", language="ja", retries=0, transport=_make_mock_transport())

    video = yt.get_video("https://youtu.be/dQw4w9WgXcQ", with_streams=True)
    assert video.title == "Never Gonna Give You Up"
    assert video.duration_seconds == 213
    assert video.streams is not None and len(video.streams) == 1

    results = yt.search_videos("lofi", limit=5)
    assert len(results) == 1
    assert results[0].title == "Lofi Mix"

    suggestions = yt.get_suggestions("py")
    assert suggestions == ["python", "pytest"]

    oembed = yt.get_oembed("dQw4w9WgXcQ")
    assert oembed.author_name == "Rick Astley"

    channel = yt.get_channel("@MrBeast")
    assert channel.name == "MrBeast"
    assert channel.handle == "@MrBeast"
    assert channel.subscriber_count == 300_000_000


def test_cli_commands(capsys) -> None:
    yt = YouTube(retries=0, transport=_make_mock_transport())

    assert cli_run(["help"], yt_client=yt) == 0
    assert "yt-api" in capsys.readouterr().out

    assert cli_run(["video", "dQw4w9WgXcQ"], yt_client=yt) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "dQw4w9WgXcQ"
    assert out["title"] == "Never Gonna Give You Up"

    assert cli_run(["suggest", "py"], yt_client=yt) == 0
    assert json.loads(capsys.readouterr().out) == ["python", "pytest"]

    assert cli_run(["unknown-cmd"], yt_client=yt) == 1
    assert "unknown command" in capsys.readouterr().err
