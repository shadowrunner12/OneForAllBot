import asyncio
import secrets
import time
from dataclasses import dataclass, field

from pyrogram.types import Message


class Cancelled(Exception):
    pass


@dataclass
class Item:
    kind: str                      # "tg" یا "url"
    name: str = ""
    size: int = 0
    custom_name: str | None = None
    msg: Message | None = None
    url: str | None = None
    fmt: str | None = None         # 720 / audio / best
    dest: str = "github"           # github یا chat
    repo: str = "public"           # public یا private
    gif: bool = False


@dataclass
class Menu:
    url: str
    title: str
    name: str | None = None
    entries: list = field(default_factory=list)


@dataclass
class Batch:
    active: bool = False
    zip_mode: bool = False
    password: str | None = None
    title: str = ""
    items: list = field(default_factory=list)


class State:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.cancel = False
        self.pending_name = None
        self.live_name = None
        self.zip_next = False
        self.zip_password = None
        self.rename_asset = None
        self.awaiting_range = None
        self.batch = Batch()
        self.menus = {}
        self.tasks = set()
        self.stash = {}
        self.started = time.time()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def take_name(self, explicit=None):
        if self.pending_name:
            name, self.pending_name = self.pending_name, None
            return name
        if explicit:
            first = explicit.strip().splitlines()[0].strip() if explicit.strip() else ""
            if first and not first.startswith(("/", "http")):
                return first
        return None

    def take_zip(self):
        do_zip, password = self.zip_next, self.zip_password
        self.zip_next, self.zip_password = False, None
        return do_zip, password

    def reset_pending(self):
        self.pending_name = None
        self.zip_next = False
        self.zip_password = None
        self.rename_asset = None
        self.awaiting_range = None
        self.batch = Batch()

    def remember(self, menu):
        token = secrets.token_hex(4)
        self.menus[token] = menu
        while len(self.menus) > 50:
            self.menus.pop(next(iter(self.menus)))
        return token

    def keep(self, obj):
        token = secrets.token_hex(4)
        self.stash[token] = obj
        while len(self.stash) > 20:
            self.stash.pop(next(iter(self.stash)))
        return token
