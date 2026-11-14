import asyncio
import os
import re
from pathlib import Path

import config
from services.proc import run
from state import Cancelled
from utils.names import ascii_name

CHUNK = 8 * 1024 * 1024


def _split(path, part_size, stop):
    """فایل را بدون تغییر محتوا به پارت‌های .001 / .002 / ... تقسیم می‌کند و فایل اصلی را پاک می‌کند."""
    parts = []
    try:
        with open(path, "rb") as src:
            index = 0
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                index += 1
                part = Path(f"{path}.{index:03d}")
                parts.append(part)
                written = 0
                with open(part, "wb") as out:
                    while chunk:
                        out.write(chunk)
                        written += len(chunk)
                        if stop and stop():
                            raise Cancelled()
                        if written >= part_size:
                            break
                        chunk = src.read(min(CHUNK, part_size - written))
    except BaseException:
        for part in parts:
            part.unlink(missing_ok=True)
        raise
    Path(path).unlink()
    return parts


async def make_zip(paths, root, base_name, password=None, split=False, stop=None, tick=None):
    """
    ZIP در حالت Store (بدون فشرده‌سازی). اگر حجم از سقف GitHub بیشتر باشد، فایل ZIP
    یک‌تکه ساخته و بعد به پارت‌های .zip.001 تقسیم می‌شود (با 7-Zip و WinRAR باز می‌شود).
    ساخت مستقیم ZIP چندبخشی با -v در 7-Zip نسخه 23 (اوبونتو ۲۴) خطا می‌دهد.
    """
    root = Path(root)
    base = re.sub(r"\.(zip|7z|rar)$", "", base_name, flags=re.I)
    archive = ascii_name(base + ".zip")
    inputs = [os.path.relpath(p, root) for p in paths]
    if archive in inputs:
        archive = ascii_name(base + "_archive.zip")

    cmd = ["7z", "a", "-tzip", "-mx=0"]
    if password:
        cmd += [f"-p{password}", "-mem=AES256"]
    cmd.append(archive)
    cmd += inputs

    code, out, err = await run(cmd, cwd=root, stop=stop, tick=tick)
    if code != 0:
        (root / archive).unlink(missing_ok=True)
        raise RuntimeError("خطا در ساخت آرشیو:\n" + (err or out)[-300:])

    for p in paths:
        Path(p).unlink(missing_ok=True)

    target = root / archive
    if not target.exists():
        raise RuntimeError("فایل آرشیو ساخته نشد.")
    if target.stat().st_size <= config.PART_SIZE and not split:
        return [target]
    return await asyncio.to_thread(_split, target, config.PART_SIZE, stop)
