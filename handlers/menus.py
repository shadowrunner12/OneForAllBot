import re

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

import config
import jobs
from core import app, owner, repos, state
from services import ytdlp
from state import Item, Menu
from utils.errors import explain
from utils.names import code

RANGE = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")


def target(choice):
    """(مقصد، ریپو، GIF؟) از روی گزینه‌ی دکمه."""
    dest = "chat" if choice in ("chat", "gif") else "github"
    repo = "private" if choice == "private" else "public"
    return dest, repo, choice == "gif"


def dest_kb(make_data, chat=True, gif=False):
    """دکمه‌های انتخاب مقصد؛ گزینه‌ی ریپوی خصوصی فقط وقتی تنظیم شده باشه نمایش داده می‌شه."""
    rows = []
    if chat:
        rows.append([Btn("📤 ارسال در چت", callback_data=make_data("chat"))])
    if "private" in repos:
        rows.append([Btn("🌐 گیت‌هاب عمومی", callback_data=make_data("github"))])
        rows.append([Btn("🔒 گیت‌هاب خصوصی", callback_data=make_data("private"))])
    else:
        rows.append([Btn("☁️ آپلود روی گیت‌هاب", callback_data=make_data("github"))])
    if gif:
        rows.append([Btn(f"🎞 GIF ({config.GIF_MAX_SECONDS} ثانیه اول)", callback_data=make_data("gif"))])
    return Markup(rows)


async def ask_target(message, item, chat=True):
    """پیش از آپلود می‌پرسد کجا برود (چت / ریپوی عمومی / ریپوی خصوصی)."""
    token = state.keep(item)
    label = item.custom_name or item.name or item.url or ""
    await message.reply_text(
        f"📍 **کجا آپلود کنم؟**\n`{code(label[:80])}`",
        reply_markup=dest_kb(lambda c: f"s:{token}:{c}", chat=chat),
    )


async def _edit_any(message, text, kb):
    if message.photo:
        await message.edit_caption(text[:1024], reply_markup=kb)
    else:
        await message.edit_text(text, reply_markup=kb)


async def offer(client, message, url, name):
    """بررسی لینک و نمایش منوی کیفیت (یا درخواست بازه برای پلی‌لیست)."""
    note = await message.reply_text("🔎 در حال بررسی لینک...")
    try:
        if ytdlp.is_playlist(url):
            title, entries = await ytdlp.probe_playlist(url)
            if not entries:
                return await note.edit_text("هیچ ویدیویی در این پلی‌لیست پیدا نشد.")
            state.awaiting_range = {"title": title, "entries": entries}
            shown = entries[:60]
            listing = "\n".join(f"{i}. {code(e['title'])}" for i, e in enumerate(shown, 1))
            if len(entries) > len(shown):
                listing += f"\n... و {len(entries) - len(shown)} مورد دیگر"
            return await note.edit_text(
                f"«{code(title)}» — {len(entries)} ویدیو:\n\n{listing[:3300]}\n\n"
                f"✍️ بازه‌ای که می‌خوای رو بفرست (مثلاً `1-10`، حداکثر {config.PLAYLIST_MAX} ویدیو)."
            )
        info = await ytdlp.probe(url)
        title, thumb, options = ytdlp.describe(info, url)
    except Exception as e:
        return await note.edit_text(f"❌ **بررسی لینک ناموفق بود**\n{explain(e)}")

    if not options:
        return await note.edit_text("این لینک هیچ ویدیو یا فایل قابل‌دانلودی نداره.")

    token = state.remember(Menu(url=url, title=title, name=name))
    kb = Markup([[Btn(label, callback_data=f"q:{token}:{fmt}")] for label, fmt in options])
    caption = f"🎬 **{code(title)}**\n\nکیفیت مورد نظر رو انتخاب کن 👇"
    await note.delete()
    if thumb:
        try:
            return await message.reply_photo(thumb, caption=caption[:1024], reply_markup=kb)
        except Exception:
            pass
    await message.reply_text(caption, reply_markup=kb)


async def apply_range(message, first, last):
    pending = state.awaiting_range
    start, end = first, last or first
    chosen = pending["entries"][max(start - 1, 0):end][:config.PLAYLIST_MAX]
    if not chosen:
        return await message.reply_text("⚠️ این بازه معتبر نیست، دوباره بفرست.")
    state.awaiting_range = None
    token = state.remember(Menu(url="", title=pending["title"], entries=chosen))
    rows = [[Btn(f"{h}p", callback_data=f"q:{token}:{h}")] for h in (1080, 720, 480, 360)]
    rows.append([Btn("فقط صدا 🎵", callback_data=f"q:{token}:audio")])
    await message.reply_text(
        f"🎬 **{len(chosen)} ویدیو** (قسمت {start} تا {start + len(chosen) - 1})\nکیفیت رو انتخاب کن:",
        reply_markup=Markup(rows),
    )


@app.on_callback_query(filters.regex(r"^q:(\w+):(\w+)$") & owner)
async def pick_quality(client, cb):
    token, fmt = cb.matches[0].group(1), cb.matches[0].group(2)
    menu = state.menus.get(token)
    if not menu:
        return await cb.answer("این منو منقضی شده، لینک رو دوباره بفرست.", show_alert=True)
    kb = dest_kb(lambda c: f"d:{token}:{fmt}:{c}", chat=True, gif=fmt != "audio" and not menu.entries)
    await cb.answer()
    await _edit_any(cb.message, f"🎬 **{code(menu.title)}**\n\nمقصد رو انتخاب کن 👇", kb)


@app.on_callback_query(filters.regex(r"^d:(\w+):(\w+):(chat|github|private|gif)$") & owner)
async def pick_destination(client, cb):
    token, fmt, choice = cb.matches[0].group(1, 2, 3)
    menu = state.menus.pop(token, None)
    if not menu:
        return await cb.answer("این منو منقضی شده، لینک رو دوباره بفرست.", show_alert=True)
    await cb.answer()
    chat_id = cb.message.chat.id
    try:
        await cb.message.delete()
    except Exception:
        pass

    dest, repo, gif = target(choice)
    if menu.entries:
        return await jobs.submit_playlist(client, chat_id, menu.entries, fmt, dest, repo)
    item = Item(
        kind="url", url=menu.url, name=menu.title, fmt=fmt, dest=dest, repo=repo,
        gif=gif, custom_name=menu.name,
    )
    await jobs.submit_single(client, chat_id, item)


@app.on_callback_query(filters.regex(r"^r:([\w-]+):(\w+):(chat|github|private)$") & owner)
async def retry_video(client, cb):
    vid, fmt, choice = cb.matches[0].group(1, 2, 3)
    await cb.answer("دوباره تلاش می‌کنم...")
    dest, repo, _ = target(choice)
    item = Item(kind="url", url=f"https://www.youtube.com/watch?v={vid}", fmt=fmt, dest=dest, repo=repo)
    await jobs.submit_single(client, cb.message.chat.id, item)


@app.on_callback_query(filters.regex(r"^s:(\w+):(chat|github|private)$") & owner)
async def pick_target(client, cb):
    token, choice = cb.matches[0].group(1, 2)
    item = state.stash.pop(token, None)
    if item is None:
        return await cb.answer("این منو منقضی شده، دوباره بفرست.", show_alert=True)
    await cb.answer()
    try:
        await cb.message.delete()
    except Exception:
        pass
    item.dest, item.repo, _ = target(choice)
    await jobs.submit_single(client, cb.message.chat.id, item)
