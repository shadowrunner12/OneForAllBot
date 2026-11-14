from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
AUDIO_EXT = {".mp3", ".m4a"}
PARTIAL = (".part", ".ytdl", ".tmp", ".temp")


def biggest_file(folder):
    files = [
        f for f in Path(folder).rglob("*")
        if f.is_file() and not f.name.endswith(PARTIAL)
    ]
    if not files:
        raise FileNotFoundError("بعد از دانلود هیچ فایلی پیدا نشد.")
    return max(files, key=lambda f: f.stat().st_size)
