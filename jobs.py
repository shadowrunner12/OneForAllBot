import logging
import shutil
import time
from contextlib import asynccontextmanager

from pyrogram import StopTransmission

import config
from core import repos, state
from pipeline import Runner
from state import Cancelled
from ui import Status, fmt_time
from utils.errors import explain

log = logging.getLogger(__name__)


@asynccontextmanager
async def slot(status, prefix):
    """صف تک‌نفره: هر بار فقط یک کار اجرا می‌شود و پوشه‌ی موقتش بعدش پاک می‌شود."""
    async with state.lock:
        state.cancel = False
        state.live_name = None
        status.began = None
        folder = config.WORK_DIR / f"{prefix}_{time.time_ns()}"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            yield folder
        except (Cancelled, StopTransmission):
            await status.set("🛑 **عملیات لغو شد**\nفایل‌های موقت پاک شدند.")
        except Exception as e:
            log.exception("job failed")
            await status.set(f"❌ **خطا**\n{explain(e)}")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


async def _finish(status, outcome):
    text = f"{outcome.text}\n\n⏱ زمان کل: `{fmt_time(status.elapsed())}`"
    await status.set(text, outcome.kb)


async def _single(client, status, item, do_zip, password):
    async with slot(status, "job") as folder:
        outcome = await Runner(client, state, repos, status).process(item, folder, do_zip, password)
        await _finish(status, outcome)


async def _batch(client, status, items, title, zip_mode, password, repo):
    async with slot(status, "batch") as folder:
        outcome = await Runner(client, state, repos, status).batch(items, title, zip_mode, password, folder, repo)
        await _finish(status, outcome)


async def _playlist(client, status, entries, fmt, dest, repo):
    async with slot(status, "pl") as folder:
        await Runner(client, state, repos, status).playlist(entries, fmt, dest, repo, folder)


async def _status(client, chat_id):
    msg = await client.send_message(
        chat_id, "⏳ **در صف انتظار**\nنوبتت که بشه، خودکار شروع می‌شه."
    )
    return Status(client, msg, state)


async def submit_single(client, chat_id, item):
    status = await _status(client, chat_id)
    do_zip, password = state.take_zip()
    state.spawn(_single(client, status, item, do_zip, password))


async def submit_batch(client, status, items, title, zip_mode, password, repo="public"):
    state.spawn(_batch(client, status, items, title, zip_mode, password, repo))


async def submit_playlist(client, chat_id, entries, fmt, dest, repo="public"):
    status = await _status(client, chat_id)
    state.spawn(_playlist(client, status, entries, fmt, dest, repo))
