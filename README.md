# Instagram / Facebook / TikTok → Telegram бот

Бот бачить у повідомленні посилання на відео з Instagram, Facebook або TikTok, качає публічне відео
і відправляє його як відповідь (Reply) на це повідомлення.

Підтримувані посилання:
- **Instagram:** `instagram.com/reel/…`, `/p/…`, `/tv/…`
- **Facebook:** `facebook.com/reel/…`, `/watch?v=…`, `/<сторінка>/videos/…`, `/share/v/…`, `/share/r/…`, `fb.watch/…`
- **TikTok:** `tiktok.com/@<user>/video/…`, `vm.tiktok.com/…`, `vt.tiktok.com/…`, `tiktok.com/t/…`

## Запуск

1. Створи бота в [@BotFather](https://t.me/BotFather) → `/newbot`, скопіюй токен.
2. **Для груп:** у BotFather `/setprivacy` → вибери бота → `Disable`.
   Інакше бот не бачитиме звичайні повідомлення в групі. Після цього видали й знову додай бота в групу.
3. Встанови залежності та запусти:

```bash
pip install -r requirements.txt
cp .env.example .env   # і впиши BOT_TOKEN
python bot.py
```

## Запуск на сервері (Ubuntu, напр. Oracle Cloud)

```bash
git clone https://github.com/Silvedko/insta-video-loader-tg-bot.git
bash insta-video-loader-tg-bot/deploy.sh
```

Скрипт встановить усе потрібне, спитає токен і запустить бота як службу.
Оновлення до свіжої версії: `bash ~/insta-video-loader-tg-bot/deploy.sh`.
Логи: `sudo journalctl -u insta-bot -f`.

Не запускай бота одночасно на сервері й на своєму комп'ютері — Telegram видасть помилку `Conflict`.

## Нюанси

- Ліміт Telegram для ботів — 50 МБ на файл.
- Якщо пост — фото або приватний, бот мовчить (пише в лог).
- Instagram, Facebook і TikTok іноді блокують анонімні запити. Тоді експортуй cookies зі свого браузера
  (розширення «Get cookies.txt LOCALLY») і вкажи шлях у `COOKIES_FILE`.
  Якщо потрібні cookies для кількох сайтів — експортуй їх по черзі (instagram.com, facebook.com, tiktok.com)
  і склей вміст в один файл.
- Якщо щось перестало качатися — онови yt-dlp: `pip install -U yt-dlp`.
- Бажано встановити ffmpeg — тоді yt-dlp зможе зклеювати відео й аудіо, якщо Instagram віддає їх окремо.
