import os
import re
import time
import unicodedata

_EXT = re.compile(r"^\.[A-Za-z0-9]{1,5}$")


def clean_name(name):
    name = re.sub(r'[\\/*?:"<>|\s]+', "_", name.strip())
    return name.strip("_") or f"file_{int(time.time())}"


def with_ext(text, ext):
    name = clean_name(text)
    if ext and not _EXT.match(os.path.splitext(name)[1]):
        name += ext
    return name


def ascii_name(filename):
    stem, ext = os.path.splitext(filename)
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    stem = re.sub(r"\.{2,}", ".", stem)
    stem = re.sub(r"_+", "_", stem).strip("_.") or "file"
    if not stem[0].isalnum():
        stem = "f_" + stem
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext)
    return stem + ext


def human_size(num):
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TB"


def code(text):
    return str(text).replace("`", "'")


def short(err, limit=300):
    return str(err).strip()[-limit:]
