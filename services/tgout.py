import config
from services import media
from utils.files import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT


async def send_file(client, chat_id, path, caption, progress, as_audio=False):
    ext = path.suffix.lower()
    caption = caption[:1024]

    if ext in IMAGE_EXT and path.stat().st_size <= config.PHOTO_LIMIT:
        return await client.send_photo(chat_id, str(path), caption=caption, progress=progress)

    if ext in AUDIO_EXT and as_audio:
        return await client.send_audio(chat_id, str(path), caption=caption, progress=progress)

    if ext in VIDEO_EXT:
        info = await media.probe(path)
        thumb = await media.thumbnail(path, path.with_suffix(".thumb.jpg"))
        try:
            return await client.send_video(
                chat_id, str(path), caption=caption,
                duration=int(info["duration"]), width=info["width"], height=info["height"],
                thumb=str(thumb) if thumb else None,
                supports_streaming=True, no_sound=False, progress=progress,
            )
        finally:
            if thumb:
                thumb.unlink(missing_ok=True)

    return await client.send_document(chat_id, str(path), caption=caption, progress=progress)


async def send_gif(client, chat_id, path, caption, progress):
    return await client.send_animation(chat_id, str(path), caption=caption[:1024], progress=progress)
