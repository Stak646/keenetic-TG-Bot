#!/bin/sh
# Keenetic TG Bot autoinstall (Entware /opt)
# - Works as: curl .../autoinstall.sh | sh
# - Interactive questions work even with pipe (reads from /dev/tty)
#
set -e
export PATH="/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

WITH_BOT=0
WITH_HYDRA=0
WITH_NFQWS2=0
WITH_NFQWSWEB=0
WITH_AWG=0
WITH_CRON=0
WITH_WEEKLY=0
ASSUME_YES=0

TG_TOKEN=""
TG_ADMIN_ID=""
RECONFIG=0

REPO="Stak646/keenetic-TG-Bot"
BRANCH="main"

has_cmd() { command -v "$1" >/dev/null 2>&1; }
is_exec() { [ -x "$1" ]; }

need_opt() {
  if [ ! -d /opt ] || [ ! -x /opt/bin/opkg ]; then
    echo "ERROR: Entware (/opt + opkg) is not ready."
    exit 1
  fi
}

raw_url() { echo "https://raw.githubusercontent.com/$REPO/$BRANCH/$1"; }

fetch_file() {
  URL="$(raw_url "$1")"
  DEST="$2"
  mkdir -p "$(dirname "$DEST")"
  echo "download: $URL -> $DEST" >&2
  curl -fsSL "$URL" -o "$DEST"
}

ensure_repo_files() {
  TMP="/opt/tmp/keenetic-tg-bot-installer"
  mkdir -p "$TMP"
  fetch_file "bot.py" "$TMP/bot.py"
  fetch_file "config.example.json" "$TMP/config.example.json"
  fetch_file "S99keenetic-tg-bot" "$TMP/S99keenetic-tg-bot"
  fetch_file "install.sh" "$TMP/install.sh"
  echo "$TMP"
}

ask() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  TTY="/dev/tty"
  if [ -r "$TTY" ]; then
    printf "%s [y/N]: " "$1" > "$TTY"
    read ans < "$TTY" || true
  else
    printf "%s [y/N]: " "$1"
    read ans || true
  fi
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

prompt_token_admin() {
  TTY="/dev/tty"
  if [ -z "$TG_TOKEN" ]; then
    echo "Telegram Bot Token (@BotFather /newbot)" >&2
    if [ -r "$TTY" ]; then printf "Введите bot_token: " > "$TTY"; read TG_TOKEN < "$TTY" || true; else printf "Введите bot_token: "; read TG_TOKEN || true; fi
  fi
  if [ -z "$TG_ADMIN_ID" ]; then
    echo "Telegram user_id (число, @userinfobot)" >&2
    if [ -r "$TTY" ]; then printf "Введите admin user_id: " > "$TTY"; read TG_ADMIN_ID < "$TTY" || true; else printf "Введите admin user_id: "; read TG_ADMIN_ID || true; fi
  fi
  case "$TG_ADMIN_ID" in ''|*[!0-9]*) echo "ERROR: admin user_id должен быть числом." >&2; exit 2 ;; esac
  [ -z "$TG_TOKEN" ] && { echo "ERROR: bot_token пустой." >&2; exit 2; }
}

write_config_json() {
  CFG_DIR="/opt/etc/keenetic-tg-bot"
  mkdir -p "$CFG_DIR"
  CFG="$CFG_DIR/config.json"
  cat > "$CFG" <<EOF
{
  "bot_token": "${TG_TOKEN}",
  "admins": [${TG_ADMIN_ID}],
  "allow_chats": [],
  "command_timeout_sec": 30,
  "poll_interval_sec": 2,
  "monitor": {"enabled": true, "interval_sec": 60, "opkg_update_interval_sec": 86400, "internet_check_interval_sec": 300, "cpu_load_threshold": 3.5, "disk_free_mb_threshold": 200},
  "notify": {"updates": true, "service_down": true, "internet_down": true, "log_errors": true, "cooldown_sec": 300}
}
EOF
  echo "Saved config: $CFG" >&2
}

installed_bot() { [ -x /opt/etc/init.d/S99keenetic-tg-bot ] && [ -f /opt/keenetic-tg-bot/bot.py ]; }
installed_hydra() { has_cmd neo || has_cmd hr || is_exec /opt/bin/neo || is_exec /opt/bin/hr; }
installed_nfqws2() { is_exec /opt/etc/init.d/S51nfqws2 || has_cmd nfqws2 || is_exec /opt/bin/nfqws2; }
installed_nfqwsweb() { [ -f /opt/etc/nfqws_web.conf ] || [ -d /opt/share/nfqws-web ] || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^nfqws-keenetic-web '; }
installed_awg() { is_exec /opt/etc/init.d/S99awg-manager || has_cmd awg-manager || is_exec /opt/bin/awg-manager; }
installed_cron() { is_exec /opt/etc/init.d/S10cron || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^cron '; }

say_status() {
  echo "==== DETECTED ===="
  printf "BOT:        %s\n" "$(installed_bot && echo installed || echo missing)"
  printf "HydraRoute:  %s\n" "$(installed_hydra && echo installed || echo missing)"
  printf "NFQWS2:      %s\n" "$(installed_nfqws2 && echo installed || echo missing)"
  printf "NFQWS web:   %s\n" "$(installed_nfqwsweb && echo installed || echo missing)"
  printf "AWG Manager: %s\n" "$(installed_awg && echo installed || echo missing)"
  printf "cron:        %s\n" "$(installed_cron && echo installed || echo missing)"
  echo "==============="
}

install_base() { /opt/bin/opkg update; /opt/bin/opkg install ca-certificates curl coreutils-nohup; }

install_bot() {
  echo "[BOT] install python + deps..."
  /opt/bin/opkg update
  /opt/bin/opkg install python3 python3-pip ca-certificates curl coreutils-nohup
  python3 -m pip install --upgrade pip
  python3 -m pip install --no-cache-dir pyTelegramBotAPI

  SRC_DIR="$(ensure_repo_files)"
  mkdir -p /opt/keenetic-tg-bot /opt/etc/init.d /opt/etc/keenetic-tg-bot
  cp -f "$SRC_DIR/bot.py" /opt/keenetic-tg-bot/bot.py
  chmod +x /opt/keenetic-tg-bot/bot.py
  cp -f "$SRC_DIR/S99keenetic-tg-bot" /opt/etc/init.d/S99keenetic-tg-bot
  chmod +x /opt/etc/init.d/S99keenetic-tg-bot

  if [ "$RECONFIG" -eq 1 ] || [ ! -f /opt/etc/keenetic-tg-bot/config.json ]; then
    prompt_token_admin
    write_config_json
  fi

  /opt/etc/init.d/S99keenetic-tg-bot restart || true
}

install_hydra() { echo "[HydraRoute Neo] install..."; /opt/bin/opkg update; /opt/bin/opkg install curl; curl -Ls https://ground-zerro.github.io/release/keenetic/install-neo.sh | sh; }
install_nfqws2() { echo "[NFQWS2] install..."; /opt/bin/opkg update; /opt/bin/opkg install ca-certificates wget-ssl; /opt/bin/opkg remove wget-nossl || true; mkdir -p /opt/etc/opkg; echo 'src/gz nfqws2-keenetic https://nfqws.github.io/nfqws2-keenetic/aarch64' > /opt/etc/opkg/nfqws2-keenetic.conf; /opt/bin/opkg update; /opt/bin/opkg install nfqws2-keenetic; }
install_nfqwsweb() { echo "[NFQWS web] install..."; /opt/bin/opkg update; /opt/bin/opkg install ca-certificates wget-ssl; /opt/bin/opkg remove wget-nossl || true; mkdir -p /opt/etc/opkg; echo 'src/gz nfqws-keenetic-web https://nfqws.github.io/nfqws-keenetic-web/all' > /opt/etc/opkg/nfqws-keenetic-web.conf; /opt/bin/opkg update; /opt/bin/opkg install nfqws-keenetic-web; for s in /opt/etc/init.d/S*php* /opt/etc/init.d/S*lighttpd /opt/etc/init.d/S*nginx; do [ -x "$s" ] && "$s" start >/dev/null 2>&1 || true; done; }
install_awg() { echo "[AWG Manager] install..."; /opt/bin/opkg update; /opt/bin/opkg install ca-certificates curl; curl -sL https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh | sh; }
install_cron() { echo "[cron] install..."; /opt/bin/opkg update; /opt/bin/opkg install cron; /opt/etc/init.d/S10cron start || true; }

setup_weekly_updates() {
  echo "[weekly updates] setup every Thu 06:00"
  UPD="/opt/bin/weekly-update.sh"
  mkdir -p /opt/bin /opt/var/log
  cat > "$UPD" <<'SH'
#!/bin/sh
LOG="/opt/var/log/weekly-update.log"
mkdir -p /opt/var/log
REPO="Stak646/keenetic-TG-Bot"
BRANCH="main"
raw() { echo "https://raw.githubusercontent.com/${REPO}/${BRANCH}/$1"; }
update_bot_files() {
  TMP="/opt/tmp/keenetic-tg-bot-weekly"
  mkdir -p "$TMP"
  curl -fsSL "$(raw bot.py)" -o "$TMP/bot.py" || return 0
  curl -fsSL "$(raw S99keenetic-tg-bot)" -o "$TMP/S99keenetic-tg-bot" || return 0
  mkdir -p /opt/keenetic-tg-bot /opt/etc/init.d
  cp -f "$TMP/bot.py" /opt/keenetic-tg-bot/bot.py
  chmod +x /opt/keenetic-tg-bot/bot.py
  cp -f "$TMP/S99keenetic-tg-bot" /opt/etc/init.d/S99keenetic-tg-bot
  chmod +x /opt/etc/init.d/S99keenetic-tg-bot
}
{
  echo "===== $(date) weekly update ====="
  opkg update
  opkg upgrade hrneo hrweb nfqws2-keenetic nfqws-keenetic-web awg-manager coreutils-nohup python3 python3-pip || true
  update_bot_files || true
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
  grep -Fq "$UPD" "$CRONFILE" || echo "$LINE" >> "$CRONFILE"
  /opt/etc/init.d/S10cron restart || true
  echo "[weekly updates] done. log: /opt/var/log/weekly-update.log"
}

# args
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=1 ;;
    --token) shift; TG_TOKEN="$1" ;;
    --admin) shift; TG_ADMIN_ID="$1" ;;
    --reconfig) RECONFIG=1 ;;
    --bot) WITH_BOT=1 ;;
    --hydra) WITH_HYDRA=1 ;;
    --nfqws2) WITH_NFQWS2=1 ;;
    --nfqwsweb) WITH_NFQWSWEB=1 ;;
    --awg) WITH_AWG=1 ;;
    --cron) WITH_CRON=1 ;;
    --weekly) WITH_WEEKLY=1 ;;
  esac
  shift
done

need_opt
install_base
say_status

FLAGS="${WITH_BOT}${WITH_HYDRA}${WITH_NFQWS2}${WITH_NFQWSWEB}${WITH_AWG}${WITH_CRON}${WITH_WEEKLY}"

if [ "$FLAGS" = "0000000" ]; then
  echo "Interactive mode."
  installed_hydra || { ask "Install HydraRoute Neo?" && WITH_HYDRA=1; }
  installed_nfqws2 || { ask "Install NFQWS2?" && WITH_NFQWS2=1; }
  (installed_nfqws2 && installed_nfqwsweb) || { installed_nfqws2 && ask "Install NFQWS web UI?" && WITH_NFQWSWEB=1; } || true
  installed_awg || { ask "Install AWG Manager?" && WITH_AWG=1; }
  installed_cron || { ask "Install cron (for scheduling updates)?" && WITH_CRON=1; }
  [ "$WITH_CRON" -eq 1 ] && { ask "Setup weekly updates (Thu 06:00)?" && WITH_WEEKLY=1; } || true
  installed_bot || { ask "Install Telegram bot service?" && WITH_BOT=1; }
else
  if [ "$ASSUME_YES" -eq 1 ] && [ "$FLAGS" = "0000000" ]; then
    installed_hydra || WITH_HYDRA=1
    installed_nfqws2 || WITH_NFQWS2=1
    installed_nfqwsweb || WITH_NFQWSWEB=1
    installed_awg || WITH_AWG=1
    installed_cron || WITH_CRON=1
    WITH_WEEKLY=1
    installed_bot || WITH_BOT=1
  fi
fi

[ "$WITH_HYDRA" -eq 1 ] && install_hydra
[ "$WITH_NFQWS2" -eq 1 ] && install_nfqws2
[ "$WITH_NFQWSWEB" -eq 1 ] && install_nfqwsweb
[ "$WITH_AWG" -eq 1 ] && install_awg
[ "$WITH_CRON" -eq 1 ] && install_cron
[ "$WITH_WEEKLY" -eq 1 ] && setup_weekly_updates
[ "$WITH_BOT" -eq 1 ] && install_bot

echo "DONE."
echo "Config: /opt/etc/keenetic-tg-bot/config.json"
echo "Logs:   /opt/var/log/keenetic-tg-bot.log"
