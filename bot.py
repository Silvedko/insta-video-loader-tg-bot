"""Telegram-бот: знаходить Instagram- і Facebook-посилання в повідомленнях,
качає публічне відео і відповідає на повідомлення цим відео."""

import asyncio
import copy
import itertools
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, ContextTypes, MessageHandler, filters

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Необов'язково: cookies.txt від залогінених Instagram/Facebook-акаунтів (допомагає, коли сайт просить логін)
COOKIES_FILE = os.getenv("COOKIES_FILE") or None
# Ліміт Telegram Bot API на відправку файлів — 50 МБ
MAX_SIZE = 50 * 1024 * 1024
# Скільки відео максимум надсилати з одного посту-каруселі
MAX_VIDEOS_PER_LINK = 10

BASE_OPTS = {
    "merge_output_format": "mp4",
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
}
if COOKIES_FILE:
    BASE_OPTS["cookiefile"] = COOKIES_FILE


def _quality(h: int) -> str:
    return (f"b[height<={h}][ext=mp4]/bv*[height<={h}][ext=mp4]+ba[ext=m4a]"
            f"/bv*[height<={h}]+ba/b[height<={h}]")


# Варіанти якості від найкращої до найгіршої. Якщо файл не влазить у 50 МБ — пробуємо наступний.
# Спершу готовий mp4 з аудіо (не потрібен ffmpeg), інакше відео+аудіо окремо (склеює ffmpeg).
FORMAT_LADDER = [
    "b[ext=mp4]/bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b",
    _quality(720),
    _quality(480),
    _quality(360),
    _quality(240),
    "w[ext=mp4]/wv*+wa/w",
]
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}

INSTAGRAM_RE = re.compile(
    r"https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/[\w-]+/?(?:\?[^\s]*)?",
    re.IGNORECASE,
)
FACEBOOK_RE = re.compile(
    r"https?://(?:(?:www|m|web|mbasic)\.)?(?:"
    r"facebook\.com/(?:"
    r"reel/\d+"
    r"|watch/?\?\S*?v=\d+"
    r"|video\.php\?\S*?v=\d+"
    r"|share/[vr]/[\w-]+"
    r"|[\w.-]+/(?:videos|posts)/[\w.-]+(?:/\d+)?"
    r")"
    r"|fb\.watch/[\w-]+"
    r")/?\S*",
    re.IGNORECASE,
)
# Короткі посилання, що лише перенаправляють на справжню адресу відео
FB_SHORT_RE = re.compile(r"fb\.watch/|facebook\.com/share/", re.IGNORECASE)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("insta-bot")


def extract_links(text: str) -> list[str]:
    """Унікальні Instagram- і Facebook-посилання в порядку появи в тексті."""
    text = text or ""
    found = []
    for m in INSTAGRAM_RE.finditer(text):
        # У Instagram параметри після "?" (igsh=...) не потрібні
        found.append((m.start(), m.group(0).split("?")[0]))
    for m in FACEBOOK_RE.finditer(text):
        # У Facebook параметри потрібні (watch?v=...), тож лише прибираємо розділові знаки в кінці
        found.append((m.start(), m.group(0).rstrip(".,!?)]>»\"'")))

    seen, result = set(), []
    for _, url in sorted(found):
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def resolve_short_link(ydl: yt_dlp.YoutubeDL, url: str) -> str:
    """fb.watch/... і facebook.com/share/... → справжня адреса відео."""
    try:
        with ydl.urlopen(url) as resp:
            final = resp.url
    except Exception:
        log.warning("Не вдалося розкрити коротке посилання %s", url, exc_info=True)
        return url
    # Facebook іноді перекидає на сторінку логіну, а справжня адреса лежить у параметрі next
    nxt = parse_qs(urlparse(final).query).get("next")
    if "/login" in final and nxt:
        final = nxt[0]
    log.info("Коротке посилання %s → %s", url, final)
    return final


def estimated_size(info: dict) -> int | None:
    """Приблизний розмір файлу до завантаження (None, якщо сайт не дав даних)."""
    total = 0
    for f in info.get("requested_formats") or [info]:
        size = f.get("filesize") or f.get("filesize_approx")
        if not size and f.get("tbr") and info.get("duration"):
            size = f["tbr"] * 1000 / 8 * info["duration"]
        if not size:
            return None
        total += size
    return int(total)


def download_entry(entry: dict, out_dir: str) -> tuple[Path | None, bool]:
    """Качає одне відео, знижуючи якість, доки файл не влізе в 50 МБ.
    Повертає (файл або None, чи траплявся варіант більший за ліміт)."""
    os.makedirs(out_dir, exist_ok=True)
    tried: set[str] = set()
    too_big = False

    for spec in FORMAT_LADDER:
        attempt_dir = tempfile.mkdtemp(dir=out_dir)
        opts = {**BASE_OPTS, "format": spec,
                "outtmpl": os.path.join(attempt_dir, "%(id)s.%(ext)s")}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Спершу лише вибираємо формат (без завантаження) і оцінюємо розмір
                info = ydl.process_ie_result(copy.deepcopy(entry), download=False)
                fmt = info.get("format_id")
                if fmt in tried:
                    continue  # цей самий формат уже пробували
                tried.add(fmt)
                est = estimated_size(info)
                if est and est > MAX_SIZE * 1.1:
                    log.info("Формат %s ~%d МБ — завеликий, пробую нижчу якість", fmt, est >> 20)
                    too_big = True
                    continue
                ydl.process_ie_result(copy.deepcopy(entry), download=True)
        except Exception as e:
            log.debug("Варіант якості %r не підійшов: %s", spec, e)
            continue

        files = [p for p in Path(attempt_dir).iterdir() if p.suffix.lower() in VIDEO_EXT]
        if not files:
            continue
        f = max(files, key=lambda p: p.stat().st_size)
        if f.stat().st_size <= MAX_SIZE:
            return f, too_big
        log.info("Формат %s вийшов %d МБ — завеликий, пробую нижчу якість", fmt, f.stat().st_size >> 20)
        too_big = True
        shutil.rmtree(attempt_dir, ignore_errors=True)

    return None, too_big


def download(url: str, out_dir: str) -> tuple[list[Path], int]:
    """Качає всі відео з посту.
    Повертає (файли, скільки відео не вдалося вмістити в 50 МБ навіть у найнижчій якості)."""
    try:
        with yt_dlp.YoutubeDL(BASE_OPTS) as ydl:
            if FB_SHORT_RE.search(url):
                url = resolve_short_link(ydl, url)
            # Лише інформація про пост, без вибору формату та завантаження
            raw = ydl.extract_info(url, download=False, process=False)
    except Exception as e:
        log.info("Не вдалося отримати відео з %s: %s", url, e)
        return [], 0
    if not raw:
        return [], 0

    if raw.get("_type") == "playlist":  # карусель з кількох відео/фото
        entries = [e for e in itertools.islice(raw.get("entries") or [], MAX_VIDEOS_PER_LINK) if e]
        for e in entries:
            for key in ("extractor", "extractor_key", "webpage_url", "original_url"):
                if raw.get(key):
                    e.setdefault(key, raw[key])
    else:
        entries = [raw]

    files, too_big = [], 0
    for n, entry in enumerate(entries, 1):
        f, big = download_entry(entry, os.path.join(out_dir, str(n)))
        if f:
            files.append(f)
        elif big:
            too_big += 1
    return files, too_big


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    links = extract_links(message.text or message.caption or "")
    if not links:
        return

    for url in links:
        tmp = tempfile.mkdtemp(prefix="video_")
        try:
            await context.bot.send_chat_action(message.chat_id, ChatAction.UPLOAD_VIDEO)
            files, too_big = await asyncio.to_thread(download, url, tmp)

            if too_big:
                await message.reply_text(
                    "Відео більше 50 МБ навіть у найнижчій якості — "
                    "Telegram не дозволяє ботам надсилати такі файли.",
                    do_quote=True,
                )
            if not files:
                if not too_big:
                    log.info("Відео не знайдено (фото/приватний пост?): %s", url)
                continue

            for f in files:
                with f.open("rb") as video:
                    await message.reply_video(
                        video=video,
                        supports_streaming=True,
                        do_quote=True,
                        read_timeout=120,
                        write_timeout=120,
                    )
            log.info("Надіслано %d відео з %s", len(files), url)
        except Exception:
            log.exception("Не вдалося обробити %s", url)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
    app.add_handler(
        MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, handle_message)
    )
    log.info("Бот запущено")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
