"""Command-line interface for yt-api-wrapper."""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Any, Sequence

from .client import YouTube
from .errors import YouTubeError

USAGE = """yt-api — unofficial YouTube API wrapper

Usage:
  yt-api video <id|url> [--streams]
  yt-api search <query> [--type video|channel|playlist] [--limit N] [--sort date|views|rating]
  yt-api channel <id|@handle|url>
  yt-api channel-videos <id|@handle|url> [--limit N]
  yt-api playlist <id|url> [--limit N]
  yt-api comments <id|url> [--limit N] [--sort top|newest]
  yt-api transcript <id|url> [--lang ja]
  yt-api streams <id|url>
  yt-api trending [now|music|gaming|movies] [--limit N]
  yt-api suggest <query>
  yt-api related <id|url> [--limit N]

Global options:
  --region XX     ISO country code (default US)
  --language xx   UI language (default en)
  --json          Print raw JSON (default; kept for clarity)
"""


def _parse_args(argv: Sequence[str]) -> tuple[str, list[str], dict[str, str | bool]]:
    positional: list[str] = []
    flags: dict[str, str | bool] = {}

    i = 0
    while i < len(argv):
        arg = argv[i]
        if not arg.startswith("--"):
            positional.append(arg)
            i += 1
            continue
        name = arg[2:]
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            flags[name] = argv[i + 1]
            i += 2
        else:
            flags[name] = True
            i += 1

    command = positional.pop(0) if positional else ""
    return command, positional, flags


def _parse_int_flag(value: str | bool | None) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(value, 10)
    except ValueError:
        return None


def _to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def run(argv: Sequence[str], *, yt_client: YouTube | None = None) -> int:
    """Execute the CLI with ``argv`` and return a process exit code."""
    command, positional, flags = _parse_args(argv)

    if not command or command == "help" or flags.get("help"):
        sys.stdout.write(USAGE)
        return 0

    region = flags.get("region")
    language = flags.get("language")
    yt = yt_client or YouTube(
        region=region if isinstance(region, str) else "US",
        language=language if isinstance(language, str) else "en",
    )

    target = positional[0] if positional else None
    limit = _parse_int_flag(flags.get("limit"))

    def require_target() -> str:
        if not target:
            raise YouTubeError(f"{command} requires an argument — see 'yt-api help'")
        return target

    try:
        result: Any
        if command == "video":
            result = yt.get_video(require_target(), with_streams=flags.get("streams") is True)
        elif command == "search":
            kwargs: dict[str, Any] = {}
            if isinstance(flags.get("type"), str):
                kwargs["type"] = flags["type"]
            if isinstance(flags.get("sort"), str):
                kwargs["sort_by"] = flags["sort"]
            if limit is not None:
                kwargs["limit"] = limit
            result = yt.search(" ".join(positional), **kwargs)
        elif command == "channel":
            result = yt.get_channel(require_target())
        elif command == "channel-videos":
            kwargs = {"limit": limit} if limit is not None else {}
            result = yt.get_channel_videos(require_target(), **kwargs)
        elif command == "playlist":
            kwargs = {"limit": limit} if limit is not None else {}
            result = yt.get_playlist(require_target(), **kwargs)
        elif command == "comments":
            kwargs = {}
            if limit is not None:
                kwargs["limit"] = limit
            if isinstance(flags.get("sort"), str):
                kwargs["sort_by"] = flags["sort"]
            result = yt.get_comments(require_target(), **kwargs)
        elif command == "transcript":
            lang = flags.get("lang")
            result = yt.get_transcript(
                require_target(), lang if isinstance(lang, str) else None
            )
        elif command == "streams":
            result = yt.get_streams(require_target())
        elif command == "trending":
            kwargs = {"limit": limit} if limit is not None else {}
            cat: Any = target or "now"
            result = yt.get_trending(cat, **kwargs)
        elif command == "suggest":
            result = yt.get_suggestions(" ".join(positional))
        elif command == "related":
            kwargs = {"limit": limit} if limit is not None else {}
            result = yt.get_related(require_target(), **kwargs)
        else:
            sys.stderr.write(f"unknown command: {command}\n\n{USAGE}")
            return 1
    except Exception as err:
        sys.stderr.write(f"error: {err}\n")
        return 1

    sys.stdout.write(json.dumps(_to_jsonable(result), ensure_ascii=False, indent=2) + "\n")
    return 0


def main() -> None:
    """Console script entry point."""
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
