#!/bin/sh
set -e

# Install keenetic-tg-bot files into /opt/etc (Keenetic /etc is often read-only)
BOT_DIR="/opt/etc/keenetic-tg-bot"
INIT_DIR="/opt/etc/init.d"

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$BOT_DIR" "$BOT_DIR/config" "$BOT_DIR/modules" "$INIT_DIR" /opt/var/log /opt/var/run

# copy code
cp -f "$SRC_DIR/Main.py" "$BOT_DIR/Main.py"
chmod +x "$BOT_DIR/Main.py" || true

# modules package
rm -rf "$BOT_DIR/modules" >/dev/null 2>&1 || true
cp -a "$SRC_DIR/modules" "$BOT_DIR/"

# config example (do not overwrite real config)
if [ -f "$SRC_DIR/config/config.example.json" ]; then
  cp -f "$SRC_DIR/config/config.example.json" "$BOT_DIR/config/config.example.json"
elif [ -f "$SRC_DIR/config.example.json" ]; then
  cp -f "$SRC_DIR/config.example.json" "$BOT_DIR/config/config.example.json"
fi

# backward-compat link
if [ -f "$BOT_DIR/config/config.json" ] && [ ! -f "$BOT_DIR/config.json" ]; then
  ln -s "$BOT_DIR/config/config.json" "$BOT_DIR/config.json" 2>/dev/null || true
fi

# init script
cp -f "$SRC_DIR/S99keenetic-tg-bot" "$INIT_DIR/S99keenetic-tg-bot"
chmod +x "$INIT_DIR/S99keenetic-tg-bot" || true

echo "OK: installed into $BOT_DIR"
echo "Init: $INIT_DIR/S99keenetic-tg-bot"


# sanity: compile python files before service start
if [ -x /opt/bin/python3 ]; then
  /opt/bin/python3 -m py_compile "$BOT_DIR/Main.py" "$BOT_DIR/modules/"*.py "$BOT_DIR/modules/drivers/"*.py >/dev/null 2>&1 || {
    echo "ERROR: python compile failed"; exit 1; }
fi
