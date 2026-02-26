#!/bin/sh
# Auto-install for Keenetic TG bot + modules + weekly updates
# Usage:
#   sh autoinstall.sh --all
#   sh autoinstall.sh --bot --cron --weekly
#   sh autoinstall.sh --hydra --nfqws2 --nfqwsweb --awg
#
# NOTE: edit /opt/etc/keenetic-tg-bot/config.json after install (token/admins)

set -e

WITH_BOT=0
WITH_HYDRA=0
WITH_NFQWS2=0
WITH_NFQWSWEB=0
WITH_AWG=0
WITH_CRON=0
WITH_WEEKLY=0

if [ $# -eq 0 ]; then
  echo "Usage: $0 [--bot] [--hydra] [--nfqws2] [--nfqwsweb] [--awg] [--cron] [--weekly] [--all]"
  exit 1
fi

for a in "$@"; do
  case "$a" in
    --bot) WITH_BOT=1 ;;
    --hydra) WITH_HYDRA=1 ;;
    --nfqws2) WITH_NFQWS2=1 ;;
    --nfqwsweb) WITH_NFQWSWEB=1 ;;
    --awg) WITH_AWG=1 ;;
    --cron) WITH_CRON=1 ;;
    --weekly) WITH_WEEKLY=1 ;;
    --all) WITH_BOT=1; WITH_HYDRA=1; WITH_NFQWS2=1; WITH_NFQWSWEB=1; WITH_AWG=1; WITH_CRON=1; WITH_WEEKLY=1 ;;
    *) echo "Unknown arg: $a"; exit 2 ;;
  esac
done

need_opt() {
  if [ ! -d /opt ] || [ ! -x /opt/bin/opkg ]; then
    echo "ERROR: Entware (/opt + opkg) is not ready."
    echo "Install Entware on Keenetic first, then retry."
    exit 1
  fi
}

install_base() {
  opkg update
  # nohup is required by init script
  opkg install ca-certificates curl coreutils-nohup
}

install_bot() {
  echo "[BOT] installing python + deps..."
  opkg update
  opkg install python3 python3-pip ca-certificates curl coreutils-nohup
  python3 -m pip install --upgrade pip
  python3 -m pip install --no-cache-dir pyTelegramBotAPI

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
    echo "Config exists: $CFG_DIR/config.json"
  fi

  cp -f ./S99keenetic-tg-bot "$INIT_DIR/S99keenetic-tg-bot"
  chmod +x "$INIT_DIR/S99keenetic-tg-bot"

  echo "[BOT] restart service..."
  "$INIT_DIR/S99keenetic-tg-bot" restart || true
  "$INIT_DIR/S99keenetic-tg-bot" status || true
  echo "[BOT] logs: /opt/var/log/keenetic-tg-bot.log"
}

install_hydra() {
  echo "[HydraRoute Neo] install..."
  opkg update
  opkg install curl
  curl -Ls "https://ground-zerro.github.io/release/keenetic/install-neo.sh" | sh
}

install_nfqws2() {
  echo "[NFQWS2] install..."
  opkg update
  opkg install ca-certificates wget-ssl
  opkg remove wget-nossl || true
  mkdir -p /opt/etc/opkg
  if opkg print-architecture | grep -q "aarch64-3.10"; then
    FEED="https://nfqws.github.io/nfqws2-keenetic/aarch64"
  else
    FEED="https://nfqws.github.io/nfqws2-keenetic/aarch64"
  fi
  echo "src/gz nfqws2-keenetic $FEED" > /opt/etc/opkg/nfqws2-keenetic.conf
  opkg update
  opkg install nfqws2-keenetic
}

install_nfqwsweb() {
  echo "[NFQWS web] install..."
  opkg update
  opkg install ca-certificates wget-ssl
  opkg remove wget-nossl || true
  mkdir -p /opt/etc/opkg
  echo "src/gz nfqws-keenetic-web https://nfqws.github.io/nfqws-keenetic-web/all" > /opt/etc/opkg/nfqws-keenetic-web.conf
  opkg update
  opkg install nfqws-keenetic-web
}

install_awg() {
  echo "[AWG Manager] install..."
  opkg update
  opkg install ca-certificates curl
  curl -sL "https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh" | sh
}

install_cron() {
  echo "[cron] install..."
  opkg update
  opkg install cron
  /opt/etc/init.d/S10cron start || true
}

setup_weekly_updates() {
  echo "[weekly updates] setup every Thu 06:00"
  UPD="/opt/bin/weekly-update.sh"
  mkdir -p /opt/bin /opt/var/log
  cat > "$UPD" <<'SH'
#!/bin/sh
LOG="/opt/var/log/weekly-update.log"
mkdir -p /opt/var/log
{
  echo "===== $(date) weekly update ====="
  opkg update
  opkg upgrade hrneo hrweb nfqws2-keenetic nfqws-keenetic-web awg-manager coreutils-nohup python3 python3-pip || true
  command -v neo >/dev/null 2>&1 && neo restart || true
  [ -x /opt/etc/init.d/S51nfqws2 ] && /opt/etc/init.d/S51nfqws2 restart || true
  [ -x /opt/etc/init.d/S99awg-manager ] && /opt/etc/init.d/S99awg-manager restart || true
  [ -x /opt/etc/init.d/S99keenetic-tg-bot ] && /opt/etc/init.d/S99keenetic-tg-bot restart || true
  echo "OK"
  echo
} >> "$LOG" 2>&1
SH
  chmod +x "$UPD"

  CRONFILE="/opt/etc/crontab"
  LINE="0 6 * * 4 root $UPD"
  touch "$CRONFILE"
  if ! grep -Fq "$UPD" "$CRONFILE"; then
    echo "$LINE" >> "$CRONFILE"
  fi
  /opt/etc/init.d/S10cron restart || true
  echo "[weekly updates] done. log: /opt/var/log/weekly-update.log"
}

need_opt
install_base

if [ "$WITH_HYDRA" -eq 1 ]; then install_hydra; fi
if [ "$WITH_NFQWS2" -eq 1 ]; then install_nfqws2; fi
if [ "$WITH_NFQWSWEB" -eq 1 ]; then install_nfqwsweb; fi
if [ "$WITH_AWG" -eq 1 ]; then install_awg; fi
if [ "$WITH_CRON" -eq 1 ]; then install_cron; fi
if [ "$WITH_WEEKLY" -eq 1 ]; then setup_weekly_updates; fi
if [ "$WITH_BOT" -eq 1 ]; then install_bot; fi

echo "DONE."
echo "Remember to edit: /opt/etc/keenetic-tg-bot/config.json (bot_token/admins)"
