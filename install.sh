#!/bin/sh
set -e

echo "[1/6] opkg update"
opkg update

echo "[2/6] install python3 + pip + basic tools"
# набор может отличаться по сборке Entware; если чего-то нет — удалите из списка
opkg install python3 python3-pip ca-certificates curl

echo "[3/6] pip install pyTelegramBotAPI"
python3 -m pip install --upgrade pip
python3 -m pip install --no-cache-dir pyTelegramBotAPI

echo "[4/6] deploy files"
APP_DIR="/opt/keenetic-tg-bot"
CFG_DIR="/opt/etc/keenetic-tg-bot"
INIT_DIR="/opt/etc/init.d"

mkdir -p "$APP_DIR" "$CFG_DIR" "$INIT_DIR"

cp -f ./bot.py "$APP_DIR/bot.py"
chmod +x "$APP_DIR/bot.py"

if [ ! -f "$CFG_DIR/config.json" ]; then
  cp -f ./config.example.json "$CFG_DIR/config.json"
  echo "Created $CFG_DIR/config.json (EDIT IT: bot_token, admins!)"
else
  echo "Config already exists: $CFG_DIR/config.json"
fi

cp -f ./S99keenetic-tg-bot "$INIT_DIR/S99keenetic-tg-bot"
chmod +x "$INIT_DIR/S99keenetic-tg-bot"

echo "[5/6] start service"
"$INIT_DIR/S99keenetic-tg-bot" restart || true

echo "[6/6] done"
echo "Edit config at: $CFG_DIR/config.json"
echo "Logs: /opt/var/log/keenetic-tg-bot.log"
