from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import LinkPreviewOptions

import config
from services.github import GitHub
from state import State

app = Client(
    "tgbot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workdir=str(config.BASE_DIR),
    parse_mode=ParseMode.MARKDOWN,
    link_preview_options=LinkPreviewOptions(is_disabled=True),
    max_concurrent_transmissions=4,
)
state = State()
repos = {"public": GitHub(config.GITHUB_TOKEN, config.GITHUB_REPO)}
if config.GITHUB_REPO_PRIVATE:
    repos["private"] = GitHub(config.GITHUB_TOKEN, config.GITHUB_REPO_PRIVATE, "private")
owner = filters.user(config.ADMIN_ID)
