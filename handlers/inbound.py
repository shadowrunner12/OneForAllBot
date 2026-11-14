from datetime import datetime

from pyrogram import filters

from core import app, gh, owner, state
import jobs
from handlers import cookies, menus
from services import ytdlp
from state import Item
from utils.names import clean_name, code, human_size, with_ext


async def handle_url(client, message, url, custom):
    name = state.take_name(custom)

    if state.batch.active:
        state.batch.items.append(Item(kind="url", url=url, custom_name=name))
        return await message.reply_text(
            f"➕ **لینک شماره `{len(state.batch.items)}` به صف «{code(state.batch.title)}» اضافه شد!**\n"
            f"🔗 `{code(url)}`\n"
            f"📄 نام: `{code(clean_name(name)) if name else 'خودکار'}`\n\n"
            f"(مورد بعدی رو بفرست، با /pop حذفش کن یا برای شروع /done رو بزن)"
        )

    if ytdlp.platform_of(url) != "other":
        return await menus.offer(client, message, url, name)

    await jobs.submit_single(client, message.chat.id, Item(kind="url", url=url, custom_name=name))


def tg_item(message, custom=None):
    media = message.video or message.document or message.audio
    name = getattr(media, "file_name", None)
    if not name:
        ext = ".mp4" if message.video else (".mp3" if message.audio else ".bin")
        name = f"media_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    return Item(kind="tg", name=name, size=media.file_size or 0, custom_name=custom, msg=message)


@app.on_message((filters.video | filters.document | filters.audio) & owner)
async def on_media(client, message):
    if await cookies.intercept(client, message):
        return

    forwarded = bool(getattr(message, "forward_origin", None) or getattr(message, "forward_date", None))
    custom = state.take_name(None if forwarded else message.caption)
    item = tg_item(message, custom)

    if state.batch.active:
        state.batch.items.append(item)
        queue_size = sum(i.size for i in state.batch.items)
        shown = with_ext(custom, "") if custom else clean_name(item.name)
        return await message.reply_text(
            f"➕ **فایل شماره `{len(state.batch.items)}` به صف «{code(state.batch.title)}» اضافه شد**\n"
            f"📄 `{code(shown)}` · `{human_size(item.size)}`\n"
            f"📊 جمع حجم صف: `{human_size(queue_size)}`\n\n"
            f"مورد بعدی رو بفرست یا /done بزن (/pop آخرین مورد رو حذف می‌کنه)"
        )

    await jobs.submit_single(client, message.chat.id, item)


@app.on_message(filters.text & owner & ~filters.regex(r"^/"))
async def on_text(client, message):
    lines = [ln.strip() for ln in message.text.strip().splitlines() if ln.strip()]
    if not lines:
        return
    first = lines[0]

    # تغییر نام فایل روی گیت‌هاب
    if state.rename_asset and not first.startswith("http"):
        asset_id, state.rename_asset = state.rename_asset, None
        new_name = clean_name(first)
        try:
            data = await gh.rename_asset(asset_id, new_name)
        except Exception as e:
            return await message.reply_text(f"❌ {e}")
        return await message.reply_text(
            f"✅ **نام فایل عوض شد!**\n\n📄 **نام جدید:** `{code(data['name'])}`\n"
            f"🔗 **لینک جدید:**\n`{data['browser_download_url']}`"
        )

    # بازه پلی‌لیست
    if state.awaiting_range:
        match = menus.RANGE.match(first)
        if match:
            return await menus.apply_range(
                message, int(match.group(1)), int(match.group(2)) if match.group(2) else None
            )

    # لینک
    if first.startswith(("http://", "https://")):
        parts = first.split(maxsplit=1)
        custom = lines[1] if len(lines) > 1 else (parts[1] if len(parts) > 1 else None)
        return await handle_url(client, message, parts[0], custom)

    # تغییر نام حین دانلود
    if state.lock.locked():
        state.live_name = first
        return await message.reply_text(f"✏️ **نام فایل در حال دانلود عوض شد به:**\n`{code(clean_name(first))}`")

    # نام برای فایل/لینک بعدی
    state.pending_name = first
    await message.reply_text(
        f"📌 **نام `{code(clean_name(first))}` برای فایل/لینک بعدی ذخیره شد!**\n"
        f"حالا فایل یا لینک رو بفرست."
    )
