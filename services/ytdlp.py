import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import config
from services.proc import run, run_lines
from state import Cancelled
from utils.files import biggest_file

HOSTS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "instagram.com": "instagram",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "soundcloud.com": "soundcloud",
    "tiktok.com": "tiktok",
    "twitch.tv": "twitch",
    "vimeo.com": "vimeo",
    "reddit.com": "reddit",
}
COOKIE_PLATFORMS = ("youtube", "instagram", "twitter", "soundcloud")
PLATFORM_LABELS = {
    "youtube": "یوتیوب", "instagram": "اینستاگرام", "twitter": "توییتر / X",
    "soundcloud": "ساندکلاد", "tiktok": "تیک‌تاک", "twitch": "توییچ",
    "vimeo": "Vimeo", "reddit": "Reddit",
}


def platform_of(url):
    host = urlparse(url).netloc.lower().split(":")[0]
    for domain, name in HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return "other"


def is_playlist(url):
    if platform_of(url) != "youtube" or "youtu.be/" in url:
        return False
    return "playlist?list=" in url or ("list=" in url and "watch?v=" not in url)


def cookie_file(platform):
    path = config.COOKIES_DIR / f"{platform}.txt"
    return path if path.exists() and path.stat().st_size > 0 else None


def _base(url):
    platform = platform_of(url)
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings"]
    cookies = cookie_file(platform)
    if cookies:
        cmd += ["--cookies", str(cookies)]
    if platform == "youtube" and config.YT_CLIENTS:
        cmd += ["--extractor-args", f"youtube:player_client={config.YT_CLIENTS}"]
    return cmd


async def probe(url):
    code, out, err = await run(_base(url) + ["-J", "--no-playlist", url])
    if code != 0:
        raise RuntimeError((err or out)[-600:])
    return json.loads(out)


async def probe_playlist(url):
    code, out, err = await run(_base(url) + ["-J", "--flat-playlist", url])
    if code != 0:
        raise RuntimeError((err or out)[-600:])
    info = json.loads(out)
    entries = [
        {"id": e["id"], "title": e.get("title") or e["id"]}
        for e in info.get("entries", []) if e and e.get("id")
    ]
    return info.get("title") or "پلی‌لیست", entries


def _has_video(f):
    return f.get("vcodec") not in (None, "none")


def _size(f):
    return f.get("filesize") or f.get("filesize_approx") or 0


def _size_text(num):
    if not num:
        return ""
    mb = num / (1024 * 1024)
    return f" (~{mb / 1024:.1f}GB)" if mb >= 1024 else f" (~{mb:.0f}MB)"


def describe(info, url):
    """برمی‌گرداند: (عنوان، تامبنیل، [(متن دکمه، فرمت)])"""
    formats = info.get("formats") or []
    title = info.get("title") or "ویدیو"
    thumb = info.get("thumbnail")

    if not any(_has_video(f) for f in formats) and info.get("entries"):
        first = next((e for e in info["entries"] if e), None)
        if first:
            formats = first.get("formats") or formats
            title = first.get("title") or title
            thumb = first.get("thumbnail") or thumb

    video = [f for f in formats if _has_video(f)]
    audio = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max(audio, key=lambda f: f.get("abr") or 0) if audio else None
    audio_size = _size(best_audio) if best_audio else 0
    platform = platform_of(url)
    options = []

    if platform == "youtube":
        heights = sorted({f["height"] for f in video if f.get("height")}, reverse=True)
        tiers = [h for h in (1080, 720, 480, 360, 240) if heights and h <= heights[0]]
        if heights and heights[0] > 1080:
            tiers.insert(0, heights[0])
        seen = set()
        for h in tiers:
            pool = [f for f in video if f.get("height") and f["height"] <= h]
            if not pool:
                continue
            best = max(pool, key=lambda f: f["height"])
            if best["height"] in seen:
                continue
            seen.add(best["height"])
            label = f"{best['height']}p"
            options.append((f"{label}{_size_text(_size(best) + audio_size)}", str(h)))
        if audio:
            options.append((f"فقط صدا 🎵{_size_text(audio_size)}", "audio"))
    elif platform == "soundcloud" and audio:
        options.append((f"دانلود 🎵{_size_text(audio_size)}", "audio"))
    elif video:
        best = max(video, key=lambda f: (f.get("height") or 0) * (f.get("width") or 1))
        options.append((f"دانلود 📥{_size_text(_size(best))}", "best"))
    elif formats:
        options.append(("دانلود 📥", "best"))

    return title, thumb, options


def selector(fmt):
    if fmt == "audio":
        return "bestaudio[ext=m4a]/bestaudio/best"
    if fmt == "best":
        return "bv*+ba/b"
    return f"bv*[height<={fmt}]+ba/b[height<={fmt}]"


PROGRESS = "PROG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s"


def _num(text):
    try:
        return float(text)
    except ValueError:
        return 0.0


async def _download(url, fmt, folder, use_selector, stop, progress, stage):
    cmd = _base(url) + [
        "--no-playlist", "--newline",
        "--progress-template", "download:" + PROGRESS,
        "-o", "%(title).80s.%(ext)s",
    ]
    if use_selector:
        cmd += ["-f", selector(fmt)]
    if fmt != "audio":
        cmd += ["--merge-output-format", "mp4"]

    part = 0
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    async def on_line(line):
        nonlocal part
        if line.startswith("PROG|"):
            _, done, total, estimate = (line.split("|") + ["", "", ""])[:4]
            if progress:
                await progress(_num(done), _num(total) or _num(estimate), f"بخش {part}" if part > 1 else None)
        elif line.startswith("[download] Destination:"):
            part += 1
        elif stage and line.startswith(("[Merger]", "[ExtractAudio]", "[VideoRemuxer]", "[VideoConvertor]")):
            await stage("در حال ادغام و آماده‌سازی فایل...")

    code, tail = await run_lines(cmd + [url], cwd=folder, stop=stop, on_line=on_line, ignore=("PROG|",))
    if code != 0:
        raise RuntimeError(tail[-600:])
    return biggest_file(folder)


async def download(url, fmt, folder, stop=None, progress=None, stage=None):
    twitter = platform_of(url) == "twitter"
    attempts, delay = (4, 8) if twitter else (2, 5)
    last = None
    for n in range(attempts):
        try:
            # اگر انتخاب فرمت جواب نداد (مثلاً پست عکس اینستاگرام)، بار بعد بدون فرمت امتحان می‌کنیم
            return await _download(url, fmt, folder, not (fmt == "best" and n > 0), stop, progress, stage)
        except Cancelled:
            raise
        except Exception as e:
            last = e
            if n < attempts - 1:
                await asyncio.sleep(delay)
    raise last
