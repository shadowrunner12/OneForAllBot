from utils.names import code, short

COOKIE_STEPS = (
    "۱) توی مرورگر یه پنجره **Incognito** باز کن و وارد حساب شو (بهتره یه اکانت جدا باشه)\n"
    "۲) افزونه **Get cookies.txt LOCALLY** رو نصب کن و از همون پنجره Export بزن\n"
    "۳) پنجره رو ببند و فایل رو همین‌جا برام بفرست؛ خودم ذخیره‌ش می‌کنم (به گیت‌هاب آپلود نمی‌شه)"
)


def explain(err):
    """خطای خام ابزارها را به یک پیام قابل‌فهم فارسی تبدیل می‌کند."""
    from services.ytdlp import cookie_file

    raw = str(err)
    low = raw.lower()
    tail = f"\n\n`{code(short(raw, 220))}`"

    if "sign in to confirm" in low and "bot" in low:
        if cookie_file("youtube"):
            return ("🤖 **یوتیوب کوکی فعلی رو قبول نکرد**\nکوکی منقضی یا نامعتبره، دوباره بگیرش:\n"
                    + COOKIE_STEPS + tail)
        return ("🤖 **یوتیوب IP سرور رو ربات تشخیص داد و کوکی می‌خواد**\n" + COOKIE_STEPS + tail)
    if "confirm your age" in low or "age-restricted" in low:
        return "🔞 **این ویدیو محدودیت سنی داره**؛ بدون کوکی حساب واردشده دانلود نمی‌شه. /cookies" + tail
    if "private video" in low or "members-only" in low:
        return "🔒 **این ویدیو خصوصیه** یا فقط برای اعضاست." + tail
    if "video unavailable" in low or "has been removed" in low:
        return "🚫 **این ویدیو در دسترس نیست** (حذف شده یا در منطقه سرور محدوده)." + tail
    if "requested format is not available" in low:
        return "🎞 **کیفیت انتخاب‌شده موجود نیست.** یه کیفیت دیگه امتحان کن یا `/upgrade` بزن." + tail
    if "login required" in low or "rate-limit reached" in low:
        return "🔑 **این سایت لاگین می‌خواد.** کوکی بده: `/cookies instagram` (یا twitter)" + tail
    if "429" in low or "too many requests" in low:
        return "⏱ **سایت درخواست‌ها رو محدود کرده.** چند دقیقه صبر کن و دوباره امتحان کن." + tail
    if "unsupported url" in low:
        return "❓ **این لینک پشتیبانی نمی‌شه.**" + tail
    if "no space left" in low:
        return "💾 **فضای دیسک سرور تموم شده.**" + tail
    if "ffmpeg" in low and "not found" in low:
        return "🛠 **ffmpeg نصب نیست.** `sudo apt install ffmpeg`" + tail
    return f"`{code(short(raw, 400))}`"
