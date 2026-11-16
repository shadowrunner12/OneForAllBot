import io

from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

import config
from core import app, owner, repos
from services import links
from utils.names import code, human_size

SHORT_LIVED = "فقط چند دقیقه (همین الان توی IDM یا مرورگر بزن)"


async def make_link(key, asset):
    """(لینک، مدت اعتبار) برای یک فایل. ریپوی عمومی لینک خودش رو داره."""
    if key == "public":
        return asset["browser_download_url"], "نامحدود"
    if links.enabled():
        return links.create(key, asset["id"], asset["name"]), f"{config.LINK_TTL_HOURS} ساعت"
    return await repos[key].signed_url(asset["id"]), SHORT_LIVED


@app.on_callback_query(filters.regex(r"^lk_(public|private)_(\d+)$") & owner)
async def link_one(client, cb):
    key, asset_id = cb.matches[0].group(1), int(cb.matches[0].group(2))
    try:
        asset = await repos[key].asset(asset_id)
        url, validity = await make_link(key, asset)
    except Exception as e:
        return await cb.answer(f"❌ {e}", show_alert=True)
    await cb.answer()
    text = (
        f"🔗 **لینک دانلود** · اعتبار: {validity}\n"
        f"📄 `{code(asset['name'])}` · `{human_size(asset['size'])}`\n\n`{url}`"
    )
    if validity == SHORT_LIVED:
        text += "\n\n💡 برای لینک ماندگار، `PUBLIC_URL` رو تنظیم کن (`tgbot config`)."
    try:
        await client.send_message(cb.message.chat.id, text, reply_markup=Markup([[Btn("⬇️ باز کردن لینک", url=url)]]))
    except Exception:
        await client.send_message(cb.message.chat.id, text)


@app.on_callback_query(filters.regex(r"^lka_(public|private)_(\d+)$") & owner)
async def link_all(client, cb):
    key, release_id = cb.matches[0].group(1), int(cb.matches[0].group(2))
    try:
        assets = [a for a in await repos[key].release_assets(release_id) if a["name"] != "links.txt"]
        pairs = [(a, *await make_link(key, a)) for a in assets]
    except Exception as e:
        return await cb.answer(f"❌ {e}", show_alert=True)
    if not pairs:
        return await cb.answer("فایلی توی این Release نیست.", show_alert=True)
    await cb.answer()

    validity = pairs[0][2]
    lines = [f"{i}. `{code(a['name'])}`\n`{url}`" for i, (a, url, _) in enumerate(pairs, 1)]
    text = f"🔗 **لینک {len(pairs)} فایل** · اعتبار: {validity}\n\n" + "\n".join(lines)
    chat = cb.message.chat.id
    if len(text) <= 3800:
        return await client.send_message(chat, text)

    data = io.BytesIO("\n".join(url for _, url, _ in pairs).encode())
    data.name = "links.txt"
    await client.send_document(
        chat, data, caption=f"🔗 لینک {len(pairs)} فایل · اعتبار: {validity}\nتوی IDM: Tasks ← Import ← From text file"
    )
