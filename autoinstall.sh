#!/bin/sh
# Auto-install for Keenetic TG bot + modules + weekly updates (Keenetic Entware /opt)
#
# Works both:
# 1) from local folder (repo cloned/copied)  -> uses local files
# 2) as one-liner: curl .../autoinstall.sh | sh -> downloads required files from GitHub raw automatically
#
# Interactive by default: detects what's installed and asks what to install.
# Non-interactive: --yes installs all missing (or selected flags).
#
# Examples:
#   sh autoinstall.sh
#   sh autoinstall.sh --yes
#   sh autoinstall.sh --repo Stak646/keenetic-TG-Bot --branch main --yes
#   sh autoinstall.sh --bot --cron --weekly
#   curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/main/autoinstall.sh | sh -s -- --yes
#
set -e

WITH_BOT=0
WITH_HYDRA=0
WITH_NFQWS2=0
WITH_NFQWSWEB=0
WITH_AWG=0
WITH_CRON=0
WITH_WEEKLY=0
ASSUME_YES=0
LOCAL_ONLY=0
TG_TOKEN=""
TG_ADMIN_ID=""
RECONFIG=0

REPO="Stak646/keenetic-TG-Bot"
BRANCH="main"

has_cmd() { command -v "$1" >/dev/null 2>&1; }
is_exec() { [ -x "$1" ]; }
is_file() { [ -f "$1" ]; }

need_opt() {
  if [ ! -d /opt ] || [ ! -x /opt/bin/opkg ]; then
    echo "ERROR: Entware (/opt + opkg) is not ready."
    echo "Install Entware on Keenetic first, then retry."
    exit 1
  fi
  export PATH="/opt/bin:/opt/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
}

raw_url() {
  # $1 file path in repo root
  echo "https://raw.githubusercontent.com/$REPO/$BRANCH/$1"
}

fetch_file() {
  # $1 filename, $2 dest
  URL="$(raw_url "$1")"
  DEST="$2"
  mkdir -p "$(dirname "$DEST")"
  echo "download: $URL -> $DEST"
  curl -fsSL "$URL" -o "$DEST"
}

ensure_repo_files() {
  # ensure bot artifacts exist locally (for bot installation)
  TMP="/opt/tmp/keenetic-tg-bot-installer"
  mkdir -p "$TMP"

  if [ "$LOCAL_ONLY" -eq 1 ]; then
    # use local files from current directory
    cp -f ./bot.py "$TMP/bot.py"
    cp -f ./config.example.json "$TMP/config.example.json"
    cp -f ./S99keenetic-tg-bot "$TMP/S99keenetic-tg-bot"
    cp -f ./install.sh "$TMP/install.sh"
    echo "$TMP"
    return
  fi

  # Always fetch свежие файлы из GitHub (важно для автообновления)
  fetch_file "bot.py" "$TMP/bot.py"
  fetch_file "config.example.json" "$TMP/config.example.json"
  fetch_file "S99keenetic-tg-bot" "$TMP/S99keenetic-tg-bot"
  fetch_file "install.sh" "$TMP/install.sh"
  echo "$TMP"
}

is_tty() { [ -t 0 ]; }

prompt_token_admin() {
  # TG_TOKEN / TG_ADMIN_ID may already be set via flags
  if [ -z "$TG_TOKEN" ]; then
    echo ""
    echo "Telegram Bot Token:"
    echo "  Получи у @BotFather (команда /newbot), потом скопируй токен вида 123456:ABC-DEF..."
    printf "Введите bot_token: "
    read TG_TOKEN || true
  fi

  if [ -z "$TG_ADMIN_ID" ]; then
    echo ""
    echo "Telegram user_id (число):"
    echo "  Проще всего — написать @userinfobot и взять поле Id."
    printf "Введите admin user_id: "
    read TG_ADMIN_ID || true
  fi

  # basic validation
  case "$TG_ADMIN_ID" in
    ''|*[!0-9]*)
      echo "ERROR: admin user_id должен быть числом."
      exit 2
      ;;
  esac

  if [ -z "$TG_TOKEN" ]; then
    echo "ERROR: bot_token пустой."
    exit 2
  fi
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
  "monitor": {
    "enabled": true,
    "interval_sec": 60,
    "opkg_update_interval_sec": 86400,
    "internet_check_interval_sec": 300,
    "cpu_load_threshold": 3.5,
    "disk_free_mb_threshold": 200
  },
  "notify": {
    "updates": true,
    "service_down": true,
    "internet_down": true,
    "log_errors": true,
    "cooldown_sec": 300
  }
}
EOF
  echo "Saved config: $CFG"
}


installed_bot() { [ -f /opt/keenetic-tg-bot/bot.py ] && [ -x /opt/etc/init.d/S99keenetic-tg-bot ]; }
installed_hydra() { has_cmd neo || has_cmd hr || is_exec /opt/bin/neo || is_exec /opt/bin/hr; }
installed_nfqws2() { is_exec /opt/etc/init.d/S51nfqws2 || has_cmd nfqws2 || is_exec /opt/bin/nfqws2; }
installed_nfqwsweb() { [ -f /opt/etc/nfqws_web.conf ] || [ -d /opt/share/nfqws-web ] || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^nfqws-keenetic-web '; }
installed_awg() { is_exec /opt/etc/init.d/S99awg-manager || has_cmd awg-manager || is_exec /opt/bin/awg-manager; }
installed_cron() { is_exec /opt/etc/init.d/S10cron || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^cron '; }

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
  if [ "$ASSUME_YES" -eq 1 ]; then return 0; fi
  printf "%s [y/N]: " "$1"
  read ans || true
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

install_base() {
  opkg update
  opkg install ca-certificates curl coreutils-nohup
}

install_bot() {
  echo "[BOT] install python + deps..."
  opkg update
  opkg install python3 python3-pip ca-certificates curl coreutils-nohup
  python3 -m pip install --upgrade pip
  python3 -m pip install --no-cache-dir pyTelegramBotAPI

  SRC_DIR="$(ensure_repo_files)"

  APP_DIR="/opt/keenetic-tg-bot"
  CFG_DIR="/opt/etc/keenetic-tg-bot"
  INIT_DIR="/opt/etc/init.d"

  mkdir -p "$APP_DIR" "$CFG_DIR" "$INIT_DIR"
  cp -f "$SRC_DIR/bot.py" "$APP_DIR/bot.py"
  chmod +x "$APP_DIR/bot.py"
  CFG="$CFG_DIR/config.json"
  if [ "$RECONFIG" -eq 1 ] || [ ! -f "$CFG" ]; then
    echo "[BOT] configuring Telegram credentials..."
    prompt_token_admin
    write_config_json
  else
    echo "Config exists: $CFG (skip). Use --reconfig to rewrite."
  fi


  cp -f "$SRC_DIR/S99keenetic-tg-bot" "$INIT_DIR/S99keenetic-tg-bot"
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

REPO="Stak646/keenetic-TG-Bot"
BRANCH="main"

raw() {
  echo "https://raw.githubusercontent.com/${REPO}/${BRANCH}/$1"
}

update_bot_files() {
  # обновляем файлы бота из GitHub (config.json не трогаем)
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

  # обновить файлы бота из GitHub
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
  echo "  sh autoinstall.sh --repo user/repo --branch main --yes"
  echo "  sh autoinstall.sh --bot --token <BOT_TOKEN> --admin <USER_ID> --yes"
  echo "  sh autoinstall.sh --reconfig   # переписать config.json"
  echo "  curl -Ls https://raw.githubusercontent.com/$REPO/$BRANCH/autoinstall.sh | sh -s -- --yes"
}

# parse args
for a in "$@"; do
  case "$a" in
    --yes) ASSUME_YES=1 ;;
    --repo) shift; REPO="$1" ;;
    --branch) shift; BRANCH="$1" ;;
    --local) LOCAL_ONLY=1 ;;
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
    -h|--help) usage; exit 0 ;;
    *) ;;
  esac
done

need_opt
install_base
say_status

FLAGS="$WITH_BOT$WITH_HYDRA$WITH_NFQWS2$WITH_NFQWSWEB$WITH_AWG$WITH_CRON$WITH_WEEKLY"

if [ "$FLAGS" = "0000000" ]; then
  echo "Interactive mode."
  installed_hydra || (ask "Install HydraRoute Neo?" && WITH_HYDRA=1)
  installed_nfqws2 || (ask "Install NFQWS2?" && WITH_NFQWS2=1)
  (installed_nfqws2 && installed_nfqwsweb) || (installed_nfqws2 && ask "Install NFQWS web UI?" && WITH_NFQWSWEB=1) || true
  installed_awg || (ask "Install AWG Manager?" && WITH_AWG=1)
  installed_cron || (ask "Install cron (for scheduling updates)?" && WITH_CRON=1)
  [ "$WITH_CRON" -eq 1 ] && (ask "Setup weekly updates (Thu 06:00)?" && WITH_WEEKLY=1) || true
  installed_bot || (ask "Install Telegram bot service?" && WITH_BOT=1)
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
echo "Edit bot config: /opt/etc/keenetic-tg-bot/config.json (bot_token/admins)"
