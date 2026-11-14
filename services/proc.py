import asyncio

from state import Cancelled


async def run(cmd, cwd=None, stop=None, tick=None):
    """اجرای یک ابزار خارجی؛ هر چند ثانیه وضعیت لغو را چک می‌کند."""
    proc = await asyncio.create_subprocess_exec(
        *[str(c) for c in cmd],
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    waiter = asyncio.ensure_future(proc.communicate())
    try:
        while True:
            done, _ = await asyncio.wait({waiter}, timeout=2)
            if done:
                break
            if stop and stop():
                raise Cancelled()
            if tick:
                await tick()
    finally:
        if proc.returncode is None:
            proc.kill()
    out, err = waiter.result()
    return proc.returncode, out.decode("utf-8", "ignore"), err.decode("utf-8", "ignore")


async def run_lines(cmd, cwd=None, stop=None, on_line=None, ignore=()):
    """اجرای ابزار با خواندن خط‌به‌خط خروجی (برای نمایش پیشرفت). برمی‌گرداند: (کد خروجی، آخرین خطوط)"""
    proc = await asyncio.create_subprocess_exec(
        *[str(c) for c in cmd],
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    tail = []

    async def reader():
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "ignore").rstrip()
            if on_line:
                await on_line(line)
            if not (ignore and line.startswith(tuple(ignore))):
                tail.append(line)
                del tail[:-60]

    task = asyncio.ensure_future(reader())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=1)
            if done:
                break
            if stop and stop():
                raise Cancelled()
    finally:
        if proc.returncode is None:
            proc.kill()
    task.result()
    await proc.wait()
    return proc.returncode, "\n".join(tail)
