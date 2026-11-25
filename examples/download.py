"""動画をダウンロードする例 (最大 4K 対応).

使い方:
    python3 examples/download.py <URL または ID> [出力名] [--dir <保存先>]

既定の保存先はリポジトリ直下の download/ です。
高画質は映像と音声が別ファイルなので ffmpeg で結合します。
progressive（360p以下）だけで良ければ ffmpeg は不要です。
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from yt_api_wrapper import (
    CLIENTS,
    InvalidArgumentError,
    NetworkError,
    StreamFormat,
    UnavailableError,
    YouTube,
)

# ストリーム URL は発行元クライアントの User-Agent で取りにいく。
# get_streams は VISIONOS を優先して使うので、それに合わせる。
STREAM_HEADERS = {
    "User-Agent": CLIENTS["VISIONOS"].user_agent,
}

# 大きすぎるチャンクは弾かれやすいので控えめに刻む。
CHUNK_SIZE = 2 * 1024 * 1024


class ThrottledError(Exception):
    """YouTube が転送を打ち切ったことを表す。progressive へ切り替える合図。"""

    def __init__(self, message: str, downloaded: int, total: int) -> None:
        super().__init__(message)
        self.downloaded = downloaded
        self.total = total


def _fetch_bytes(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp_headers, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, {}, b""


def download_chunked(fmt: StreamFormat, path: Path, label: str) -> None:
    """URL を Range で分割取得してファイルに保存し、進捗を 1 行で表示する。"""
    assert fmt.url is not None
    status, headers, _ = _fetch_bytes(fmt.url, {**STREAM_HEADERS, "Range": "bytes=0-0"})
    if not (200 <= status < 300):
        raise RuntimeError(f"{label}: HTTP {status}")

    content_range = headers.get("content-range", "")
    total = 0
    if "/" in content_range:
        try:
            total = int(content_range.split("/")[-1])
        except ValueError:
            total = 0
    if not total:
        total = fmt.content_length or 0
    if not total:
        raise RuntimeError(f"{label}: サイズを取得できませんでした")

    done = 0
    with path.open("wb") as out:
        for start in range(0, total, CHUNK_SIZE):
            end = min(start + CHUNK_SIZE - 1, total - 1)
            chunk = b""
            for attempt in range(5):
                status, _, chunk = _fetch_bytes(
                    fmt.url, {**STREAM_HEADERS, "Range": f"bytes={start}-{end}"}
                )
                if 200 <= status < 300:
                    break
                if attempt >= 4:
                    raise ThrottledError(
                        f"{label}: {start / 1e6:.1f}MB 地点で YouTube に遮断されました（HTTP {status}）",
                        done,
                        total,
                    )
                sys.stdout.write(f"\r  {label}: 再試行 {attempt + 1}/4 ...          ")
                sys.stdout.flush()
                time.sleep(1.0 * (2**attempt))

            out.write(chunk)
            done = end + 1
            pct = round((done / total) * 100)
            sys.stdout.write(
                f"\r  {label}: {done / 1e6:.1f} / {total / 1e6:.1f}MB ({pct}%)   "
            )
            sys.stdout.flush()

    sys.stdout.write(f"\r  {label}: {total / 1e6:.1f}MB 完了          \n")
    sys.stdout.flush()


def merge(video_path: Path, audio_path: Path, out_path: Path) -> None:
    """ffmpeg で映像と音声を 1 つの mp4 にまとめる（再エンコードなし）。"""
    result = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out_path),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg が {result.returncode} で終了しました")


def download_progressive(streams, out_path: Path) -> None:
    """映像+音声が一体の progressive 形式を 1 本で落とす。画質は 360p 程度。"""
    single = next((f for f in streams.progressive if f.url), None)
    if not single or not single.url:
        raise RuntimeError("ダウンロード可能な形式が見つかりませんでした")

    print(f"画質: {single.quality_label}（映像+音声一体）\n")
    req = urllib.request.Request(single.url, headers=STREAM_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp, out_path.open("wb") as out:
        while True:
            buf = resp.read(65536)
            if not buf:
                break
            out.write(buf)
    print(f"保存しました: {out_path}")


def main() -> None:
    args = list(sys.argv[1:])
    out_dir: str | None = None

    if "--dir" in args:
        idx = args.index("--dir")
        if idx + 1 >= len(args):
            print("--dir には保存先のパスを指定してください", file=sys.stderr)
            raise SystemExit(1)
        out_dir = args[idx + 1]
        del args[idx : idx + 2]

    if not args:
        print(
            "使い方: python3 examples/download.py <URL または ID> [出力名] [--dir <保存先>]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    input_str = args[0]
    out_name = args[1] if len(args) > 1 else None

    target_dir = Path(out_dir).resolve() if out_dir else (Path(__file__).resolve().parent.parent / "download")
    target_dir.mkdir(parents=True, exist_ok=True)

    yt = YouTube(region="JP", language="ja")
    try:
        info = yt.get_video(input_str)
        streams = yt.get_streams(input_str)
    except InvalidArgumentError:
        print(f"動画 ID を読み取れませんでした: {input_str}", file=sys.stderr)
        print('例: python3 examples/download.py "https://www.youtube.com/watch?v=Rsfwu-c5S14"', file=sys.stderr)
        raise SystemExit(1)
    except UnavailableError:
        print(f"この動画は取得できません（非公開・削除済み・地域制限のいずれか）: {input_str}", file=sys.stderr)
        raise SystemExit(1)
    except NetworkError as err:
        print(f"YouTube への接続に失敗しました: {err}", file=sys.stderr)
        raise SystemExit(1)

    safe_name = re.sub(r'[/\\?%*:|"<>]', "_", out_name or info.title)[:80]
    out_path = target_dir / f"{safe_name}.mp4"

    print(f"タイトル: {info.title}")
    print(f"保存先  : {target_dir}")

    videos = sorted(
        [f for f in streams.adaptive if f.kind == "video" and f.url],
        key=lambda f: f.height or 0,
        reverse=True,
    )
    audios = sorted(
        [f for f in streams.adaptive if f.kind == "audio" and f.url],
        key=lambda f: f.bitrate or 0,
        reverse=True,
    )
    video = videos[0] if videos else None
    audio = audios[0] if audios else None

    if video and audio:
        kbps = round((audio.bitrate or 0) / 1000)
        print(f"画質: {video.quality_label} + 音声 {kbps}kbps\n")

        v_tmp = target_dir / f".{safe_name}.video"
        a_tmp = target_dir / f".{safe_name}.audio"
        try:
            download_chunked(video, v_tmp, "映像")
            download_chunked(audio, a_tmp, "音声")
            print("\n結合中...")
            merge(v_tmp, a_tmp, out_path)
            print(f"保存しました: {out_path}")
        except ThrottledError as err:
            print(f"\n{err}", file=sys.stderr)
            print("高画質の取得を諦めて、低画質版に切り替えます。\n", file=sys.stderr)
            download_progressive(streams, out_path)
        finally:
            v_tmp.unlink(missing_ok=True)
            a_tmp.unlink(missing_ok=True)
    else:
        download_progressive(streams, out_path)


if __name__ == "__main__":
    main()
