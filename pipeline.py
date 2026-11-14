import shutil
from datetime import datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

from pyrogram import StopTransmission

import config
from services import archive, fetchers, media, tgout, ytdlp
from state import Cancelled, Item
from ui import Btn, Markup, Outcome, release_outcome
from utils.errors import explain
from utils.files import IMAGE_EXT
from utils.names import clean_name, code, human_size, short, with_ext


class Runner:
    """یک کار کامل: دانلود ← نام‌گذاری ← (ZIP) ← ارسال در چت یا آپلود روی گیت‌هاب."""

    def __init__(self, client, state, gh, status):
        self.client = client
        self.state = state
        self.gh = gh
        self.status = status
        self.chat_id = status.msg.chat.id

    def _stop(self):
        return self.state.cancel

    def _check(self):
        if self.state.cancel:
            raise Cancelled()

    # ---------- دانلود ----------

    async def fetch(self, item, folder):
        folder.mkdir(parents=True, exist_ok=True)
        self.state.live_name = None
        hint = item.custom_name or item.name
        self.status.name = clean_name(hint) if hint else ""
        progress = self.status.transfer()

        if item.kind == "tg":
            await self.status.goto("download", "دانلود از تلگرام")
            result = await item.msg.download(file_name=str(folder / clean_name(item.name)), progress=progress)
            if self.state.cancel or not result:
                raise Cancelled()
            return Path(result)

        host = urlparse(item.url).netloc.lower()
        tick = partial(self.status.folder_tick(), folder)
        if "mega.nz" in host or "mega.co.nz" in host:
            await self.status.goto("download", "دانلود از Mega")
            return await fetchers.mega(item.url, folder, self._stop, tick)
        if "drive.google.com" in host:
            await self.status.goto("download", "دانلود از Google Drive")
            return await fetchers.gdrive(item.url, folder, self._stop, tick)

        platform = ytdlp.platform_of(item.url)
        if platform != "other":
            await self.status.goto("download", f"دانلود از {ytdlp.PLATFORM_LABELS.get(platform, platform)}")
            await self.status.note("🔎 در حال آماده‌سازی...")
            return await ytdlp.download(
                item.url, item.fmt or config.DEFAULT_QUALITY, folder,
                self._stop, progress, lambda text: self.status.note(text),
            )

        await self.status.goto("download", "دانلود از لینک")
        return await fetchers.direct(item.url, folder, progress)

    def apply_name(self, item, path):
        chosen = self.state.live_name or item.custom_name
        name = with_ext(chosen, path.suffix) if chosen else clean_name(path.name)
        target = path.with_name(name)
        if target != path:
            path.rename(target)
        return target

    async def get_file(self, item, folder):
        path = await self.fetch(item, folder)
        title = path.stem
        self.status.name = clean_name(path.name)
        path = self.apply_name(item, path)
        self.status.name = path.name
        await self.status.done(human_size(path.stat().st_size))
        return path, title

    # ---------- تحویل ----------

    async def process(self, item, folder, do_zip=False, password=None, context=None):
        keys = ["download"]
        if item.dest == "chat":
            if item.gif:
                keys.append("convert")
            keys.append("send")
        else:
            keys.append("upload")
        self.status.plan(*keys, context=context)

        path, title = await self.get_file(item, folder)
        note = ""
        if item.dest == "chat":
            outcome, note = await self.to_chat(item, path, title)
            if outcome:
                return outcome
            self.status.drop("send")
            self.status.drop("convert")
        return await self.to_github(path, folder, do_zip, password, note)

    async def to_chat(self, item, path, title):
        try:
            if item.gif and item.fmt != "audio" and path.suffix.lower() not in IMAGE_EXT:
                sent = await self._send_gif(path, title)
                if sent:
                    return sent, ""
                self.status.drop("convert")

            if path.stat().st_size > config.CHAT_LIMIT:
                return None, " (حجم فایل بیشتر از سقف چت بود)"

            await self.status.goto("send")
            await tgout.send_file(
                self.client, self.chat_id, path, title,
                self.status.transfer(), as_audio=item.fmt == "audio",
            )
            path.unlink(missing_ok=True)
            return Outcome("✅ **در چت ارسال شد**"), ""
        except (Cancelled, StopTransmission):
            raise
        except Exception as e:
            return None, f" (ارسال در چت نشد: {short(e, 100)})"

    async def _send_gif(self, path, title):
        await self.status.goto("convert")
        await self.status.note("🎞 در حال ساخت GIF...")
        try:
            gif, trimmed = await media.to_gif(path, config.GIF_MAX_SECONDS, self._stop)
        except Cancelled:
            raise
        except Exception:
            return None
        try:
            if gif.stat().st_size > config.CHAT_LIMIT:
                return None
            await self.status.done(human_size(gif.stat().st_size))
            await self.status.goto("send", "ارسال GIF در چت")
            await tgout.send_gif(self.client, self.chat_id, gif, title, self.status.transfer())
        finally:
            gif.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        note = f"\n(فقط {config.GIF_MAX_SECONDS} ثانیه اول تبدیل شد)" if trimmed else ""
        return Outcome(f"✅ **GIF در چت ارسال شد**{note}")

    async def _zip(self, paths, folder, name, password, split):
        await self.status.goto("zip")
        extra = [f"🔑 رمز: `{code(password)}`"] if password else []
        await self.status.note("📦 در حال ساخت آرشیو (بدون فشرده‌سازی، سریع)...", *extra)
        files = await archive.make_zip(paths, folder, name, password, split, self._stop)
        await self.status.done(f"{len(files)} پارت" if len(files) > 1 else human_size(files[0].stat().st_size))
        return files

    async def _upload_all(self, rel, files):
        await self.status.goto("upload")
        for i, f in enumerate(files, 1):
            note = f"🧩 پارت {i} از {len(files)}" if len(files) > 1 else ""
            await rel.upload(f, progress=self.status.transfer(note))
        await self.status.done(f"{len(files)} فایل" if len(files) > 1 else None)

    async def to_github(self, path, folder, do_zip, password, note=""):
        raw_size = path.stat().st_size
        split = raw_size > config.PART_SIZE
        files = [path]
        if do_zip or split:
            files = await self._zip([path], folder, path.name, password, split)

        await self.status.goto("upload")
        await self.status.note("⚙️ در حال ساخت Release در گیت‌هاب...")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"{path.name} | {now}"
        body = f"Uploaded via Telegram bot on {now}\nName: `{path.name}` ({human_size(raw_size)})"
        async with self.gh.release(title, body) as rel:
            await self._upload_all(rel, files)
            links = await rel.upload_links(folder)
        return release_outcome(title, rel, links, raw_size, password if do_zip else None, note)

    # ---------- گروهی ----------

    async def batch(self, items, title, zip_mode, password, folder):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        release_title = f"📦 {title} | {now}"
        body = f"Batch release created on {now}\nTitle: {title} | Items: {len(items)}"
        failed = []
        total = 0
        count = len(items)

        if zip_mode:
            paths = []
            for i, item in enumerate(items, 1):
                self._check()
                self.status.plan("download", context=f"📦 {title} · آیتم {i} از {count}")
                item_dir = folder / f"item_{i}"
                try:
                    path, _ = await self.get_file(item, item_dir)
                    dest = folder / f"{i:02d}_{path.name}"
                    shutil.move(str(path), str(dest))
                    paths.append(dest)
                    total += dest.stat().st_size
                except (Cancelled, StopTransmission):
                    raise
                except Exception as e:
                    failed.append(f"آیتم {i}: {short(e, 120)}")
                finally:
                    shutil.rmtree(item_dir, ignore_errors=True)
            if not paths:
                raise RuntimeError("هیچ‌کدام از آیتم‌ها قابل دانلود نبودند:\n" + "\n".join(failed))

            self.status.plan("zip", "upload", context=f"📦 {title}")
            files = await self._zip(paths, folder, title, password, False)
            async with self.gh.release(release_title, body) as rel:
                await self._upload_all(rel, files)
                links = await rel.upload_links(folder)
            return release_outcome(release_title, rel, links, total, password, failed=failed)

        async with self.gh.release(release_title, body) as rel:
            for i, item in enumerate(items, 1):
                self._check()
                self.status.plan("download", "upload", context=f"📦 {title} · آیتم {i} از {count}")
                item_dir = folder / f"item_{i}"
                try:
                    path, _ = await self.get_file(item, item_dir)
                    size = path.stat().st_size
                    total += size
                    files = [path]
                    if size > config.PART_SIZE:
                        files = await self._zip([path], item_dir, path.name, password, True)
                    await self._upload_all(rel, files)
                except (Cancelled, StopTransmission):
                    raise
                except Exception as e:
                    failed.append(f"آیتم {i}: {short(e, 120)}")
                finally:
                    shutil.rmtree(item_dir, ignore_errors=True)
            if not rel.assets:
                raise RuntimeError("هیچ‌کدام از آیتم‌ها آپلود نشدند:\n" + "\n".join(failed))
            links = await rel.upload_links(folder)
        return release_outcome(release_title, rel, links, total, failed=failed)

    # ---------- پلی‌لیست ----------

    async def playlist(self, entries, fmt, dest, folder):
        total = len(entries)
        done = 0
        for i, entry in enumerate(entries, 1):
            self._check()
            item = Item(
                kind="url", url=f"https://www.youtube.com/watch?v={entry['id']}",
                name=entry["title"], fmt=fmt, dest=dest,
            )
            item_dir = folder / f"v{i}"
            try:
                outcome = await self.process(item, item_dir, context=f"🎬 پلی‌لیست · ویدیو {i} از {total}")
                await self.client.send_message(
                    self.chat_id, f"**({i}/{total})** {outcome.text}", reply_markup=outcome.kb
                )
                done += 1
            except (Cancelled, StopTransmission):
                raise
            except Exception as e:
                retry = Markup([[Btn("🔄 دوباره امتحان کن", callback_data=f"r:{entry['id']}:{fmt}:{dest}")]])
                await self.client.send_message(
                    self.chat_id, f"❌ **({i}/{total}) خطا**\n{explain(e)}", reply_markup=retry
                )
            finally:
                shutil.rmtree(item_dir, ignore_errors=True)
        await self.status.set(f"✅ **پایان پلی‌لیست**\n{done} از {total} ویدیو با موفقیت انجام شد.")
