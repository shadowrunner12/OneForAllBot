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
    shutil.rmtree(config.WORK_DIR, ignore_errors=True)
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    config.COOKIES_DIR.mkdir(exist_ok=True)

    from core import app
    import handlers  # noqa: F401  (ثبت هندلرها)

    app.run()


if __name__ == "__main__":
    main()
