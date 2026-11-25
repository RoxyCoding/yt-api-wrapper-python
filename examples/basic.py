"""Basic usage demo for yt-api-wrapper.

Run with:
    python3 examples/basic.py
"""

from yt_api_wrapper import YouTube, format_duration


def main() -> None:
    yt = YouTube(region="JP", language="ja")

    # 1. Video metadata
    video = yt.get_video("https://youtu.be/dQw4w9WgXcQ")
    print(f"\n[動画] {video.title}")
    print(f"  チャンネル : {video.channel.name if video.channel else None}")
    print(f"  再生数     : {video.view_count:,}" if video.view_count is not None else "  再生数     : None")
    print(f"  高評価     : {video.like_count:,}" if video.like_count is not None else "  高評価     : None")
    print(f"  長さ       : {format_duration(video.duration_seconds or 0)}")
    print(f"  投稿日     : {video.publish_date}")

    # 2. Search with filters
    print('\n[検索] "lofi hip hop" 再生数順')
    for item in yt.search_videos("lofi hip hop", limit=5, sort_by="views"):
        views = f"{item.view_count:,}" if item.view_count is not None else "?"
        print(f"  {item.title[:40]} — {views} views")

    # 3. Channel
    channel = yt.get_channel("@MrBeast")
    subs = f"{channel.subscriber_count:,}" if channel.subscriber_count is not None else "?"
    print(f"\n[チャンネル] {channel.name} — 登録者 {subs}")

    # 4. Comments
    print("\n[コメント]")
    for comment in yt.get_comments("dQw4w9WgXcQ", limit=3):
        print(f"  {comment.author.name}: {comment.text[:50]} (♥{comment.like_count})")

    # 5. Transcript
    transcript = yt.get_transcript("dQw4w9WgXcQ", "en")
    print(f"\n[字幕] {len(transcript)} 行")
    if len(transcript) > 1:
        print(f"  {transcript[1].start_seconds}s: {transcript[1].text}")

    # 6. Streams
    streams = yt.get_streams("dQw4w9WgXcQ")
    videos = sorted(
        [f for f in streams.adaptive if f.kind == "video"],
        key=lambda f: f.height or 0,
        reverse=True,
    )
    best = videos[0] if videos else None
    print(
        f"\n[ストリーム] {len(streams.formats)} 形式 / "
        f"最高画質 {best.quality_label if best else 'N/A'}"
    )
    print(f"  有効期限: {streams.expires_in_seconds}秒")


if __name__ == "__main__":
    main()
