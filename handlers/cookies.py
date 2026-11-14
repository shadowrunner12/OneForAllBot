import os
import time

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

import config
from core import app, owner, state
from services import ytdlp
from state import Item
from utils.errors import COOKIE_STEPS
from utils.names import code

DOMAINS = {
    "youtube": ("youtube.com",),
    "instagram": ("instagram.com",),
    "twitter": ("twitter.com", "x.com"),
    "soundcloud": ("soundcloud.com",),
}
LABELS = {"youtube": "یوتیوب", "instagram": "اینستاگرام", "twitter": "توییتر / X", "soundcloud": "ساندکلاد"}
YT_LOGIN = {"SID", "SAPISID", "__Secure-3PSID", "LOGIN_INFO"}
MAX_SIZE = 2 * 1024 * 1024


def parse_cookies(raw):
    """برمی‌گرداند: (تعداد کوکی، مجموعه نام‌ها، مجموعه دامنه‌ها)"""
    names, domains, count = set(), set(), 0
    for line in raw.decode("utf-8", "ignore").splitlines():
        line = line.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            count += 1
            domains.add(parts[0].lstrip(".").lower())
            names.add(parts[5])
    return count, names, domains


def platforms_in(domains):
    found = []
    for platform, hosts in DOMAINS.items():
        if any(d == h or d.endswith("." + h) for d in domains for h in hosts):
            found.append(platform)
    return found


def cookie_status():
    lines = []
    for platform in ytdlp.COOKIE_PLATFORMS:
        path = ytdlp.cookie_file(platform)
        if path:
            days = int((time.time() - path.stat().st_mtime) // 86400)
            age = "امروز" if days == 0 else f"{days} روز پیش"
            lines.append(f"✅ {LABELS[platform]} · ذخیره‌شده {age}")
        else:
            lines.append(f"▫️ {LABELS[platform]} · ندارد")
    return "\n".join(lines)


def cookie_help():
    return (
        "🍪 **مدیریت کوکی‌ها**\n\n"
        f"{cookie_status()}\n\n"
        "**چطور کوکی بدم؟**\n"
        f"{COOKIE_STEPS}\n\n"
        "فایل `cookies.txt` رو مستقیم برام بفرست؛ نوعش (یوتیوب، اینستاگرام...) رو خودم تشخیص می‌دم "
        "و هیچ‌وقت به گیت‌هاب آپلود نمی‌شه."
    )


async def _store(client, chat_id, platform, raw, count, names, source=None):
    config.COOKIES_DIR.mkdir(exist_ok=True)
    path = config.COOKIES_DIR / f"{platform}.txt"
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

    warn = ""
    if platform == "youtube" and not (names & YT_LOGIN):
        warn = "\n\n⚠️ توی این فایل کوکی ورود به حساب (مثل `SID`) نیست؛ احتمالاً لاگین نبودی و یوتیوب قبولش نمی‌کنه."
    cleaned = ""
    if source is not None:
        try:
            await source.delete()
            cleaned = "\n🧹 پیام فایل از چت پاک شد تا کوکی‌هات جایی نمونه."
        except Exception:
            pass
    await client.send_message(
        chat_id, f"✅ **کوکی {LABELS[platform]} ذخیره شد**\n🍪 {count} کوکی{warn}{cleaned}"
    )


async def intercept(client, message):
    """اگر فایل ارسالی کوکی بود، ذخیره‌اش می‌کند (و آپلود نمی‌شود). True یعنی پیام مصرف شد."""
    doc = message.document
    if not doc or (doc.file_size or 0) > MAX_SIZE:
        return False
    name = (doc.file_name or "").lower()
    cookie_named = "cookie" in name
    if not (cookie_named or name.endswith(".txt")):
        return False

    data = await message.download(in_memory=True)
    raw = data.getvalue() if data is not None else b""
    count, names, domains = parse_cookies(raw)

    if not count:
        if not cookie_named:
            return False
        token = state.keep({"msg": message})
        await message.reply_text(
            "⚠️ **این فایل فرمت cookies.txt (Netscape) نداره.**\n"
            "با افزونه‌ی Get cookies.txt LOCALLY دوباره Export بگیر.",
            reply_markup=Markup([[Btn("📤 به‌عنوان فایل عادی آپلود کن", callback_data=f"ck:{token}:upload")]]),
        )
        return True

    found = platforms_in(domains)
    if len(found) == 1:
        await _store(client, message.chat.id, found[0], raw, count, names, source=message)
        return True

    token = state.keep({"msg": message, "raw": raw, "count": count, "names": names})
    rows = [[Btn(LABELS[p], callback_data=f"ck:{token}:{p}")] for p in ytdlp.COOKIE_PLATFORMS]
    rows.append([Btn("📤 آپلود به‌عنوان فایل عادی", callback_data=f"ck:{token}:upload")])
    await message.reply_text(
        f"🍪 **فایل کوکی شناسایی شد** ({count} کوکی)\nبرای کدوم سایت ذخیره‌اش کنم؟",
        reply_markup=Markup(rows),
    )
    return True


@app.on_callback_query(filters.regex(r"^ck:(\w+):(\w+)$") & owner)
async def cookie_choice(client, cb):
    token, choice = cb.matches[0].group(1), cb.matches[0].group(2)
    data = state.stash.pop(token, None)
    if not data:
        return await cb.answer("این گزینه منقضی شده، فایل رو دوباره بفرست.", show_alert=True)
    await cb.answer()
    chat_id = cb.message.chat.id
    try:
        await cb.message.delete()
    except Exception:
        pass

    if choice == "upload":
        from handlers.inbound import tg_item
        from jobs import submit_single

        return await submit_single(client, chat_id, tg_item(data["msg"]))
    if choice in ytdlp.COOKIE_PLATFORMS:
        await _store(client, chat_id, choice, data["raw"], data["count"], data["names"], source=data["msg"])


@app.on_message(filters.command("cookies") & owner)
async def cookies_cmd(client, message):
    platform = message.command[1].lower() if len(message.command) > 1 else ""
    reply = message.reply_to_message
    if platform in ytdlp.COOKIE_PLATFORMS and reply and reply.document:
        data = await reply.download(in_memory=True)
        raw = data.getvalue()
        count, names, _ = parse_cookies(raw)
        if not count:
            return await message.reply_text("⚠️ این فایل فرمت cookies.txt (Netscape) نداره.")
        return await _store(client, message.chat.id, platform, raw, count, names, source=reply)
    await message.reply_text(cookie_help())
