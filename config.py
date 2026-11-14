import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID") or 0)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

DEFAULT_QUALITY = os.getenv("DEFAULT_QUALITY", "720")
YT_CLIENTS = os.getenv("YT_CLIENTS", "")
WORK_DIR = Path(os.getenv("WORK_DIR", "/tmp/tgbot"))
COOKIES_DIR = BASE_DIR / "cookies"

PART_SIZE_MB = 1900
PART_SIZE = PART_SIZE_MB * 1024 * 1024
CHAT_LIMIT = PART_SIZE
PHOTO_LIMIT = 10 * 1024 * 1024
GIF_MAX_SECONDS = 15
PLAYLIST_MAX = 20


def missing():
    required = {
        "API_ID": API_ID,
        "API_HASH": API_HASH,
        "BOT_TOKEN": BOT_TOKEN,
        "ADMIN_ID": ADMIN_ID,
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "GITHUB_REPO": GITHUB_REPO,
    }
    return [key for key, value in required.items() if not value]
