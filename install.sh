#!/bin/sh
set -e
export PATH="/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

pick_cfg_dir() {
  for d in /etc/keenetic-tg-bot /opt/etc/keenetic-tg-bot; do
    mkdir -p "$d" >/dev/null 2>&1 || continue
    tfile="$d/.rwtest.$$"
    if ( : > "$tfile" ) 2>/dev/null; then
      rm -f "$tfile" >/dev/null 2>&1 || true
      echo "$d"
      return 0
    fi
  done
  mkdir -p /opt/etc/keenetic-tg-bot >/dev/null 2>&1 || true
  echo "/opt/etc/keenetic-tg-bot"
}

opkg update
opkg install python3 python3-pip ca-certificates curl coreutils-nohup

python3 -m pip install --upgrade pip
python3 -m pip install --no-cache-dir pyTelegramBotAPI

CFG_DIR="$(pick_cfg_dir)"
mkdir -p "$CFG_DIR" /opt/etc/init.d

cp -f ./bot.py "$CFG_DIR/bot.py"
chmod +x "$CFG_DIR/bot.py"

# optional modules
if [ -d ./keenetic_tg_bot ]; then
  rm -rf "$CFG_DIR/keenetic_tg_bot" >/dev/null 2>&1 || true
  cp -R ./keenetic_tg_bot "$CFG_DIR/keenetic_tg_bot"
fi

if [ ! -f "$CFG_DIR/config.json" ]; then
  cp -f ./config.example.json "$CFG_DIR/config.json"
  echo "Created $CFG_DIR/config.json"
fi

cp -f ./S99keenetic-tg-bot /opt/etc/init.d/S99keenetic-tg-bot
chmod +x /opt/etc/init.d/S99keenetic-tg-bot

/opt/etc/init.d/S99keenetic-tg-bot restart || true
/opt/etc/init.d/S99keenetic-tg-bot status || true
echo "Logs: /opt/var/log/keenetic-tg-bot.log"
