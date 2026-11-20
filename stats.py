"""Статистика бота: лічильник лінків і завантажень у SQLite.

Імена, Telegram ID, чати й самі посилання не зберігаються.
Щоб рахувати унікальних користувачів, замість ID зберігається HMAC-хеш
із секретним ключем (файл .stats_salt поруч із базою). Без ключа хеш не
перетворити назад на ID навіть перебором.
"""

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo("Europe/Kyiv")
except Exception:  # немає бази часових поясів — рахуємо «сьогодні» за UTC
    LOCAL_TZ = timezone.utc

log = logging.getLogger("insta-bot.stats")

TS_FMT = "%Y-%m-%d %H:%M:%S"

# (підпис, скільки днів назад; None — з початку сьогоднішньої доби за Києвом, 0 — за весь час)
PERIODS = [
    ("Сьогодні", None),
    ("7 днів", 7),
    ("30 днів", 30),
    ("Пів року", 182),
    ("Рік", 365),
    ("Усього", 0),
]
PLATFORM_NAMES = {"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}


def platform_of(url: str) -> str:
    url = url.lower()
    if "tiktok.com" in url:
        return "tiktok"
    if "instagram.com" in url:
        return "instagram"
    return "facebook"


class Stats:
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,        -- час у UTC
                platform TEXT NOT NULL,  -- instagram / tiktok / facebook
                status TEXT NOT NULL,    -- sent / too_big / failed
                user_hash TEXT           -- HMAC від Telegram ID; сам ID не зберігається
            )"""
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")
        self.db.commit()
        salt_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), ".stats_salt")
        self.salt = self._load_salt(salt_path)

    @staticmethod
    def _load_salt(path: str) -> bytes:
        try:
            with open(path, "rb") as f:
                salt = f.read()
            if salt:
                return salt
        except FileNotFoundError:
            pass
        salt = secrets.token_bytes(32)
        with open(path, "wb") as f:
            f.write(salt)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return salt

    def user_hash(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        return hmac.new(self.salt, str(user_id).encode(), hashlib.sha256).hexdigest()[:16]

    def record(self, platform: str, status: str, user_id: int | None) -> None:
        """Записує один кинутий лінк. Помилка запису не має ламати роботу бота."""
        try:
            self.db.execute(
                "INSERT INTO events (ts, platform, status, user_hash) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).strftime(TS_FMT), platform, status,
                 self.user_hash(user_id)),
            )
            self.db.commit()
        except Exception:
            log.exception("Не вдалося записати статистику")

    @staticmethod
    def _since(days: int | None) -> str:
        now = datetime.now(timezone.utc)
        if days == 0:
            return ""
        if days is None:
            midnight = now.astimezone(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            start = midnight.astimezone(timezone.utc)
        else:
            start = now - timedelta(days=days)
        return start.strftime(TS_FMT)

    def summary_html(self) -> str:
        """Текст для команди /stats (HTML-розмітка Telegram)."""
        lines = [f"{'':9}{'Лінки':>6}{'Ок':>6}{'Збій':>6}{'Вел.':>6}{'Люди':>6}"]
        for label, days in PERIODS:
            links, sent, failed, too_big, users = self.db.execute(
                """SELECT COUNT(*),
                          COALESCE(SUM(status = 'sent'), 0),
                          COALESCE(SUM(status = 'failed'), 0),
                          COALESCE(SUM(status = 'too_big'), 0),
                          COUNT(DISTINCT user_hash)
                   FROM events WHERE ts >= ?""",
                (self._since(days),),
            ).fetchone()
            lines.append(f"{label:9}{links:>6}{sent:>6}{failed:>6}{too_big:>6}{users:>6}")

        by_platform = dict(self.db.execute(
            "SELECT platform, COUNT(*) FROM events WHERE status = 'sent' GROUP BY platform"
        ))
        platforms = " · ".join(
            f"{name} {by_platform.get(key, 0)}" for key, name in PLATFORM_NAMES.items()
        )

        return (
            "📊 <b>Статистика</b>\n\n"
            "<pre>" + "\n".join(lines) + "</pre>\n"
            f"Надіслано за весь час: {platforms}\n\n"
            "<i>Лінки — скільки лінків кинули\n"
            "Ок — відео надіслано\n"
            "Збій — не вдалося завантажити\n"
            "Вел. — відео більше 50 МБ\n"
            "Люди — різні користувачі\n"
            "Сьогодні — з опівночі за Києвом; інші періоди — останні N днів</i>"
        )
