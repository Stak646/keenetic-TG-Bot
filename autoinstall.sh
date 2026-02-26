#!/bin/sh
# Keenetic TG Bot autoinstall (Entware /opt)
# - i18n: RU/EN selection at start (--lang ru|en)
# - quiet by default (prints only results); full logs with --debug
# - works with curl | sh (reads input from /dev/tty)
#
set -e

export PATH="/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

# -------- settings --------
REPO="Stak646/keenetic-TG-Bot"
BRANCH="main"

LANG_SEL=""
DEBUG=0
ASSUME_YES=0

WITH_BOT=0
WITH_HYDRA=0
WITH_NFQWS2=0
WITH_NFQWSWEB=0
WITH_AWG=0
WITH_CRON=0
WITH_WEEKLY=0

TG_TOKEN=""
TG_ADMIN_ID=""
RECONFIG=0

LOGDIR="/opt/var/log"
LOGFILE="$LOGDIR/keenetic-tg-bot-install.log"

TTY="/dev/tty"

# -------- helpers --------
t() {
  # t KEY [ru] [en]
  key="$1"; ru="$2"; en="$3"
  case "$LANG_SEL" in
    ru) printf "%s" "$ru" ;;
    en) printf "%s" "$en" ;;
    *)  printf "%s" "$en" ;;
  esac
}

say() {
  # print message
  printf "%s\n" "$*"
}

dbg() {
  [ "$DEBUG" -eq 1 ] && printf "[debug] %s\n" "$*" >&2 || true
}

runq() {
  # runq "description" command...
  desc="$1"; shift
  mkdir -p "$LOGDIR"
  if [ "$DEBUG" -eq 1 ]; then
    say "$desc"
    "$@" 2>&1 | tee -a "$LOGFILE"
    return "${PIPESTATUS:-0}"
  else
    "$@" >> "$LOGFILE" 2>&1
  fi
}

ok()   { say "✅ $*"; }
warn() { say "⚠️ $*"; }
fail() { say "❌ $*"; }

read_tty() {
  # read_tty VAR PROMPT
  var="$1"; prompt="$2"
  if [ -r "$TTY" ]; then
    printf "%s" "$prompt" > "$TTY"
    read "$var" < "$TTY" || true
  else
    printf "%s" "$prompt"
    read "$var" || true
  fi
}

ask() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  if [ -r "$TTY" ]; then
    printf "%s [y/N]: " "$1" > "$TTY"
    read ans < "$TTY" || true
  else
    printf "%s [y/N]: " "$1"
    read ans || true
  fi
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

need_entware() {
  if [ ! -x /opt/bin/opkg ]; then
    fail "$(t X "Entware не найден (/opt/bin/opkg). Установи Entware и повтори." "Entware not found (/opt/bin/opkg). Install Entware first.")"
    exit 1
  fi
}

raw_url() { echo "https://raw.githubusercontent.com/$REPO/$BRANCH/$1"; }

fetch_file() {
  f="$1"; dest="$2"
  url="$(raw_url "$f")"
  mkdir -p "$(dirname "$dest")"
  if [ "$DEBUG" -eq 1 ]; then
    say "download: $url -> $dest"
  else
    dbg "download: $url -> $dest"
  fi
  curl -fsSL "$url" -o "$dest" >> "$LOGFILE" 2>&1
}

# prefer /etc, fallback /opt/etc; create /etc symlink if possible
pick_cfg_dir() {
  CFG_DIR="/etc/keenetic-tg-bot"
  if [ ! -d /etc ] || [ ! -w /etc ]; then
    CFG_DIR="/opt/etc/keenetic-tg-bot"
  fi
  echo "$CFG_DIR"
}

ensure_repo_files() {
  TMP="/opt/tmp/keenetic-tg-bot-installer"
  rm -rf "$TMP" >/dev/null 2>&1 || true
  mkdir -p "$TMP"
  fetch_file "bot.py" "$TMP/bot.py"
  fetch_file "config.example.json" "$TMP/config.example.json"
  fetch_file "S99keenetic-tg-bot" "$TMP/S99keenetic-tg-bot"
  fetch_file "install.sh" "$TMP/install.sh"
  echo "$TMP"
}

cleanup() {
  # remove temporary files
  rm -rf /opt/tmp/keenetic-tg-bot-installer >/dev/null 2>&1 || true
  rm -rf /opt/tmp/keenetic-tg-bot-weekly >/dev/null 2>&1 || true
}

select_language() {
  [ -n "$LANG_SEL" ] && return 0
  # auto: if tty exists
  if [ -r "$TTY" ]; then
    printf "\n1) Русский\n2) English\n" > "$TTY"
    printf "Select language / Выберите язык [1/2]: " > "$TTY"
    read choice < "$TTY" || true
    case "$choice" in
      1) LANG_SEL="ru" ;;
      2) LANG_SEL="en" ;;
      *) LANG_SEL="en" ;;
    esac
  else
    LANG_SEL="en"
  fi
}

# -------- detection --------
has_cmd() { command -v "$1" >/dev/null 2>&1; }
is_exec() { [ -x "$1" ]; }

installed_bot() {
  CFG_DIR="$(pick_cfg_dir)"
  [ -f "$CFG_DIR/bot.py" ] && [ -x /opt/etc/init.d/S99keenetic-tg-bot ]
}
installed_hydra() { has_cmd neo || has_cmd hr || is_exec /opt/bin/neo || is_exec /opt/bin/hr; }
installed_nfqws2() { is_exec /opt/etc/init.d/S51nfqws2 || has_cmd nfqws2 || is_exec /opt/bin/nfqws2; }
installed_nfqwsweb() { [ -f /opt/etc/nfqws_web.conf ] || [ -d /opt/share/nfqws-web ] || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^nfqws-keenetic-web '; }
installed_awg() { is_exec /opt/etc/init.d/S99awg-manager || has_cmd awg-manager || is_exec /opt/bin/awg-manager; }
installed_cron() { is_exec /opt/etc/init.d/S10cron || /opt/bin/opkg list-installed 2>/dev/null | grep -q '^cron '; }

say_detected() {
  say "==== DETECTED ===="
  say "BOT:        $(installed_bot && echo installed || echo missing)"
  say "HydraRoute:  $(installed_hydra && echo installed || echo missing)"
  say "NFQWS2:      $(installed_nfqws2 && echo installed || echo missing)"
  say "NFQWS web:   $(installed_nfqwsweb && echo installed || echo missing)"
  say "AWG Manager: $(installed_awg && echo installed || echo missing)"
  say "cron:        $(installed_cron && echo installed || echo missing)"
  say "==============="
}

# -------- installers --------
install_base() {
  runq "$(t X "Обновляю списки opkg..." "Updating opkg lists...")" /opt/bin/opkg update || true
  runq "$(t X "Устанавливаю базовые утилиты..." "Installing base utilities...")" /opt/bin/opkg install ca-certificates curl coreutils-nohup || true
}

prompt_token_admin() {
  [ -n "$TG_TOKEN" ] && [ -n "$TG_ADMIN_ID" ] && return 0
  read_tty TG_TOKEN "$(t X "Введите bot_token: " "Enter bot_token: ")"
  read_tty TG_ADMIN_ID "$(t X "Введите admin user_id (число): " "Enter admin user_id (number): ")"
  case "$TG_ADMIN_ID" in ''|*[!0-9]*) fail "$(t X "admin user_id должен быть числом" "admin user_id must be a number")"; exit 2 ;; esac
  [ -z "$TG_TOKEN" ] && { fail "$(t X "bot_token пустой" "bot_token is empty")"; exit 2; }
}

write_config_json() {
  CFG_DIR="$(pick_cfg_dir)"
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
}

deploy_bot_files() {
  SRC_DIR="$1"
  CFG_DIR="$(pick_cfg_dir)"
  mkdir -p "$CFG_DIR" /opt/etc/init.d

  cp -f "$SRC_DIR/bot.py" "$CFG_DIR/bot.py"
  chmod +x "$CFG_DIR/bot.py"

  cp -f "$SRC_DIR/S99keenetic-tg-bot" /opt/etc/init.d/S99keenetic-tg-bot
  chmod +x /opt/etc/init.d/S99keenetic-tg-bot

  # create /etc symlink if installed into /opt/etc and /etc is writable
  if [ "$CFG_DIR" = "/opt/etc/keenetic-tg-bot" ] && [ ! -e /etc/keenetic-tg-bot ] && [ -w /etc ]; then
    ln -s /opt/etc/keenetic-tg-bot /etc/keenetic-tg-bot >/dev/null 2>&1 || true
  fi
}

install_bot() {
  ok "$(t X "Установка бота..." "Installing bot...")"
  runq "opkg python" /opt/bin/opkg install python3 python3-pip ca-certificates curl coreutils-nohup || { fail "python/opkg"; return 1; }

  # pip
  runq "pip upgrade" python3 -m pip install --upgrade pip || true
  runq "pip pyTelegramBotAPI" python3 -m pip install --no-cache-dir pyTelegramBotAPI || { fail "pip pyTelegramBotAPI"; return 1; }

  SRC_DIR="$(ensure_repo_files)"
  deploy_bot_files "$SRC_DIR"

  CFG_DIR="$(pick_cfg_dir)"
  if [ "$RECONFIG" -eq 1 ] || [ ! -f "$CFG_DIR/config.json" ]; then
    prompt_token_admin
    write_config_json
    ok "$(t X "Конфиг сохранён" "Config saved")"
  fi

  runq "bot restart" /opt/etc/init.d/S99keenetic-tg-bot restart || true
  if /opt/etc/init.d/S99keenetic-tg-bot status >/dev/null 2>&1; then
    ok "$(t X "Бот запущен" "Bot started")"
  else
    warn "$(t X "Бот не запустился. См. лог: /opt/var/log/keenetic-tg-bot.log" "Bot did not start. See log: /opt/var/log/keenetic-tg-bot.log")"
  fi
  cleanup
}

install_hydra() {
  ok "$(t X "Установка HydraRoute Neo..." "Installing HydraRoute Neo...")"
  if runq "hydra" sh -c 'opkg update && opkg install curl && curl -Ls "https://ground-zerro.github.io/release/keenetic/install-neo.sh" | sh'; then
    ok "$(t X "HydraRoute Neo установлен" "HydraRoute Neo installed")"
  else
    fail "$(t X "HydraRoute Neo установка не удалась" "HydraRoute Neo install failed")"
    return 1
  fi
}

install_nfqws2() {
  ok "$(t X "Установка NFQWS2..." "Installing NFQWS2...")"
  if runq "nfqws2" sh -c 'opkg update && opkg install ca-certificates wget-ssl && opkg remove wget-nossl || true; mkdir -p /opt/etc/opkg; echo "src/gz nfqws2-keenetic https://nfqws.github.io/nfqws2-keenetic/aarch64" > /opt/etc/opkg/nfqws2-keenetic.conf; opkg update; opkg install nfqws2-keenetic'; then
    ok "$(t X "NFQWS2 установлен" "NFQWS2 installed")"
  else
    fail "$(t X "NFQWS2 установка не удалась" "NFQWS2 install failed")"
    return 1
  fi
}

start_web_stack_if_present() {
  for s in /opt/etc/init.d/S*php* /opt/etc/init.d/S*lighttpd /opt/etc/init.d/S*nginx; do
    [ -x "$s" ] || continue
    runq "web stack" "$s" start || true
  done
}

install_nfqwsweb() {
  # NFQWS web requires NFQWS2
  installed_nfqws2 || WITH_NFQWS2=1

  ok "$(t X "Установка NFQWS web..." "Installing NFQWS web...")"
  if runq "nfqwsweb" sh -c 'opkg update && opkg install ca-certificates wget-ssl && opkg remove wget-nossl || true; mkdir -p /opt/etc/opkg; echo "src/gz nfqws-keenetic-web https://nfqws.github.io/nfqws-keenetic-web/all" > /opt/etc/opkg/nfqws-keenetic-web.conf; opkg update; opkg install nfqws-keenetic-web'; then
    start_web_stack_if_present
    ok "$(t X "NFQWS web установлен (порт 90)" "NFQWS web installed (port 90)")"
  else
    fail "$(t X "NFQWS web установка не удалась" "NFQWS web install failed")"
    return 1
  fi
}

install_awg() {
  ok "$(t X "Установка AWG Manager..." "Installing AWG Manager...")"
  if runq "awg" sh -c 'opkg update && opkg install ca-certificates curl && curl -sL "https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh" | sh'; then
    ok "$(t X "AWG Manager установлен" "AWG Manager installed")"
  else
    fail "$(t X "AWG Manager установка не удалась" "AWG Manager install failed")"
    return 1
  fi
}

install_cron() {
  ok "$(t X "Установка cron..." "Installing cron...")"
  if runq "cron" sh -c 'opkg update && opkg install cron && /opt/etc/init.d/S10cron start || true'; then
    ok "$(t X "cron установлен" "cron installed")"
  else
    fail "$(t X "cron установка не удалась" "cron install failed")"
    return 1
  fi
}

setup_weekly_updates() {
  ok "$(t X "Настраиваю еженедельные обновления (Чт 06:00)..." "Setting weekly updates (Thu 06:00)...")"
  runq "weekly setup" sh -c 'mkdir -p /opt/bin /opt/var/log; cat > /opt/bin/weekly-update.sh <<'\''SH'\'' 
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

  CFG="/etc/keenetic-tg-bot"
  [ -d /etc ] && [ -w /etc ] || CFG="/opt/etc/keenetic-tg-bot"
  mkdir -p "$CFG" /opt/etc/init.d
  cp -f "$TMP/bot.py" "$CFG/bot.py"
  chmod +x "$CFG/bot.py"
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
} >> "$LOG" 2>&1
SH
chmod +x /opt/bin/weekly-update.sh
touch /opt/etc/crontab
grep -Fq "/opt/bin/weekly-update.sh" /opt/etc/crontab || echo "0 6 * * 4 root /opt/bin/weekly-update.sh" >> /opt/etc/crontab
/opt/etc/init.d/S10cron restart || true'
  ok "$(t X "Еженедельные обновления настроены" "Weekly updates configured")"
}

usage() {
  say "autoinstall.sh options:"
  say "  --lang ru|en"
  say "  --debug"
  say "  --yes"
  say "  --bot --token <token> --admin <id> [--reconfig]"
  say "  --hydra --nfqws2 --nfqwsweb --awg --cron --weekly"
}

# -------- args --------
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) shift; LANG_SEL="$1" ;;
    --debug|-debug) DEBUG=1 ;;
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
    -h|--help) usage; exit 0 ;;
  esac
  shift
done

need_entware
select_language

mkdir -p "$LOGDIR"
: > "$LOGFILE" || true

install_base
say_detected

FLAGS="${WITH_BOT}${WITH_HYDRA}${WITH_NFQWS2}${WITH_NFQWSWEB}${WITH_AWG}${WITH_CRON}${WITH_WEEKLY}"

if [ "$FLAGS" = "0000000" ]; then
  say "$(t X "Интерактивный режим." "Interactive mode.")"
  installed_hydra || { ask "$(t X "Установить HydraRoute Neo?" "Install HydraRoute Neo?")" && WITH_HYDRA=1; }
  installed_nfqws2 || { ask "$(t X "Установить NFQWS2?" "Install NFQWS2?")" && WITH_NFQWS2=1; }
  installed_nfqwsweb || { ask "$(t X "Установить NFQWS web UI?" "Install NFQWS web UI?")" && WITH_NFQWSWEB=1; }
  installed_awg || { ask "$(t X "Установить AWG Manager?" "Install AWG Manager?")" && WITH_AWG=1; }
  installed_cron || { ask "$(t X "Установить cron (для расписаний)?" "Install cron (for scheduling)?" )" && WITH_CRON=1; }
  [ "$WITH_CRON" -eq 1 ] && { ask "$(t X "Настроить автообновление (Чт 06:00)?" "Setup weekly update (Thu 06:00)?" )" && WITH_WEEKLY=1; } || true
  installed_bot || { ask "$(t X "Установить Telegram-бот?" "Install Telegram bot service?" )" && WITH_BOT=1; }
else
  # if user explicitly picked nfqwsweb, force nfqws2
  [ "$WITH_NFQWSWEB" -eq 1 ] && WITH_NFQWS2=1
fi

[ "$ASSUME_YES" -eq 1 ] && [ "$FLAGS" = "0000000" ] && {
  installed_hydra || WITH_HYDRA=1
  installed_nfqws2 || WITH_NFQWS2=1
  installed_nfqwsweb || WITH_NFQWSWEB=1
  installed_awg || WITH_AWG=1
  installed_cron || WITH_CRON=1
  WITH_WEEKLY=1
  installed_bot || WITH_BOT=1
}

# -------- execute --------
[ "$WITH_HYDRA" -eq 1 ] && install_hydra || true
[ "$WITH_NFQWS2" -eq 1 ] && install_nfqws2 || true
[ "$WITH_NFQWSWEB" -eq 1 ] && install_nfqwsweb || true
[ "$WITH_AWG" -eq 1 ] && install_awg || true
[ "$WITH_CRON" -eq 1 ] && install_cron || true
[ "$WITH_WEEKLY" -eq 1 ] && setup_weekly_updates || true
[ "$WITH_BOT" -eq 1 ] && install_bot || true

ok "$(t X "Готово." "Done.")"
ok "$(t X "Лог установки: /opt/var/log/keenetic-tg-bot-install.log" "Install log: /opt/var/log/keenetic-tg-bot-install.log")"
cleanup
