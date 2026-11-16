import asyncio
import logging
import threading

from aiohttp import web

import config
from services import links

log = logging.getLogger(__name__)


def _app(repos):
    async def download(request):
        entry = links.lookup(request.match_info["token"])
        if entry is None:
            raise web.HTTPNotFound(text="link not found")
        if entry == "expired":
            raise web.HTTPGone(text="link expired")
        gh = repos.get(entry["repo"])
        if gh is None:
            raise web.HTTPNotFound(text="repo not configured")
        try:
            url = await gh.signed_url(entry["asset"])
        except Exception:
            log.exception("signed url failed")
            raise web.HTTPBadGateway(text="could not get a download URL from GitHub")
        raise web.HTTPFound(url, headers={"Cache-Control": "no-store"})

    app = web.Application()
    app.router.add_get("/d/{token}", download)
    app.router.add_get("/d/{token}/{name:.*}", download)
    return app


async def _serve(repos):
    runner = web.AppRunner(_app(repos), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.WEB_PORT).start()
    await asyncio.Event().wait()


def start(repos):
    """سرور کوچک لینک دانلود را در یک ترد جدا اجرا می‌کند (جدا از حلقه‌ی تلگرام)."""
    def run():
        try:
            asyncio.run(_serve(repos))
        except Exception:
            log.exception("link server stopped")

    threading.Thread(target=run, name="link-server", daemon=True).start()
