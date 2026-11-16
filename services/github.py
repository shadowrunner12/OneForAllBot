import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from utils.names import ascii_name

API = "https://api.github.com"


@dataclass
class Asset:
    id: int
    name: str
    url: str
    size: int


async def _chunks(path, size, name, progress):
    sent = 0
    with open(path, "rb") as f:
        while chunk := f.read(512 * 1024):
            sent += len(chunk)
            if progress:
                await progress(sent, size, name)
            yield chunk
            await asyncio.sleep(0)


class Release:
    def __init__(self, gh, http, data):
        self.gh = gh
        self.http = http
        self.id = data["id"]
        self.tag = data["tag_name"]
        self.page = data["html_url"]
        self.upload_url = data["upload_url"].split("{")[0]
        self.assets = []

    def _unique(self, name):
        used = {a.name for a in self.assets}
        n = 1
        candidate = name
        while candidate in used:
            candidate = f"{n}_{name}"
            n += 1
        return candidate

    async def upload(self, path, name=None, progress=None):
        path = Path(path)
        name = self._unique(ascii_name(name or path.name))
        size = path.stat().st_size
        headers = {
            **self.gh.headers,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(size),
        }
        resp = await self.http.post(
            self.upload_url, params={"name": name}, headers=headers,
            content=_chunks(path, size, name, progress),
        )
        if resp.status_code != 201:
            raise RuntimeError(f"خطا در آپلود {name}: {resp.text[:300]}")
        data = resp.json()
        asset = Asset(data["id"], data["name"], data["browser_download_url"], size)
        self.assets.append(asset)
        path.unlink(missing_ok=True)
        return asset

    async def upload_links(self, folder):
        """فایل links.txt برای دانلود یکجا (مثلاً با IDM)؛ فقط وقتی بیشتر از یک فایل داریم."""
        if len(self.assets) <= 1 or self.gh.key == "private":
            return None
        path = Path(folder) / "links.txt"
        path.write_text("\n".join(a.url for a in self.assets) + "\n", encoding="utf-8")
        asset = await self.upload(path, "links.txt")
        self.assets.remove(asset)
        return asset.url


class GitHub:
    def __init__(self, token, repo, key="public"):
        self.repo = repo
        self.key = key
        self.mark = "🔒" if key == "private" else "🌐"
        self.upload_label = f"آپلود روی گیت‌هاب {self.mark}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @asynccontextmanager
    async def release(self, title, body=""):
        """اگر وسط کار خطایی بیاید یا لغو شود، Release نیمه‌کاره حذف می‌شود."""
        async with httpx.AsyncClient(timeout=None) as http:
            tag = f"v{time.time_ns() // 1_000_000}"
            resp = await http.post(
                f"{API}/repos/{self.repo}/releases", headers=self.headers,
                json={"tag_name": tag, "name": title, "body": body},
            )
            if resp.status_code != 201:
                raise RuntimeError(f"خطا در ساخت Release: {resp.text[:300]}")
            rel = Release(self, http, resp.json())
            try:
                yield rel
            except Exception:
                await self._discard(http, rel.id, rel.tag)
                raise

    async def _discard(self, http, release_id, tag):
        try:
            await http.delete(f"{API}/repos/{self.repo}/releases/{release_id}", headers=self.headers)
            await http.delete(f"{API}/repos/{self.repo}/git/refs/tags/{tag}", headers=self.headers)
        except Exception:
            pass

    async def list_releases(self, per_page=10):
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(
                f"{API}/repos/{self.repo}/releases?per_page={per_page}", headers=self.headers
            )
            if resp.status_code != 200:
                raise RuntimeError(f"خطا در ارتباط با گیت‌هاب: {resp.status_code}")
            return resp.json()

    async def asset(self, asset_id):
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(f"{API}/repos/{self.repo}/releases/assets/{asset_id}", headers=self.headers)
            if resp.status_code != 200:
                raise RuntimeError(f"فایل پیدا نشد ({resp.status_code})")
            return resp.json()

    async def release_assets(self, release_id):
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(f"{API}/repos/{self.repo}/releases/{release_id}", headers=self.headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Release پیدا نشد ({resp.status_code})")
            return resp.json().get("assets", [])

    async def signed_url(self, asset_id):
        """لینک امضاشده‌ی کوتاه‌مدت گیت‌هاب برای دانلود فایل ریپوی خصوصی (بدون نیاز به توکن)."""
        headers = {**self.headers, "Accept": "application/octet-stream"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
            resp = await http.get(f"{API}/repos/{self.repo}/releases/assets/{asset_id}", headers=headers)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                return resp.headers["location"]
            raise RuntimeError(f"گرفتن لینک دانلود ناموفق بود ({resp.status_code})")

    async def rename_asset(self, asset_id, name):
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.patch(
                f"{API}/repos/{self.repo}/releases/assets/{asset_id}",
                headers=self.headers, json={"name": name},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"خطا در تغییر نام: {resp.status_code} {resp.text[:200]}")
            return resp.json()

    async def delete_release(self, release_id):
        async with httpx.AsyncClient(timeout=30) as http:
            url = f"{API}/repos/{self.repo}/releases/{release_id}"
            got = await http.get(url, headers=self.headers)
            tag = got.json().get("tag_name") if got.status_code == 200 else None
            resp = await http.delete(url, headers=self.headers)
            if resp.status_code != 204:
                raise RuntimeError(f"خطا در حذف: {resp.status_code}")
            if tag:
                await http.delete(f"{API}/repos/{self.repo}/git/refs/tags/{tag}", headers=self.headers)
