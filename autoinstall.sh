#!/bin/sh
# Auto-install for Keenetic TG bot + modules (HydraRoute Neo, NFQWS2 + web, AWG Manager) + weekly updates
# Runs on Keenetic Entware (/opt).
#
# By default this script is interactive: it detects what is installed and asks what to install.
# Non-interactive: add --yes (install everything missing) or pass explicit flags.
#
# Examples:
#   sh autoinstall.sh              # interactive
#   sh autoinstall.sh --yes        # install all missing
#   sh autoinstall.sh --bot --cron --weekly
#   sh autoinstall.sh --hydra --nfqws2 --nfqwsweb --awg

set -e

WITH_BOT=0
WITH_HYDRA=0
WITH_NFQWS2=0
WITH_NFQWSWEB=0
WITH_AWG=0
WITH_CRON=0
WITH_WEEKLY=0
ASSUME_YES=0

has_cmd() { command -v "$1" >/dev/null 2>&1; }
is_file() { [ -f "$1" ]; }
is_exec() { [ -x "$1" ]; }

need_opt() {
  if [ ! -d /opt ] || [ ! -x /opt/bin/opkg ]; then
    echo "ERROR: Entware (/opt + opkg) is not ready."
    echo "Install Entware on Keenetic first, then retry."
    exit 1
  fi
  export PATH="/opt/bin:/opt/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
}

installed_bot() {
  [ -f /opt/keenetic-tg-bot/bot.py ] && [ -x /opt/etc/init.d/S99keenetic-tg-bot ]
}

installed_hydra() {
  has_cmd neo || has_cmd hr || is_exec /opt/bin/neo || is_exec /opt/bin/hr
}

installed_nfqws2() {
  is_exec /opt/etc/init.d/S51nfqws2 || has_cmd nfqws2 || is_exec /opt/bin/nfqws2
}

installed_nfqwsweb() {
  # web ui package creates /opt/etc/nfqws_web.conf and/or /opt/share/nfqws-web
  [ -f /opt/etc/nfqws_web.conf ] || [ -d /opt/share/nfqws-web ] || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^nfqws-keenetic-web '
}

installed_awg() {
  is_exec /opt/etc/init.d/S99awg-manager || has_cmd awg-manager || is_exec /opt/bin/awg-manager
}

installed_cron() {
  is_exec /opt/etc/init.d/S10cron || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^cron '
}

say_status() {
  echo "==== DETECTED ===="
  printf "BOT:        %s\n" "$(installed_bot && echo 'installed' || echo 'missing')"
  printf "HydraRoute:  %s\n" "$(installed_hydra && echo 'installed' || echo 'missing')"
  printf "NFQWS2:      %s\n" "$(installed_nfqws2 && echo 'installed' || echo 'missing')"
  printf "NFQWS web:   %s\n" "$(installed_nfqwsweb && echo 'installed' || echo 'missing')"
  printf "AWG Manager: %s\n" "$(installed_awg && echo 'installed' || echo 'missing')"
  printf "cron:        %s\n" "$(installed_cron && echo 'installed' || echo 'missing')"
  echo "==============="
}

ask() {
  # $1 prompt, returns 0 if yes
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  printf "%s [y/N]: " "$1"
  read ans || true
  case "$ans" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

install_base() {
  opkg update
  # nohup required by init script; curl/ca for HTTPS downloads
  opkg install ca-certificates curl coreutils-nohup
}

install_bot() {
  echo "[BOT] install python + deps..."
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
  # KN-1012 is aarch64-3.10; feed is universal aarch64 in upstream
  FEED="https://nfqws.github.io/nfqws2-keenetic/aarch64"
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
  # update the key packages; ignore failures to keep cron running
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

usage() {
  echo "Usage:"
  echo "  sh autoinstall.sh                 # interactive"
  echo "  sh autoinstall.sh --yes           # install everything missing"
  echo "  sh autoinstall.sh --bot --cron --weekly"
  echo "  sh autoinstall.sh --hydra --nfqws2 --nfqwsweb --awg"
}

# Parse args (optional)
if [ $# -gt 0 ]; then
  for a in "$@"; do
    case "$a" in
      --yes) ASSUME_YES=1 ;;
      --bot) WITH_BOT=1 ;;
      --hydra) WITH_HYDRA=1 ;;
      --nfqws2) WITH_NFQWS2=1 ;;
      --nfqwsweb) WITH_NFQWSWEB=1 ;;
      --awg) WITH_AWG=1 ;;
      --cron) WITH_CRON=1 ;;
      --weekly) WITH_WEEKLY=1 ;;
      -h|--help) usage; exit 0 ;;
      *) echo "Unknown arg: $a"; usage; exit 2 ;;
    esac
  done
fi

need_opt
install_base

say_status

# If no explicit flags were passed, run interactive detection/prompting
if [ "$WITH_BOT$WITH_HYDRA$WITH_NFQWS2$WITH_NFQWSWEB$WITH_AWG$WITH_CRON$WITH_WEEKLY" = "0000000" ]; then
  echo "No explicit flags provided. Interactive mode."
  if ! installed_hydra; then ask "Install HydraRoute Neo?"; WITH_HYDRA=$?; WITH_HYDRA=$((1 - WITH_HYDRA)); fi
  if ! installed_nfqws2; then ask "Install NFQWS2?"; WITH_NFQWS2=$?; WITH_NFQWS2=$((1 - WITH_NFQWS2)); fi
  if installed_nfqws2 && ! installed_nfqwsweb; then ask "Install NFQWS web UI?"; WITH_NFQWSWEB=$?; WITH_NFQWSWEB=$((1 - WITH_NFQWSWEB)); fi
  if ! installed_awg; then ask "Install AWG Manager?"; WITH_AWG=$?; WITH_AWG=$((1 - WITH_AWG)); fi
  if ! installed_cron; then ask "Install cron (for scheduling updates)?"; WITH_CRON=$?; WITH_CRON=$((1 - WITH_CRON)); fi
  if [ "$WITH_CRON" -eq 1 ]; then
    ask "Setup weekly updates (Thu 06:00)?"; WITH_WEEKLY=$?; WITH_WEEKLY=$((1 - WITH_WEEKLY))
  fi
  if ! installed_bot; then ask "Install Telegram bot service?"; WITH_BOT=$?; WITH_BOT=$((1 - WITH_BOT)); fi
else
  # If --yes was provided, install missing for the selected set.
  if [ "$ASSUME_YES" -eq 1 ]; then
    [ "$WITH_HYDRA" -eq 1 ] && installed_hydra && WITH_HYDRA=0 || true
    [ "$WITH_NFQWS2" -eq 1 ] && installed_nfqws2 && WITH_NFQWS2=0 || true
    [ "$WITH_NFQWSWEB" -eq 1 ] && installed_nfqwsweb && WITH_NFQWSWEB=0 || true
    [ "$WITH_AWG" -eq 1 ] && installed_awg && WITH_AWG=0 || true
    [ "$WITH_CRON" -eq 1 ] && installed_cron && WITH_CRON=0 || true
    [ "$WITH_BOT" -eq 1 ] && installed_bot && WITH_BOT=0 || true
  fi
fi

# If only --yes was specified (no flags) => install everything missing
if [ "$ASSUME_YES" -eq 1 ] && [ "$WITH_BOT$WITH_HYDRA$WITH_NFQWS2$WITH_NFQWSWEB$WITH_AWG$WITH_CRON$WITH_WEEKLY" = "0000000" ]; then
  echo "--yes with no flags: install everything missing."
  installed_hydra || WITH_HYDRA=1
  installed_nfqws2 || WITH_NFQWS2=1
  if installed_nfqws2 && ! installed_nfqwsweb; then WITH_NFQWSWEB=1; fi
  installed_awg || WITH_AWG=1
  installed_cron || WITH_CRON=1
  WITH_WEEKLY=1
  installed_bot || WITH_BOT=1
fi

# Execute
if [ "$WITH_HYDRA" -eq 1 ]; then install_hydra; fi
if [ "$WITH_NFQWS2" -eq 1 ]; then install_nfqws2; fi
if [ "$WITH_NFQWSWEB" -eq 1 ]; then install_nfqwsweb; fi
if [ "$WITH_AWG" -eq 1 ]; then install_awg; fi
if [ "$WITH_CRON" -eq 1 ]; then install_cron; fi
if [ "$WITH_WEEKLY" -eq 1 ]; then setup_weekly_updates; fi
if [ "$WITH_BOT" -eq 1 ]; then install_bot; fi

echo "DONE."
echo "Edit bot config: /opt/etc/keenetic-tg-bot/config.json (bot_token/admins)"
