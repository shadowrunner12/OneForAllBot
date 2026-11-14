from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from core import app, gh, owner, state
from ui import manage_kb
from utils.names import code, human_size


def render(rel):
    title = rel.get("name") or rel["tag_name"]
    page = rel.get("html_url", "")
    assets = rel.get("assets", [])
    rel_id = rel["id"]

    if len(assets) == 1:
        a = assets[0]
        text = (
            f"📄 **{code(title)}**\n"
            f"📦 حجم: `{human_size(a['size'])}` | 📥 دانلود: `{a.get('download_count', 0)} بار`\n"
            f"🔗 `{a['browser_download_url']}`\n"
            f"🏛 [صفحه ریلیز]({page})"
        )
        return text, manage_kb(a["browser_download_url"], rel_id, a["id"], page)

    if assets:
        lines = [f"📚 **{code(title)}** ({len(assets)} فایل):"]
        rows = []
        for i, a in enumerate(assets, 1):
            lines.append(
                f"{i}. `{code(a['name'])}` (`{human_size(a['size'])}` | 📥 {a.get('download_count', 0)})\n"
                f"🔗 `{a['browser_download_url']}`"
            )
            if i <= 5 and a["name"] != "links.txt":
                rows.append([Btn(f"✏️ تغییر نام فایل {i}", callback_data=f"ren_{a['id']}")])
        lines.append(f"\n🏛 [صفحه ریلیز]({page})")
        rows.append([Btn("🗑 حذف کل این Release", callback_data=f"del_{rel_id}")])
        return "\n".join(lines), Markup(rows)

    return f"📄 **{code(title)}** (بدون فایل)", Markup([[Btn("🗑 حذف", callback_data=f"del_{rel_id}")]])


async def send_files(client, chat_id):
    try:
        releases = await gh.list_releases(10)
    except Exception as e:
        return await client.send_message(chat_id, f"❌ {e}")
    if not releases:
        return await client.send_message(chat_id, "📭 هیچ فایلی در Releases نیست.")
    for rel in releases:
        text, kb = render(rel)
        await client.send_message(chat_id, text, reply_markup=kb)


@app.on_message(filters.command("files") & owner)
async def files_cmd(client, message):
    await send_files(client, message.chat.id)


@app.on_message(filters.command("search") & owner)
async def search_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ عبارت رو بنویس. مثال: `/search movie`")
    query = " ".join(message.command[1:]).lower()
    try:
        releases = await gh.list_releases(100)
    except Exception as e:
        return await message.reply_text(f"❌ {e}")
    found = [
        r for r in releases
        if query in (r.get("name") or r["tag_name"]).lower()
        or any(query in a["name"].lower() for a in r.get("assets", []))
    ]
    if not found:
        return await message.reply_text(f"📭 چیزی با `{code(query)}` پیدا نشد.")
    for rel in found[:10]:
        text, kb = render(rel)
        await message.reply_text(text, reply_markup=kb)


@app.on_callback_query(filters.regex(r"^cancel_task$") & owner)
async def cancel_cb(client, cb):
    if state.lock.locked():
        state.cancel = True
        await cb.answer("🛑 درخواست لغو ثبت شد...", show_alert=True)
    else:
        await cb.answer("عملیاتی در جریان نیست.", show_alert=True)


@app.on_callback_query(filters.regex(r"^ren_(\d+)$") & owner)
async def rename_cb(client, cb):
    state.rename_asset = int(cb.matches[0].group(1))
    await cb.answer()
    await cb.message.reply_text(
        "✏️ **نام جدید فایل رو (با پسوند) بفرست.**\n(برای انصراف /cancel)\n"
        "توجه: گیت‌هاب فقط حروف انگلیسی، عدد و `._-` رو نگه می‌داره."
    )


@app.on_callback_query(filters.regex(r"^del_(\d+)$") & owner)
async def delete_cb(client, cb):
    await cb.answer("در حال حذف...")
    try:
        await gh.delete_release(int(cb.matches[0].group(1)))
    except Exception as e:
        return await cb.answer(f"❌ {e}", show_alert=True)
    await cb.message.edit_text("🗑 **این Release کامل از گیت‌هاب حذف شد.**")
