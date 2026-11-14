import json
from pathlib import Path

from services.proc import run


async def probe(path):
    info = {"duration": 0, "width": 0, "height": 0}
    code, out, _ = await run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json", path,
    ])
    if code != 0:
        return info
    try:
        data = json.loads(out or "{}")
        stream = (data.get("streams") or [{}])[0]
        info["width"] = int(stream.get("width") or 0)
        info["height"] = int(stream.get("height") or 0)
        info["duration"] = float(data.get("format", {}).get("duration") or 0)
    except (ValueError, TypeError):
        pass
    return info


async def thumbnail(path, out):
    out = Path(out)
    for start in ("1", "0"):
        await run(["ffmpeg", "-y", "-ss", start, "-i", path, "-frames:v", "1",
                   "-vf", "scale=320:-2", out])
        if out.exists():
            return out
    return None


async def to_gif(path, max_seconds, stop=None):
    """برمی‌گرداند: (مسیر gif، آیا کوتاه شد)"""
    path = Path(path)
    info = await probe(path)
    duration = info["duration"] or max_seconds
    clip = min(duration, max_seconds)
    palette = path.with_name(path.stem + "_palette.png")
    gif = path.with_suffix(".gif")
    scale = "fps=12,scale=480:-1:flags=lanczos"
    try:
        code, _, err = await run(
            ["ffmpeg", "-y", "-t", str(clip), "-i", path, "-vf", scale + ",palettegen", palette],
            stop=stop,
        )
        if code != 0:
            raise RuntimeError("ساخت پالت GIF ناموفق بود: " + err[-300:])
        code, _, err = await run(
            ["ffmpeg", "-y", "-t", str(clip), "-i", path, "-i", palette,
             "-lavfi", f"{scale}[x];[x][1:v]paletteuse", gif],
            stop=stop,
        )
        if code != 0:
            raise RuntimeError("تبدیل به GIF ناموفق بود: " + err[-300:])
    finally:
        palette.unlink(missing_ok=True)
    return gif, duration > max_seconds
