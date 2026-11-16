import asyncio
import os
import shutil
import sys
import time
from datetime import datetime

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

import config
import jobs
from core import app, owner, repos, state
from handlers import cookies, manage
from services import ytdlp
from services.proc import run
from state import Batch
from ui import Status, cancel_kb, fmt_time
from utils.names import clean_name, code, human_size, short

WELCOME = (
    "👋 **سلام! من ربات دانلود و آپلودم**\n\n"
    "فقط کافیه یه لینک یا فایل بفرستی:\n\n"
    "🎬 **لینک ویدیو** (یوتیوب، اینستاگرام، توییتر، تیک‌تاک...)\n"
    "     ← منوی کیفیت، بعد چت / گیت‌هاب / GIF\n"
    "☁️ **لینک مستقیم، Mega، Google Drive یا فایل**\n"
    "     ← آپلود روی گیت‌هاب (بالای ۱۹۰۰MB خودکار پارت‌پارت)\n"
    "📦 **/batch** ← چند مورد در یک Release\n"
    "🍪 **فایل cookies.txt** ← خودم ذخیره‌ش می‌کنم، آپلود نمی‌شه"
)

HELP = (
    "📖 **راهنمای دستورها**\n\n"
    "**ارسال**\n"
    "• لینک یا فایل بفرست؛ نوعش رو خودم تشخیص می‌دم\n"
    "• لینک پلی‌لیست یوتیوب ← بازه رو بنویس (مثلاً `1-10`)\n"
    "• اگه ریپوی خصوصی تنظیم کرده باشی، موقع آپلود می‌پرسه عمومی یا خصوصی\n\n"
    "**گروهی**\n"
    "• `/batch نام` ← هر مورد جدا در یک Release\n"
    "• `/batch zip` ، `/batch zip نام` ، `/batch zip 1234 نام` ، `/batch zip -p 1234` ← همه در یک ZIP\n"
    "• `/pop` حذف آخرین مورد · `/done` شروع پردازش\n\n"
    "**زیپ تکی**\n"
    "• `/zip` یا `/zip 1234` ← فایل/لینک بعدی زیپ می‌شه\n\n"
    "**تغییر نام**\n"
    "• قبل از ارسال · حین دانلود · خط دوم لینک · کپشن فایل · دکمه‌ی بعد از آپلود\n\n"
    "**مدیریت**\n"
    "• `/files` ۱۰ Release آخر · `/search کلمه`\n"
    "• `/cookies` وضعیت کوکی‌ها و راهنما\n"
    "• `/status` وضعیت سرور · `/cancel` لغو و پاک‌کردن صف\n"
    "• `/upgrade` آپدیت yt-dlp · `/update` آپدیت ربات از گیت‌هاب"
)


def start_kb():
    return Markup([
        [Btn("📊 وضعیت سرور", callback_data="m:status"), Btn("📂 فایل‌های من", callback_data="m:files")],
        [Btn("🍪 کوکی‌ها", callback_data="m:cookies"), Btn("📖 راهنما", callback_data="m:help")],
    ])


def parse_batch_args(args):
    """(zip؟، رمز، نام) — شکل‌های مجاز: [نام] | zip | zip -p رمز [نام] | zip رمز نام | zip نام"""
    default = f"Pack_{datetime.now().strftime('%Y%m%d_%H%M')}"
    if not args:
        return False, None, default
    if args[0].lower() != "zip":
        return False, None, clean_name(" ".join(args))

    rest = args[1:]
    if not rest:
        return True, None, default
    if rest[0] in ("-p", "--pass") and len(rest) >= 2:
        name = clean_name(" ".join(rest[2:])) if len(rest) > 2 else default
        return True, rest[1], name
    if len(rest) == 1:
        return True, None, clean_name(rest[0])
    return True, rest[0], clean_name(" ".join(rest[1:]))


async def _out(*cmd, cwd=None):
    code_, out, err = await run(cmd, cwd=cwd)
    return code_, (out or err).strip()


async def status_text():
    usage = shutil.disk_usage(config.WORK_DIR if config.WORK_DIR.exists() else "/")
    _, ytv = await _out(sys.executable, "-m", "yt_dlp", "--version")
    _, rev = await _out("git", "rev-parse", "--short", "HEAD", cwd=config.BASE_DIR)
    tools = []
    for name, binary in (("ffmpeg", "ffmpeg"), ("7z", "7z"), ("megadl", "megadl"), ("deno", "deno")):
        tools.append(f"{'✅' if shutil.which(binary) else '❌'} {name}")
    queue = "🔵 در حال اجرا" if state.lock.locked() else "🟢 آزاد"
    if state.batch.active:
        queue += f" · صف گروهی: {len(state.batch.items)} مورد"
    return (
        "📊 **وضعیت سرور**\n\n"
        f"⚙️ صف کار: {queue}\n"
        f"💾 دیسک: `{human_size(usage.free)}` آزاد از `{human_size(usage.total)}`\n"
        f"⏱ مدت روشن بودن ربات: `{fmt_time(time.time() - state.started)}`\n"
        f"🎬 yt-dlp: `{code(ytv[:20])}`\n"
        f"🔖 نسخه‌ی کد: `{code(rev[:12]) if rev else 'نامشخص'}`\n\n"
        f"🧰 ابزارها: {' · '.join(tools)}\n\n"
        f"🍪 **کوکی‌ها**\n{cookies.cookie_status()}"
    )


@app.on_message(filters.command(["start", "help"]) & owner)
async def start_cmd(client, message):
    if message.command[0] == "help":
        return await message.reply_text(HELP)
    await message.reply_text(WELCOME, reply_markup=start_kb())


@app.on_message(filters.command("status") & owner)
async def status_cmd(client, message):
    await message.reply_text(await status_text())


@app.on_callback_query(filters.regex(r"^m:(\w+)$") & owner)
async def menu_cb(client, cb):
    which = cb.matches[0].group(1)
    chat_id = cb.message.chat.id
    await cb.answer()
    if which == "status":
        await client.send_message(chat_id, await status_text())
    elif which == "files":
        await manage.files_menu(client, chat_id)
    elif which == "cookies":
        await client.send_message(chat_id, cookies.cookie_help())
    elif which == "help":
        await client.send_message(chat_id, HELP)


@app.on_message(filters.command("batch") & owner)
async def batch_cmd(client, message):
    zip_mode, password, title = parse_batch_args(message.command[1:])
    state.pending_name = None
    state.batch = Batch(active=True, zip_mode=zip_mode, password=password, title=title)

    mode = "🗜 همه در یک آرشیو ZIP (حالت Store)" if zip_mode else "📂 هر مورد جدا، بدون فشرده‌سازی"
    pw = f"\n🔑 رمز: `{code(password)}`" if password else ""
    await message.reply_text(
        f"📚 **صف گروهی فعال شد**\n\n"
        f"🏷 نام: `{code(title)}`\n⚙️ حالت: {mode}{pw}\n\n"
        f"فایل‌ها و لینک‌ها رو بفرست، آخرش /done رو بزن.\n"
        f"(/pop آخرین مورد رو حذف می‌کنه · /cancel همه رو لغو می‌کنه)"
    )


@app.on_message(filters.command("pop") & owner)
async def pop_cmd(client, message):
    if not state.batch.active or not state.batch.items:
        return await message.reply_text("ℹ️ صف گروهی خالیه.")
    removed = state.batch.items.pop()
    label = removed.custom_name or removed.name or removed.url or "آیتم"
    await message.reply_text(f"🗑 `{code(label)}` از صف حذف شد · باقی‌مانده: `{len(state.batch.items)}`")


@app.on_message(filters.command("done") & owner)
async def done_cmd(client, message):
    batch = state.batch
    if not batch.active:
        return await message.reply_text("ℹ️ حالت گروهی فعال نیست. با /batch شروع کن.")
    items, title, zip_mode, password = list(batch.items), batch.title, batch.zip_mode, batch.password
    state.batch = Batch()
    state.pending_name = None
    if not items:
        return await message.reply_text("📭 صف خالی بود و بسته شد.")

    known = sum(i.size for i in items)
    parts = max(1, known // config.PART_SIZE + 1) if known else "نامشخص"
    preview = (
        f"📊 **صف «{code(title)}»**\n\n"
        f"🔢 تعداد: `{len(items)}`\n"
        f"📦 حجم فایل‌های تلگرامی: `{human_size(known)}`\n"
        f"🧩 پارت تخمینی: `{parts}` (سقف هر پارت `{config.PART_SIZE_MB}MB`)\n"
        f"⚙️ نوع: `{'ZIP یکپارچه' if zip_mode else 'هر مورد جدا در یک Release'}`\n\n"
        f"⏳ در صف انتظار..."
    )
    if "private" in repos:
        token = state.keep({"items": items, "title": title, "zip": zip_mode, "pwd": password})
        kb = Markup([[
            Btn("🌐 گیت‌هاب عمومی", callback_data=f"bt:{token}:public"),
            Btn("🔒 گیت‌هاب خصوصی", callback_data=f"bt:{token}:private"),
        ]])
        return await message.reply_text(
            preview.replace("⏳ در صف انتظار...", "📍 **روی کدوم ریپو آپلود بشه؟**"), reply_markup=kb
        )
    status = Status(client, await message.reply_text(preview, reply_markup=cancel_kb()), state)
    await jobs.submit_batch(client, status, items, title, zip_mode, password)


@app.on_callback_query(filters.regex(r"^bt:(\w+):(public|private)$") & owner)
async def batch_repo_cb(client, cb):
    token, repo = cb.matches[0].group(1, 2)
    data = state.stash.pop(token, None)
    if not data:
        return await cb.answer("منقضی شده؛ دوباره /batch بزن.", show_alert=True)
    await cb.answer()
    await cb.message.edit_text("⏳ **در صف انتظار...**", reply_markup=cancel_kb())
    status = Status(client, cb.message, state)
    await jobs.submit_batch(client, status, data["items"], data["title"], data["zip"], data["pwd"], repo)


@app.on_message(filters.command("zip") & owner)
async def zip_cmd(client, message):
    state.zip_next = True
    if len(message.command) >= 2:
        state.zip_password = message.command[1].strip()
        text = f"🔐 **زیپ با رمز `{code(state.zip_password)}` برای مورد بعدی فعال شد**"
    else:
        state.zip_password = None
        text = "🗜 **زیپ (بدون رمز) برای مورد بعدی فعال شد**\n(با رمز: `/zip 1234`)"
    await message.reply_text(text + "\nحالا فایل یا لینک رو بفرست.")


@app.on_message(filters.command("cancel") & owner)
async def cancel_cmd(client, message):
    state.reset_pending()
    if state.lock.locked():
        state.cancel = True
        await message.reply_text("🛑 درخواست لغو ثبت شد؛ عملیات در حال توقف و پاکسازیه...")
    else:
        await message.reply_text("ℹ️ همه‌ی وضعیت‌های موقت و صف گروهی پاک شد.")


@app.on_message(filters.command("url") & owner)
async def url_cmd(client, message):
    from handlers.inbound import handle_url

    lines = message.text.strip().splitlines()
    head = lines[0].split(maxsplit=2)
    if len(head) < 2:
        return await message.reply_text("⚠️ لینک رو کنار دستور بنویس: `/url https://...` (نام دلخواه در خط دوم)")
    custom = lines[1].strip() if len(lines) > 1 and lines[1].strip() else (head[2].strip() if len(head) > 2 else None)
    await handle_url(client, message, head[1].strip(), custom)


@app.on_message(filters.command("upgrade") & owner)
async def upgrade_cmd(client, message):
    status = await message.reply_text("🔄 **در حال آپدیت yt-dlp...**")
    code_, text = await _out(sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]")
    last = text.splitlines()[-1:] or [""]
    _, ytv = await _out(sys.executable, "-m", "yt_dlp", "--version")
    icon = "✅" if code_ == 0 else "❌"
    await status.edit_text(f"{icon} **آپدیت yt-dlp**\nنسخه‌ی فعلی: `{code(ytv[:20])}`\n`{code(short(last[0], 150))}`")


@app.on_message(filters.command("update") & owner)
async def update_cmd(client, message):
    status = await message.reply_text("🔄 **در حال بررسی آپدیت...**")
    base = config.BASE_DIR
    _, before = await _out("git", "rev-parse", "HEAD", cwd=base)
    code_, text = await _out("git", "pull", "--ff-only", cwd=base)
    if code_ != 0:
        return await status.edit_text(f"❌ **خطا در git pull**\n`{code(short(text))}`")
    _, after = await _out("git", "rev-parse", "HEAD", cwd=base)
    if before == after:
        return await status.edit_text("✅ **آخرین نسخه رو داری.** آپدیتی در کار نیست.")

    _, changes = await _out("git", "log", "--oneline", f"{before}..{after}", "-n", "8", cwd=base)
    await status.edit_text("📦 **آپدیت دانلود شد؛ در حال نصب نیازمندی‌ها...**")
    await _out(sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt", cwd=base)
    await status.edit_text(
        f"✅ **ربات آپدیت شد**\n\n`{code(changes)}`\n\n♻️ در حال ری‌استارت (چند ثانیه صبر کن)..."
    )
    await asyncio.sleep(1)
    os._exit(0)
