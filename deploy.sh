#!/usr/bin/env bash
# Встановлює бота на Ubuntu-сервер і запускає його як службу (працює 24/7, піднімається після перезавантаження).
# Запуск: bash deploy.sh   (повторний запуск = оновлення до свіжої версії з GitHub)
set -euo pipefail

REPO="https://github.com/Silvedko/insta-video-loader-tg-bot.git"
APP_DIR="$HOME/insta-video-loader-tg-bot"
SERVICE="insta-bot"

echo "==> Встановлюю системні пакети"
sudo apt-get update -q
sudo apt-get install -y -q python3 python3-venv python3-pip ffmpeg git

echo "==> Завантажую код"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only
else
    git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> Встановлюю Python-бібліотеки"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -U -r requirements.txt

if [ ! -f .env ]; then
    read -rp "Встав BOT_TOKEN від @BotFather: " TOKEN < /dev/tty
    printf 'BOT_TOKEN=%s\nCOOKIES_FILE=\n' "$TOKEN" > .env
    chmod 600 .env
fi

echo "==> Налаштовую службу $SERVICE"
sudo tee "/etc/systemd/system/$SERVICE.service" > /dev/null <<EOF
[Unit]
Description=Instagram video Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
# Перед кожним стартом оновлюємо yt-dlp: Instagram часто змінюється
ExecStartPre=-$APP_DIR/.venv/bin/pip install -q -U yt-dlp
ExecStart=$APP_DIR/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE" > /dev/null
sudo systemctl restart "$SERVICE"
sleep 5
sudo systemctl --no-pager status "$SERVICE" | head -n 5

echo
echo "Готово. Логи:      sudo journalctl -u $SERVICE -f"
echo "Перезапуск:        sudo systemctl restart $SERVICE"
