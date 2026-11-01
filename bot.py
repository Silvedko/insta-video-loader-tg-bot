"""Telegram-бот: знаходить Instagram-посилання в повідомленнях,
качає публічне відео і відповідає на повідомлення цим відео."""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, ContextTypes, MessageHandler, filters

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Необов'язково: cookies.txt від залогіненого Instagram-акаунта (допомагає, коли Instagram просить логін)
COOKIES_FILE = os.getenv("COOKIES_FILE") or None
# Ліміт Telegram Bot API на відправку файлів — 50 МБ
MAX_SIZE = 50 * 1024 * 1024
# Скільки відео максимум надсилати з одного посту-каруселі
MAX_VIDEOS_PER_LINK = 10

INSTAGRAM_RE = re.compile(
    r"https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/[\w-]+/?(?:\?[^\s]*)?",
    re.IGNORECASE,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("insta-bot")


def extract_links(text: str) -> list[str]:
    """Унікальні Instagram-посилання в порядку появи."""
    seen, result = set(), []
    for m in INSTAGRAM_RE.finditer(text or ""):
        url = m.group(0).split("?")[0]
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def download(url: str, out_dir: str) -> list[Path]:
    """Качає всі відео з посту. Повертає список файлів (порожній, якщо відео нема)."""
    opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s_%(autonumber)s.%(ext)s"),
        # Спершу готовий mp4 з аудіо (не потрібен ffmpeg), інакше найкращий доступний
        "format": "b[ext=mp4][filesize<50M]/b[ext=mp4]/bv*[ext=mp4]+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "playlistend": MAX_VIDEOS_PER_LINK,
        "ignoreerrors": True,  # у каруселі можуть бути фото — їх пропускаємо
    }
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    files = sorted(
        p for p in Path(out_dir).iterdir()
        if p.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}
    )
    return files


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    links = extract_links(message.text or message.caption or "")
    if not links:
        return

    for url in links:
        tmp = tempfile.mkdtemp(prefix="insta_")
        try:
            await context.bot.send_chat_action(message.chat_id, ChatAction.UPLOAD_VIDEO)
            files = await asyncio.to_thread(download, url, tmp)

            if not files:
                log.info("Відео не знайдено (фото/приватний пост?): %s", url)
                continue

            for f in files:
                if f.stat().st_size > MAX_SIZE:
                    log.warning("Файл завеликий для Telegram (%d байт): %s", f.stat().st_size, url)
                    await message.reply_text(
                        "Відео більше 50 МБ — Telegram не дозволяє ботам таке надсилати.",
                        do_quote=True,
                    )
                    continue
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
