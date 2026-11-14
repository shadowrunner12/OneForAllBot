import os
import re
import sys
import time
from urllib.parse import unquote, urlparse

import httpx

import config
from services.proc import run
from utils.files import biggest_file
from utils.names import clean_name

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}


async def mega(url, folder, stop=None, tick=None):
    code, out, err = await run(
        ["megadl", "--no-progress", "--path", folder, url], stop=stop, tick=tick
    )
    if code != 0:
        raise RuntimeError("خطا در دانلود از Mega:\n" + (err or out)[-400:])
    return biggest_file(folder)


async def gdrive(url, folder, stop=None, tick=None):
    cmd = [sys.executable, "-m", "gdown", "--fuzzy", url, "-O", f"{folder}/"]
    code, out, err = await run(cmd, cwd=folder, stop=stop, tick=tick)
    if code != 0:
        raise RuntimeError("خطا در دانلود از Google Drive:\n" + (err or out)[-400:])
    return biggest_file(folder)


def _filename(resp, url):
    disposition = resp.headers.get("content-disposition", "")
    match = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.I) \
        or re.search(r'filename="?([^";]+)"?', disposition, re.I)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    name = os.path.basename(unquote(urlparse(str(resp.url)).path))
    return name or f"file_{int(time.time())}.bin"


async def direct(url, folder, progress):
    headers = dict(BROWSER_HEADERS)
    host = urlparse(url).netloc.lower()
    if host.endswith("github.com") and config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    async with httpx.AsyncClient(follow_redirects=True, timeout=60, headers=headers) as http:
        async with http.stream("GET", url) as resp:
            if resp.status_code == 404:
                raise RuntimeError(f"لینک وجود نداره یا حذف شده (404):\n{url}")
            resp.raise_for_status()
            path = folder / clean_name(_filename(resp, url))
            total = int(resp.headers.get("content-length") or 0)
            current = 0
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes(512 * 1024):
                    f.write(chunk)
                    current += len(chunk)
                    await progress(current, total)
    return path
