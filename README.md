# Instagram → Telegram бот

Бот бачить Instagram-посилання (reel / p / tv) у повідомленні, качає публічне відео
і відправляє його як відповідь (Reply) на це повідомлення.

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

## Нюанси

- Ліміт Telegram для ботів — 50 МБ на файл.
- Якщо пост — фото або приватний, бот мовчить (пише в лог).
- Instagram іноді блокує анонімні запити. Тоді експортуй cookies зі свого браузера
  (розширення «Get cookies.txt LOCALLY») і вкажи шлях у `COOKIES_FILE`.
- Якщо щось перестало качатися — онови yt-dlp: `pip install -U yt-dlp`.
- Бажано встановити ffmpeg — тоді yt-dlp зможе зклеювати відео й аудіо, якщо Instagram віддає їх окремо.
