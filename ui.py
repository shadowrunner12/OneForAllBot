import re
import time
from dataclasses import dataclass, field

from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Markup

from utils.names import code, human_size

ORDER = ["download", "process", "convert", "zip", "upload", "send"]
TITLES = {
    "download": "دانلود",
    "process": "پردازش",
    "convert": "تبدیل به GIF",
    "zip": "ساخت آرشیو ZIP",
    "upload": "آپلود روی گیت‌هاب",
    "send": "ارسال در چت",
}
HINT = "\n\n💡 __برای تغییر نام، نام جدید رو همین‌جا بفرست__"


@dataclass
class Outcome:
    text: str
    kb: Markup | None = None


@dataclass
class Step:
    key: str
    label: str = ""
    state: str = "wait"          # wait | active | done
    lines: list = field(default_factory=list)
    summary: str = ""
    started: float = 0.0
    took: float = 0.0


def fmt_time(seconds):
    seconds = int(max(seconds, 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def bar(percent, width=14):
    filled = round(width * max(0, min(percent, 100)) / 100)
    return "▰" * filled + "▱" * (width - filled)


def cancel_kb():
    return Markup([[Btn("✖️ لغو عملیات", callback_data="cancel_task")]])


def manage_kb(link, release_id, asset_id, page_url):
    rows = [
        [Btn("⬇️ دانلود مستقیم", url=link), Btn("🌐 صفحه Release", url=page_url)],
    ]
    if asset_id:
        rows.append([
            Btn("✏️ تغییر نام", callback_data=f"ren_{asset_id}"),
            Btn("🗑 حذف", callback_data=f"del_{release_id}"),
        ])
    else:
        rows.append([Btn("🗑 حذف کل Release", callback_data=f"del_{release_id}")])
    return Markup(rows)


class Status:
    """کارت زنده‌ی وضعیت: مراحل کار (دانلود، ZIP، آپلود...) و پیشرفت مرحله‌ی فعلی."""

    def __init__(self, client, msg, state):
        self.client = client
        self.msg = msg
        self.state = state
        self.name = ""
        self.context = ""
        self.steps = []
        self.began = None
        self._last = 0.0

    # ---------- مراحل ----------

    @property
    def shown_name(self):
        return self.state.live_name or self.name or "خودکار"

    def elapsed(self):
        return time.monotonic() - self.began if self.began else 0

    def plan(self, *keys, context=None):
        self.steps = [Step(k) for k in keys]
        if context is not None:
            self.context = context
        if self.began is None:
            self.began = time.monotonic()

    def _active(self):
        return next((s for s in self.steps if s.state == "active"), None)

    def _close(self, step, summary=None):
        step.state = "done"
        step.took = time.monotonic() - step.started
        step.lines = []
        if summary is not None:
            step.summary = summary

    async def goto(self, key, label=None):
        current = self._active()
        if current and current.key == key:
            if label:
                current.label = label
            return
        if current:
            self._close(current)
        step = next((s for s in self.steps if s.key == key), None)
        if step is None:
            step = Step(key)
            position = len(self.steps)
            for i, s in enumerate(self.steps):
                if ORDER.index(s.key) > ORDER.index(key):
                    position = i
                    break
            self.steps.insert(position, step)
        step.state = "active"
        step.started = time.monotonic()
        step.lines = []
        if label:
            step.label = label
        await self.refresh(force=True)

    async def done(self, summary=None):
        current = self._active()
        if current:
            self._close(current, summary)
            await self.refresh(force=True)

    def drop(self, key):
        self.steps = [s for s in self.steps if s.key != key]

    async def note(self, *lines):
        current = self._active()
        if current:
            current.lines = list(lines)
            await self.refresh(force=True)

    # ---------- نمایش ----------

    def render(self):
        out = []
        if self.context:
            out.append(f"**{self.context}**")
        out.append(f"📄 `{code(self.shown_name)}`")
        out.append("")
        for step in self.steps:
            title = step.label or TITLES[step.key]
            if step.state == "done":
                extra = " · ".join(x for x in (step.summary, f"⏱ {fmt_time(step.took)}") if x)
                out.append(f"✅ {title} — {extra}")
            elif step.state == "active":
                out.append(f"🔵 **{title}**")
                out.extend(step.lines)
            else:
                out.append(f"⚪ {title}")
        return "\n".join(out)

    def _due(self):
        return time.monotonic() - self._last >= 3

    async def set(self, text, kb=None):
        self._last = time.monotonic()
        try:
            await self.msg.edit_text(text[:4096], reply_markup=kb)
        except Exception:
            pass

    async def refresh(self, force=False):
        if force or self._due():
            await self.set(self.render() + HINT, cancel_kb())

    # ---------- کال‌بک‌های پیشرفت ----------

    def transfer(self, note=""):
        """برای دانلود/آپلود با اندازه‌ی مشخص (تلگرام، لینک مستقیم، yt-dlp، گیت‌هاب)."""
        started = time.monotonic()

        async def cb(current, total, extra=None):
            if self.state.cancel:
                self.client.stop_transmission()
            if current != total and not self._due():
                return
            step = self._active()
            if not step:
                return
            speed = current / max(time.monotonic() - started, 0.001)
            lines = [note] if note else []
            if extra:
                lines.append(f"🏷 {code(extra)}")
            if total:
                percent = current * 100 / total
                eta = fmt_time((total - current) / speed) if speed else "—"
                lines += [
                    f"`{bar(percent)}` **{percent:.1f}%**",
                    f"📦 {human_size(current)} / {human_size(total)}",
                    f"🚀 {human_size(speed)}/s · ⏳ {eta}",
                ]
            else:
                lines += [f"📦 {human_size(current)} دریافت شد", f"🚀 {human_size(speed)}/s"]
            step.lines = lines
            await self.refresh(force=True)

        return cb

    def folder_tick(self, note=""):
        """برای ابزارهای بیرونی بدون گزارش پیشرفت؛ فقط حجم پوشه را نشان می‌دهد."""
        started = time.monotonic()

        async def tick(folder):
            if not self._due():
                return
            step = self._active()
            if not step:
                return
            try:
                size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
            except OSError:
                size = 0
            lines = [note] if note else []
            lines += [f"📦 {human_size(size)} دریافت شد", f"⏱ {fmt_time(time.monotonic() - started)} سپری شده"]
            step.lines = lines
            await self.refresh(force=True)

        return tick


# ---------- نتیجه‌ی نهایی ----------

def release_outcome(title, rel, links_url, size, password=None, note="", failed=None):
    pw = f"\n🔐 رمز آرشیو: `{code(password)}`" if password else ""
    failed_text = ""
    if failed:
        failed_text = "\n\n⚠️ **موارد ردشده**\n" + "\n".join(f"• `{code(f)}`" for f in failed)
    assets = rel.assets

    if len(assets) == 1:
        a = assets[0]
        text = (
            f"✅ **آپلود روی گیت‌هاب کامل شد**{note}\n\n"
            f"📄 `{code(a.name)}`\n"
            f"📦 `{human_size(a.size)}`{pw}\n\n"
            f"🔗 **لینک مستقیم** (برای کپی لمسش کن)\n`{a.url}`"
            f"{failed_text}"
        )
        return Outcome(text, manage_kb(a.url, rel.id, a.id, rel.page))

    lines = [
        f"✅ **{len(assets)} فایل روی گیت‌هاب آپلود شد**{note}",
        "",
        f"🏷 `{code(title)}`",
        f"📦 مجموع: `{human_size(size)}`{pw}",
    ]
    if any(re.search(r"\.zip(\.\d+)?$", a.name) for a in assets):
        lines += ["", "💡 همه پارت‌ها رو کنار هم بریز و فایل اول (`.zip` یا `.zip.001`) رو با WinRAR یا 7-Zip باز کن."]
    lines.append("")
    for i, a in enumerate(assets, 1):
        lines.append(f"**{i}.** `{code(a.name)}` · `{human_size(a.size)}`\n`{a.url}`")
    if links_url:
        lines += ["", f"📋 **لیست همه لینک‌ها (برای IDM)**\n`{links_url}`"]
    return Outcome("\n".join(lines) + failed_text, manage_kb(assets[0].url, rel.id, None, rel.page))
