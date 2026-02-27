#!/bin/sh
# Keenetic TG Bot autoinstall (Entware /opt)
# RU/EN language selection at start (--lang ru|en)
# quiet by default (prints only results); verbose with --debug (or -debug)
# works with curl | sh (reads interactive input from /dev/tty)
set -e

export PATH="/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

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

# Force update bot files even if already installed
UPDATE_BOT=0

TG_TOKEN=""
TG_ADMIN_ID=""
RECONFIG=0

LOGDIR="/opt/var/log"
LOGFILE="$LOGDIR/keenetic-tg-bot-install.log"
TTY="/dev/tty"

t() { # t RU EN
  case "$LANG_SEL" in
    ru) printf "%s" "$1" ;;
    *)  printf "%s" "$2" ;;
  esac
}

say() { printf "%s\n" "$*"; }
ok()  { say "✅ $*"; }
warn(){ say "⚠️ $*"; }
fail(){ say "❌ $*"; }
dbg() { [ "$DEBUG" -eq 1 ] && printf "[debug] %s\n" "$*" >&2 || true; }

runq() { # runq "label" cmd...
  label="$1"; shift
  mkdir -p "$LOGDIR"
  if [ "$DEBUG" -eq 1 ]; then
    say "[RUN] $label"
    tmp="/opt/tmp/.runq.$$"
    rm -f "$tmp" >/dev/null 2>&1 || true
    ( "$@" 2>&1; echo $? >"$tmp" ) | tee -a "$LOGFILE"
    rc="$(cat "$tmp" 2>/dev/null || echo 1)"
    rm -f "$tmp" >/dev/null 2>&1 || true
    return "$rc"
  else
    "$@" >>"$LOGFILE" 2>&1 || return $?
  fi
}

read_tty() {
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
    fail "$(t "Entware не найден (/opt/bin/opkg). Установи Entware и повтори." "Entware not found (/opt/bin/opkg). Install Entware first.")"
    exit 1
  fi
}

select_language() {
  [ -n "$LANG_SEL" ] && return 0
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

pick_cfg_dir() {
  # /etc on Keenetic is often read-only -> probe by creating a temp file
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

raw_url() {
  # CDN cache can lag; add cache-busting query
  ts="$(date +%s)"
  echo "https://raw.githubusercontent.com/$REPO/$BRANCH/$1?t=$ts"
}

fetch_file() {
  f="$1"; dest="$2"
  url="$(raw_url "$f")"
  mkdir -p "$(dirname "$dest")"
  [ "$DEBUG" -eq 1 ] && say "download: $url -> $dest" || true
  # no-cache headers for safety
  curl -fsSL -H "Cache-Control: no-cache" -H "Pragma: no-cache" "$url" -o "$dest" >>"$LOGFILE" 2>&1
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
  rm -rf /opt/tmp/keenetic-tg-bot-installer >/dev/null 2>&1 || true
  rm -rf /opt/tmp/keenetic-tg-bot-weekly >/dev/null 2>&1 || true
}

has_cmd() { command -v "$1" >/dev/null 2>&1; }
is_exec() { [ -x "$1" ]; }

installed_bot() {
  CFG_DIR="$(pick_cfg_dir)"
  [ -f "$CFG_DIR/bot.py" ] && [ -x /opt/etc/init.d/S99keenetic-tg-bot ]
}
installed_hydra()    { has_cmd neo || has_cmd hr || is_exec /opt/bin/neo || is_exec /opt/bin/hr; }
installed_nfqws2()   { is_exec /opt/etc/init.d/S51nfqws2 || has_cmd nfqws2 || is_exec /opt/bin/nfqws2; }
installed_nfqwsweb() { [ -f /opt/etc/nfqws_web.conf ] || [ -d /opt/share/nfqws-web ] || opkg list-installed 2>/dev/null | grep -q '^nfqws-keenetic-web '; }
installed_awg()      { is_exec /opt/etc/init.d/S99awg-manager || has_cmd awg-manager || is_exec /opt/bin/awg-manager; }
installed_cron()     { is_exec /opt/etc/init.d/S10cron || opkg list-installed 2>/dev/null | grep -q '^cron '; }

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

install_base() {
  runq "opkg update" opkg update || true
  runq "base packages" opkg install ca-certificates curl coreutils-nohup || true
}

prompt_token_admin() {
  [ -n "$TG_TOKEN" ] && [ -n "$TG_ADMIN_ID" ] && return 0
  say "$(t "Telegram Bot Token: @BotFather → /newbot" "Telegram Bot Token: @BotFather → /newbot")" >&2
  read_tty TG_TOKEN "$(t "Введите bot_token: " "Enter bot_token: ")"
  say "$(t "Telegram user_id: проще всего @userinfobot (Id: ...)" "Telegram user_id: easiest via @userinfobot (Id: ...)")" >&2
  read_tty TG_ADMIN_ID "$(t "Введите admin user_id (число): " "Enter admin user_id (number): ")"
  case "$TG_ADMIN_ID" in
    ''|*[!0-9]*) fail "$(t "admin user_id должен быть числом" "admin user_id must be a number")"; exit 2 ;;
  esac
  [ -z "$TG_TOKEN" ] && { fail "$(t "bot_token пустой" "bot_token is empty")"; exit 2; }
}

write_config_json() {
  CFG_DIR="$(pick_cfg_dir)"
  mkdir -p "$CFG_DIR"
  cat > "$CFG_DIR/config.json" <<EOF
{
  "bot_token": "$TG_TOKEN",
  "admins": [$TG_ADMIN_ID],
  "monitor": {
    "enabled": true
  },
  "notify": {
    "cooldown_sec": 300,
    "disk_interval_sec": 21600,
    "load_interval_sec": 1800
  },
  "debug": {
    "enabled": false,
    "log_output_max": 5000
  }
}
EOF
}

install_bot() {
  TMP="$(ensure_repo_files)"
  # install/update files and service
  if runq "bot install/update" sh -c "cd '$TMP' && sh ./install.sh"; then
    ok "$(t "Файлы бота обновлены/установлены" "Bot files installed/updated")"
  else
    fail "$(t "Установка бота не удалась (см. лог)" "Bot install failed (see log)")"
    return 1
  fi

  CFG_DIR="$(pick_cfg_dir)"
  if [ "$RECONFIG" -eq 1 ] || [ ! -f "$CFG_DIR/config.json" ]; then
    prompt_token_admin
    write_config_json
    ok "$(t "Конфиг бота записан" "Bot config written")"
  else
    ok "$(t "Конфиг сохранён (без изменений)" "Config preserved (unchanged)")"
  fi

  # restart service after file update/config
  if [ -x /opt/etc/init.d/S99keenetic-tg-bot ]; then
    runq "bot restart" /opt/etc/init.d/S99keenetic-tg-bot restart || true
  fi
}

install_hydra() {
  if runq "hydra neo" sh -c 'opkg update && opkg install curl && curl -Ls "https://ground-zerro.github.io/release/keenetic/install-neo.sh" | sh'; then
    ok "$(t "HydraRoute Neo установлен" "HydraRoute Neo installed")"
  else
    fail "$(t "HydraRoute Neo установка не удалась" "HydraRoute Neo install failed")"
    return 1
  fi
}

install_nfqws2() {
  if runq "nfqws2" sh -c 'opkg update && opkg install ca-certificates wget-ssl && opkg remove wget-nossl || true; mkdir -p /opt/etc/opkg; echo "src/gz nfqws2-keenetic https://nfqws.github.io/nfqws2-keenetic/aarch64" > /opt/etc/opkg/nfqws2-keenetic.conf; opkg update; opkg install nfqws2-keenetic'; then
    ok "$(t "NFQWS2 установлен" "NFQWS2 installed")"
  else
    fail "$(t "NFQWS2 установка не удалась" "NFQWS2 install failed")"
    return 1
  fi
}

start_web_stack_if_present() {
  for s in /opt/etc/init.d/S*php* /opt/etc/init.d/S*lighttpd /opt/etc/init.d/S*nginx; do
    [ -x "$s" ] || continue
    runq "web stack start" "$s" start || true
  done
}

install_nfqwsweb() {
  installed_nfqws2 || install_nfqws2 || true
  if runq "nfqws web" sh -c 'opkg update && opkg install ca-certificates wget-ssl && opkg remove wget-nossl || true; mkdir -p /opt/etc/opkg; echo "src/gz nfqws-keenetic-web https://nfqws.github.io/nfqws-keenetic-web/all" > /opt/etc/opkg/nfqws-keenetic-web.conf; opkg update; opkg install nfqws-keenetic-web'; then
    start_web_stack_if_present
    ok "$(t "NFQWS web установлен (порт 90)" "NFQWS web installed (port 90)")"
  else
    fail "$(t "NFQWS web установка не удалась" "NFQWS web install failed")"
    return 1
  fi
}

install_awg() {
  if runq "awg manager" sh -c 'opkg update && opkg install ca-certificates curl && curl -sL "https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh" | sh'; then
    ok "$(t "AWG Manager установлен" "AWG Manager installed")"
  else
    fail "$(t "AWG Manager установка не удалась" "AWG Manager install failed")"
    return 1
  fi
}

install_cron() {
  if runq "cron" sh -c 'opkg update && opkg install cron && /opt/etc/init.d/S10cron start || true'; then
    ok "$(t "cron установлен" "cron installed")"
  else
    fail "$(t "cron установка не удалась" "cron install failed")"
    return 1
  fi
}

setup_weekly_updates() {
  if runq "weekly setup" sh -c '
    mkdir -p /opt/bin /opt/var/log
    cat > /opt/bin/weekly-update.sh <<'"'"'SH'"'"'
#!/bin/sh
LOG="/opt/var/log/weekly-update.log"
mkdir -p /opt/var/log
REPO="Stak646/keenetic-TG-Bot"
BRANCH="main"
raw() { echo "https://raw.githubusercontent.com/${REPO}/${BRANCH}/$1?t=$(date +%s)"; }

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

update_bot_files() {
  TMP="/opt/tmp/keenetic-tg-bot-weekly"
  rm -rf "$TMP" >/dev/null 2>&1 || true
  mkdir -p "$TMP"
  curl -fsSL -H "Cache-Control: no-cache" -H "Pragma: no-cache" "$(raw bot.py)" -o "$TMP/bot.py" || return 0
  curl -fsSL -H "Cache-Control: no-cache" -H "Pragma: no-cache" "$(raw S99keenetic-tg-bot)" -o "$TMP/S99keenetic-tg-bot" || return 0
  CFG="$(pick_cfg_dir)"
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
    /opt/etc/init.d/S10cron restart || true
  '; then
    ok "$(t "Еженедельные обновления настроены (Чт 06:00)" "Weekly updates configured (Thu 06:00)")"
  else
    warn "$(t "Не удалось настроить weekly update" "Failed to configure weekly update")"
  fi
}

usage() {
  say "Options:"
  say " --lang ru|en"
  say " --debug | -debug"
  say " --yes"
  say " --bot --token <token> --admin <id> [--reconfig]"
  say " --update-bot         (force update bot.py + init even if already installed)"
  say " --hydra --nfqws2 --nfqwsweb --awg --cron --weekly"
}

# ---- args ----
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) shift; LANG_SEL="$1" ;;
    --debug|-debug) DEBUG=1 ;;
    --yes) ASSUME_YES=1 ;;
    --token) shift; TG_TOKEN="$1" ;;
    --admin) shift; TG_ADMIN_ID="$1" ;;
    --reconfig) RECONFIG=1 ;;
    --bot) WITH_BOT=1 ;;
    --update-bot|--update) UPDATE_BOT=1; WITH_BOT=1 ;;
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

# If nfqwsweb requested, ensure nfqws2
[ "$WITH_NFQWSWEB" -eq 1 ] && WITH_NFQWS2=1

FLAGS="${WITH_BOT}${WITH_HYDRA}${WITH_NFQWS2}${WITH_NFQWSWEB}${WITH_AWG}${WITH_CRON}${WITH_WEEKLY}${UPDATE_BOT}"
if [ "$FLAGS" = "00000000" ]; then
  say "$(t "Интерактивный режим." "Interactive mode.")"

  installed_hydra || { ask "$(t "Установить HydraRoute Neo?" "Install HydraRoute Neo?")" && WITH_HYDRA=1; }
  installed_nfqws2 || { ask "$(t "Установить NFQWS2?" "Install NFQWS2?")" && WITH_NFQWS2=1; }
  installed_nfqwsweb || { ask "$(t "Установить NFQWS web UI?" "Install NFQWS web UI?")" && WITH_NFQWSWEB=1 && WITH_NFQWS2=1; }
  installed_awg || { ask "$(t "Установить AWG Manager?" "Install AWG Manager?")" && WITH_AWG=1; }
  installed_cron || { ask "$(t "Установить cron (для расписаний)?" "Install cron (for scheduling)?")" && WITH_CRON=1; }
  [ "$WITH_CRON" -eq 1 ] && { ask "$(t "Настроить автообновление (Чт 06:00)?" "Setup weekly update (Thu 06:00)?")" && WITH_WEEKLY=1; } || true

  # Bot: if already installed -> offer update
  if installed_bot; then
    ask "$(t "Обновить файлы бота (перезаписать bot.py и init-скрипт)?" "Update bot files (overwrite bot.py and init script)?")" && WITH_BOT=1
  else
    ask "$(t "Установить Telegram-бот?" "Install Telegram bot?")" && WITH_BOT=1
  fi
fi

# ---- execute ----
[ "$WITH_HYDRA" -eq 1 ] && install_hydra || true
[ "$WITH_NFQWS2" -eq 1 ] && install_nfqws2 || true
[ "$WITH_NFQWSWEB" -eq 1 ] && install_nfqwsweb || true
[ "$WITH_AWG" -eq 1 ] && install_awg || true
[ "$WITH_CRON" -eq 1 ] && install_cron || true
[ "$WITH_WEEKLY" -eq 1 ] && setup_weekly_updates || true

# bot install/update
[ "$WITH_BOT" -eq 1 ] && install_bot || true

ok "$(t "Готово." "Done.")"
ok "$(t "Лог установки: /opt/var/log/keenetic-tg-bot-install.log" "Install log: /opt/var/log/keenetic-tg-bot-install.log")"
cleanup
