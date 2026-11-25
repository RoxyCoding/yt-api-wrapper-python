# yt-api-wrapper (Python)

[RoxyCoding/yt-api-wrapper](https://github.com/RoxyCoding/yt-api-wrapper) の Python 版。

YouTube の**非公式** API ラッパー。API キーなしで、動画情報・検索・チャンネル・再生リスト・コメント・字幕・コミュニティ投稿・ライブチャット・ストリーム URL を取得できます。

- 依存パッケージ **ゼロ**（Python 3.10+ 標準ライブラリのみ）
- 型ヒント完備（`py.typed` 同梱）
- CLI (`yt-api`) 同梱
- 最大 4K でのダウンロードに対応（[`examples/download.py`](examples/download.py)）

## インストール

```bash
pip install -e .
```

または `uv` を使用する場合:

```bash
uv pip install -e .
```

## クイックスタート

```python
from yt_api_wrapper import YouTube

yt = YouTube(region="JP", language="ja")

video = yt.get_video("https://youtu.be/dQw4w9WgXcQ")
print(video.title, video.view_count, video.like_count)

results = yt.search_videos("lofi hip hop", limit=10, sort_by="views")
```

## API

コンストラクタ引数はすべて省略可能です。

```python
YouTube(
    region="JP",      # ISO 国コード（既定 "US"）
    language="ja",    # UI 言語（既定 "en"）
    timeout=20.0,     # 秒（既定 20.0）
    retries=3,        # 5xx / 429 / タイムアウトの再試行回数（既定 3）
    cookie="...",     # ログイン用（任意・上級者向け）
)
```

動画 ID は生の ID でも、`watch?v=` / `youtu.be` / `shorts` / `embed` / `live` のどの URL でも渡せます。
チャンネルは `UC...` ID、`@ハンドル`、`/c/名前`、URL のいずれでも構いません。

### 動画

```python
yt.get_video(video_id, with_streams=False)  # VideoDetails
yt.get_streams(video_id)                    # StreamBundle
yt.get_related(video_id, limit=20)          # list[VideoCompact]
yt.get_oembed(video_id)                     # OEmbed（最軽量の存在確認）
```

### 検索

```python
yt.search(
    "query",
    type="video",                       # video | channel | playlist | movie | all
    upload_date="week",                 # hour | today | week | month | year
    duration="long",                    # short | medium | long
    sort_by="views",                    # relevance | date | views | rating
    features=["hd", "4k", "subtitles"],
    limit=50,
)

yt.search_videos("query", limit=20)     # 動画のみ
yt.get_suggestions("python")            # サジェスト候補
```

### チャンネル

```python
yt.get_channel("@MrBeast")                      # ChannelDetails
yt.get_channel_videos("@veritasium", limit=30)
yt.get_channel_shorts("@MrBeast")
yt.get_channel_streams("@MrBeast")
yt.get_channel_playlists("@veritasium", limit=30)
yt.resolve_channel_id("@MrBeast")               # -> "UCX6OQ3..."
```

### コミュニティ投稿

```python
posts = yt.get_community_posts("@veritasium", limit=20)
posts[0].text          # 本文
posts[0].images        # 添付画像
posts[0].attachment    # 共有された動画・再生リスト
posts[0].poll_choices  # アンケートの選択肢
```

### ライブチャット

```python
import time

page = yt.get_live_chat(video_id)
while page.continuation:
    time.sleep(3)
    page = yt.get_live_chat(video_id, page.continuation)
    for m in page.items:
        print(m.author.name, m.text, m.purchase_amount or "")
```

### 再生リスト

```python
pl = yt.get_playlist("PLxxxx", limit=200)
print(pl.title, pl.video_count, len(pl.videos))
```

### コメント

```python
comments = yt.get_comments(video_id, limit=100, sort_by="top")
if comments and comments[0].replies_token:
    replies = yt.get_comment_replies(comments[0].replies_token)
```

### 字幕・文字起こし

```python
yt.get_captions(video_id)              # list[CaptionTrack]
yt.get_transcript(video_id, "ja")      # list[TranscriptSegment]
```

### 人気の動画

```python
yt.get_trending("now", limit=50)       # now | music | gaming | movies
```

### 低レベル API

```python
yt.raw("browse", {"browseId": "FEwhat_to_watch"})
yt.get_raw_page_data("/results?search_query=test")
```

## エラー処理

すべて `YouTubeError` を継承しています。

```python
from yt_api_wrapper import (
    InvalidArgumentError,
    MembersOnlyError,
    NetworkError,
    ParseError,
    UnavailableError,
)

try:
    yt.get_video(video_id)
except MembersOnlyError as err:
    # メンバー限定。err.required_tier に必要なランク名が入ります
    print(err.required_tier)
except UnavailableError:
    # 非公開・削除済み・地域制限
    pass
except NetworkError:
    # 通信失敗（5xx / 429 は自動再試行済み）
    pass
```

## CLI

```bash
yt-api video dQw4w9WgXcQ
yt-api search "lofi hip hop" --limit 5 --type video
yt-api channel @MrBeast
yt-api channel-videos @veritasium --limit 10
yt-api playlist PLxxxx --limit 50
yt-api comments dQw4w9WgXcQ --limit 20 --sort newest
yt-api transcript dQw4w9WgXcQ --lang ja
yt-api streams dQw4w9WgXcQ
yt-api trending music
yt-api suggest "python async"
yt-api related dQw4w9WgXcQ --limit 10
```

グローバルオプション: `--region JP` `--language ja`

## 開発・テスト

```bash
pytest
python3 examples/basic.py
python3 examples/download.py "https://youtu.be/Rsfwu-c5S14"
```

## ライセンス

MIT
