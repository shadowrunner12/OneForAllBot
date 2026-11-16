import logging
import shutil
import sys

import config


def main():
    missing = config.missing()
    if missing:
        sys.exit("این متغیرها در فایل .env تنظیم نشدن: " + ", ".join(missing))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    # فقط پوشه‌های کاری نیمه‌تمام دفعه‌ی قبل پاک می‌شن، نه کل WORK_DIR (ممکنه یه دیسک مستقل باشه)
    for leftover in config.WORK_DIR.iterdir():
        if leftover.is_dir() and leftover.name.split("_")[0] in ("job", "batch", "pl"):
            shutil.rmtree(leftover, ignore_errors=True)
    config.COOKIES_DIR.mkdir(exist_ok=True)

    from core import app, repos
    import handlers  # noqa: F401  (ثبت هندلرها)

    if config.PUBLIC_URL:
        from services import web

        web.start(repos)

    app.run()


if __name__ == "__main__":
    main()
