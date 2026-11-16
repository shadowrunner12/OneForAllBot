from pyrogram import filters
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from core import app, owner, repos, state
from ui import manage_kb
from utils.names import code, human_size


def render(rel, key="public"):
    title = rel.get("name") or rel["tag_name"]
    mark = repos[key].mark
    page = rel.get("html_url", "")
    assets = rel.get("assets", [])
    rel_id = rel["id"]

    private = key == "private"
    if len(assets) == 1:
        a = assets[0]
        text = (
            f"{mark} **{code(title)}**\n"
            f"📦 حجم: `{human_size(a['size'])}` | 📥 دانلود: `{a.get('download_count', 0)} بار`\n"
            + ("" if private else f"🔗 `{a['browser_download_url']}`\n")
            + f"🏛 [صفحه ریلیز]({page})"
        )
        return text, manage_kb(a["browser_download_url"], rel_id, a["id"], page, key)

    if assets:
        lines = [f"{mark} **{code(title)}** ({len(assets)} فایل):"]
        rows = []
        for i, a in enumerate(assets, 1):
            lines.append(
                f"{i}. `{code(a['name'])}` (`{human_size(a['size'])}` | 📥 {a.get('download_count', 0)})"
                + ("" if private else f"\n🔗 `{a['browser_download_url']}`")
            )
            if i <= 5 and a["name"] != "links.txt":
                rows.append([Btn(f"✏️ تغییر نام فایل {i}", callback_data=f"ren_{key}_{a['id']}")])
        lines.append(f"\n🏛 [صفحه ریلیز]({page})")
        if private:
            rows.insert(0, [Btn("🔗 لینک همه‌ی پارت‌ها", callback_data=f"lka_{key}_{rel_id}")])
        rows.append([Btn("🗑 حذف کل این Release", callback_data=f"del_{key}_{rel_id}")])
        return "\n".join(lines), Markup(rows)

    return f"{mark} **{code(title)}** (بدون فایل)", Markup([[Btn("🗑 حذف", callback_data=f"del_{key}_{rel_id}")]])


async def send_files(client, chat_id, key="public"):
    try:
        releases = await repos[key].list_releases(10)
    except Exception as e:
        return await client.send_message(chat_id, f"❌ {e}")
    if not releases:
        return await client.send_message(chat_id, "📭 هیچ فایلی در Releases نیست.")
    for rel in releases:
        text, kb = render(rel, key)
        await client.send_message(chat_id, text, reply_markup=kb)


async def files_menu(client, chat_id):
    """اگه ریپوی خصوصی هم تنظیم شده، اول می‌پرسه کدوم ریپو."""
    if "private" not in repos:
        return await send_files(client, chat_id)
    kb = Markup([[Btn("🌐 عمومی", callback_data="fl:public"), Btn("🔒 خصوصی", callback_data="fl:private")]])
    await client.send_message(chat_id, "📂 **فایل‌های کدوم ریپو رو ببینم؟**", reply_markup=kb)


@app.on_message(filters.command("files") & owner)
async def files_cmd(client, message):
    await files_menu(client, message.chat.id)


@app.on_callback_query(filters.regex(r"^fl:(public|private)$") & owner)
async def files_cb(client, cb):
    await cb.answer()
    await send_files(client, cb.message.chat.id, cb.matches[0].group(1))


@app.on_message(filters.command("search") & owner)
async def search_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ عبارت رو بنویس. مثال: `/search movie`")
    query = " ".join(message.command[1:]).lower()
    found = []
    for key, gh in repos.items():
        try:
            releases = await gh.list_releases(100)
        except Exception as e:
            return await message.reply_text(f"❌ {e}")
        found += [
            (key, r) for r in releases
            if query in (r.get("name") or r["tag_name"]).lower()
            or any(query in a["name"].lower() for a in r.get("assets", []))
        ]
    if not found:
        return await message.reply_text(f"📭 چیزی با `{code(query)}` پیدا نشد.")
    for key, rel in found[:10]:
        text, kb = render(rel, key)
        await message.reply_text(text, reply_markup=kb)


@app.on_callback_query(filters.regex(r"^cancel_task$") & owner)
async def cancel_cb(client, cb):
    if state.lock.locked():
        state.cancel = True
        await cb.answer("🛑 درخواست لغو ثبت شد...", show_alert=True)
    else:
        await cb.answer("عملیاتی در جریان نیست.", show_alert=True)


@app.on_callback_query(filters.regex(r"^ren_(public|private)_(\d+)$") & owner)
async def rename_cb(client, cb):
    state.rename_asset = (cb.matches[0].group(1), int(cb.matches[0].group(2)))
    await cb.answer()
    await cb.message.reply_text(
        "✏️ **نام جدید فایل رو (با پسوند) بفرست.**\n(برای انصراف /cancel)\n"
        "توجه: گیت‌هاب فقط حروف انگلیسی، عدد و `._-` رو نگه می‌داره."
    )


@app.on_callback_query(filters.regex(r"^del_(public|private)_(\d+)$") & owner)
async def delete_cb(client, cb):
    await cb.answer("در حال حذف...")
    try:
        await repos[cb.matches[0].group(1)].delete_release(int(cb.matches[0].group(2)))
    except Exception as e:
        return await cb.answer(f"❌ {e}", show_alert=True)
    await cb.message.edit_text("🗑 **این Release کامل از گیت‌هاب حذف شد.**")
