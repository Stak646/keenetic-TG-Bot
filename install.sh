#!/bin/sh
set -e
export PATH="/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

opkg update
opkg install python3 python3-pip ca-certificates curl coreutils-nohup

python3 -m pip install --upgrade pip
python3 -m pip install --no-cache-dir pyTelegramBotAPI

# Target dir: prefer /etc, fallback to /opt/etc and symlink /etc -> /opt/etc if possible
CFG_DIR="/etc/keenetic-tg-bot"
if [ ! -d /etc ] || [ ! -w /etc ]; then
  CFG_DIR="/opt/etc/keenetic-tg-bot"
fi
mkdir -p "$CFG_DIR" /opt/etc/init.d

cp -f ./bot.py "$CFG_DIR/bot.py"
chmod +x "$CFG_DIR/bot.py"

if [ ! -f "$CFG_DIR/config.json" ]; then
  cp -f ./config.example.json "$CFG_DIR/config.json"
  echo "Created $CFG_DIR/config.json (EDIT IT: bot_token, admins!)"
fi

cp -f ./S99keenetic-tg-bot /opt/etc/init.d/S99keenetic-tg-bot
chmod +x /opt/etc/init.d/S99keenetic-tg-bot

# Create /etc symlink if we installed into /opt/etc
if [ "$CFG_DIR" = "/opt/etc/keenetic-tg-bot" ] && [ ! -e /etc/keenetic-tg-bot ] && [ -w /etc ]; then
  ln -s /opt/etc/keenetic-tg-bot /etc/keenetic-tg-bot || true
fi

/opt/etc/init.d/S99keenetic-tg-bot restart || true
/opt/etc/init.d/S99keenetic-tg-bot status || true
echo "Logs: /opt/var/log/keenetic-tg-bot.log"
