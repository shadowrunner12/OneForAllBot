import json
import secrets
import threading
import time
from urllib.parse import quote

import config

_lock = threading.Lock()
_file = config.BASE_DIR / "data" / "links.json"


def enabled():
    return bool(config.PUBLIC_URL)


def _load():
    try:
        return json.loads(_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data):
    _file.parent.mkdir(parents=True, exist_ok=True)
    tmp = _file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(_file)


def create(repo, asset_id, name):
    """یک لینک ماندگار (با توکن تصادفی) برای فایل ریپوی خصوصی می‌سازد."""
    ttl = config.LINK_TTL_HOURS * 3600
    now = time.time()
    with _lock:
        data = {k: v for k, v in _load().items() if not v["exp"] or v["exp"] > now}
        token = secrets.token_urlsafe(24)
        data[token] = {"repo": repo, "asset": asset_id, "exp": now + ttl if ttl else 0}
        _save(data)
    return f"{config.PUBLIC_URL}/d/{token}/{quote(name)}"


def lookup(token):
    """برمی‌گرداند: dict، یا None اگر نیست، یا "expired"."""
    with _lock:
        entry = _load().get(token)
    if entry is None:
        return None
    if entry["exp"] and entry["exp"] < time.time():
        return "expired"
    return entry
