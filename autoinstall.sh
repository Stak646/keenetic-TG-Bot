#!/bin/sh
# Keenetic TG Bot autoinstall (Entware /opt)
# Default branch: alfa
# Usage:
#   curl -Ls https://raw.githubusercontent.com/Stak646/keenetic-TG-Bot/alfa/autoinstall.sh | sh -s -- --yes
# Options:
#   --lang ru|en
#   --debug
#   --yes                 non-interactive defaults (install only bot unless flags given)
#   --branch <name>       default: alfa
#   --token <BOT_TOKEN>
#   --admin <USER_ID>
#   --bot                 install/update bot files
#   --update-bot|--update update bot files (and restart)
#   --hydra --nfqws2 --nfqwsweb --awg --cron  install components

set -u

REPO_OWNER="Stak646"
REPO_NAME="keenetic-TG-Bot"
BRANCH="alfa"

DEBUG=0
YES=0
LANG=""
WITH_BOT=0
FORCE_UPDATE_BOT=0
WITH_HYDRA=0
WITH_NFQWS2=0
WITH_NFQWSWEB=0
WITH_AWG=0
WITH_CRON=0

BOT_TOKEN=""
ADMIN_ID=""

LOGFILE="/opt/var/log/keenetic-tg-bot-install.log"
mkdir -p /opt/var/log >/dev/null 2>&1 || true
: > "$LOGFILE" 2>/dev/null || true

t() { # t "ru" "en"
  if [ "$LANG" = "en" ]; then echo "$2"; else echo "$1"; fi
}

say() { printf "%s\n" "$*"; }
dbg() { [ "$DEBUG" -eq 1 ] && printf "[debug] %s\n" "$*" >&2 || true; }
warn() { printf "⚠️ %s\n" "$*" >&2 || true; }
die() { printf "❌ %s\n" "$*" >&2 || true; exit 1; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }

runq() { # runq "label" cmd...
  label="$1"; shift
  say "[RUN] $label"
  if [ "$DEBUG" -eq 1 ]; then
    dbg "cmd: $*"
    "$@" >>"$LOGFILE" 2>&1 || return 1
  else
    "$@" >>"$LOGFILE" 2>&1 || return 1
  fi
  return 0
}

read_tty() {
  # read_tty VAR "prompt"
  var="$1"; prompt="$2"
  printf "%s" "$prompt"
  IFS= read -r val </dev/tty || val=""
  eval "$var=\$val"
}

ask() {
  # ask "Question" -> return 0 if yes
  q="$1"
  if [ "$YES" -eq 1 ]; then
    return 0
  fi
  printf "%s [y/N]: " "$q"
  IFS= read -r ans </dev/tty || ans=""
  case "$ans" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

select_language() {
  if [ -n "$LANG" ]; then return 0; fi
  say ""
  say "1) Русский"
  say "2) English"
  printf "Select language / Выберите язык [1/2]: "
  IFS= read -r sel </dev/tty || sel="1"
  if [ "$sel" = "2" ]; then LANG="en"; else LANG="ru"; fi
}

raw_url() {
  # raw_url "path"
  printf "https://raw.githubusercontent.com/%s/%s/%s/%s" "$REPO_OWNER" "$REPO_NAME" "$BRANCH" "$1"
}

fetch_file() {
  # fetch_file "path" "dest"
  file="$1"; dest="$2"
  url="$(raw_url "$file")?t=$(date +%s)"
  mkdir -p "$(dirname "$dest")" >/dev/null 2>&1 || true
  if [ "$DEBUG" -eq 1 ]; then dbg "download: $url -> $dest"; fi
  if has_cmd curl; then
    curl -fsSL -H "Cache-Control: no-cache" -o "$dest" "$url" >>"$LOGFILE" 2>&1 || return 1
  elif has_cmd wget; then
    wget -qO "$dest" "$url" >>"$LOGFILE" 2>&1 || return 1
  else
    return 1
  fi
  [ -s "$dest" ] || return 1
  return 0
}

SRC_DIR="/opt/tmp/keenetic-tg-bot-installer"
ensure_repo_files() {
  rm -rf "$SRC_DIR" >/dev/null 2>&1 || true
  mkdir -p "$SRC_DIR" >/dev/null 2>&1 || true

  fetch_file "Main.py" "$SRC_DIR/Main.py" || die "Failed to download Main.py"
  fetch_file "bot.py" "$SRC_DIR/bot.py" || true
  fetch_file "S99keenetic-tg-bot" "$SRC_DIR/S99keenetic-tg-bot" || die "Failed to download init script"
  fetch_file "install.sh" "$SRC_DIR/install.sh" || die "Failed to download install.sh"
  fetch_file "README.md" "$SRC_DIR/README.md" || true
  fetch_file "README_RU.md" "$SRC_DIR/README_RU.md" || true

  # config examples
  fetch_file "config/config.example.json" "$SRC_DIR/config/config.example.json" || true
  fetch_file "config.example.json" "$SRC_DIR/config.example.json" || true

  # modules
  fetch_file "modules/__init__.py" "$SRC_DIR/modules/__init__.py" || die "Failed to download modules/__init__.py"
  fetch_file "modules/constants.py" "$SRC_DIR/modules/constants.py" || die "Failed to download modules/constants.py"
  fetch_file "modules/utils.py" "$SRC_DIR/modules/utils.py" || die "Failed to download modules/utils.py"
  fetch_file "modules/config.py" "$SRC_DIR/modules/config.py" || die "Failed to download modules/config.py"
  fetch_file "modules/profiler.py" "$SRC_DIR/modules/profiler.py" || die "Failed to download modules/profiler.py"
  fetch_file "modules/shell.py" "$SRC_DIR/modules/shell.py" || die "Failed to download modules/shell.py"
  fetch_file "modules/ui.py" "$SRC_DIR/modules/ui.py" || die "Failed to download modules/ui.py"
  fetch_file "modules/monitor.py" "$SRC_DIR/modules/monitor.py" || die "Failed to download modules/monitor.py"
  fetch_file "modules/storage.py" "$SRC_DIR/modules/storage.py" || die "Failed to download modules/storage.py"
  fetch_file "modules/diag.py" "$SRC_DIR/modules/diag.py" || die "Failed to download modules/diag.py"
  fetch_file "modules/app.py" "$SRC_DIR/modules/app.py" || die "Failed to download modules/app.py"
  fetch_file "modules/drivers.py" "$SRC_DIR/modules/drivers.py" || die "Failed to download modules/drivers.py"

  # drivers package
  fetch_file "modules/drivers/__init__.py" "$SRC_DIR/modules/drivers/__init__.py" || true
  fetch_file "modules/drivers/router.py" "$SRC_DIR/modules/drivers/router.py" || true
  fetch_file "modules/drivers/opkg.py" "$SRC_DIR/modules/drivers/opkg.py" || true
  fetch_file "modules/drivers/hydra.py" "$SRC_DIR/modules/drivers/hydra.py" || true
  fetch_file "modules/drivers/nfqws.py" "$SRC_DIR/modules/drivers/nfqws.py" || true
  fetch_file "modules/drivers/awg.py" "$SRC_DIR/modules/drivers/awg.py" || true

  chmod +x "$SRC_DIR/Main.py" "$SRC_DIR/install.sh" "$SRC_DIR/S99keenetic-tg-bot" >/dev/null 2>&1 || true
}

cleanup_installer() {
  rm -rf "$SRC_DIR" >/dev/null 2>&1 || true
}

installed_bot() {
  [ -f /opt/etc/keenetic-tg-bot/Main.py ] || [ -f /opt/etc/keenetic-tg-bot/bot.py ]
}

need_entware() {
  has_cmd opkg || die "Entware/opkg not found. Install Entware first."
}

install_base() {
  runq "opkg update" opkg update || die "opkg update failed"
  runq "base packages" opkg install ca-certificates curl coreutils-nohup >/dev/null 2>&1 || true
}

install_python() {
  runq "python packages" opkg install python3 python3-pip ca-certificates curl coreutils-nohup || die "Python install failed"
  runq "pip upgrade" python3 -m pip install --upgrade pip || true
  runq "pip pyTelegramBotAPI" python3 -m pip install pyTelegramBotAPI || die "pip install pyTelegramBotAPI failed"
}

deploy_bot_files() {
  [ -f "$SRC_DIR/install.sh" ] || die "install.sh not found in $SRC_DIR"
  sh "$SRC_DIR/install.sh" >>"$LOGFILE" 2>&1 || die "install.sh failed"
}

write_config() {
  CFG_DIR="/opt/etc/keenetic-tg-bot"
  mkdir -p "$CFG_DIR/config" >/dev/null 2>&1 || true

  if [ -z "$BOT_TOKEN" ]; then
    say "$(t "Telegram Bot Token: @BotFather → /newbot" "Telegram Bot Token: @BotFather → /newbot")"
    read_tty BOT_TOKEN "$(t "Введите bot_token: " "Enter bot_token: ")"
  fi
  if [ -z "$ADMIN_ID" ]; then
    say "$(t "Telegram user_id: проще всего @userinfobot (Id: ...)" "Telegram user_id: use @userinfobot (Id: ...)")"
    read_tty ADMIN_ID "$(t "Введите admin user_id (число): " "Enter admin user_id (number): ")"
  fi
  case "$ADMIN_ID" in
    ''|*[!0-9]*) die "$(t "admin user_id должен быть числом" "admin user_id must be a number")" ;;
  esac

  cat > "$CFG_DIR/config/config.json" <<EOF
{
  "bot_token": "$BOT_TOKEN",
  "admins": [$ADMIN_ID],
  "debug": { "enabled": false, "log_output_max": 5000 },
  "monitor": { "enabled": true, "interval_sec": 60 },
  "notify": { "cooldown_sec": 300 }
}
EOF

  # backward compat
  [ -f "$CFG_DIR/config.json" ] || ln -s "$CFG_DIR/config/config.json" "$CFG_DIR/config.json" >/dev/null 2>&1 || true
  say "$(t "✅ Конфиг сохранён" "✅ Config saved")"
}

service_restart() {
  INIT="/opt/etc/init.d/S99keenetic-tg-bot"
  if [ -f "$INIT" ]; then
    sh "$INIT" restart >/dev/null 2>&1 || true
    sh "$INIT" status || true
  else
    warn "$(t "init-скрипт не найден: /opt/etc/init.d/S99keenetic-tg-bot" "init script not found: /opt/etc/init.d/S99keenetic-tg-bot")"
  fi
}

# ---- component installers (best-effort; requires repos)
install_hydra() { runq "install HydraRoute" opkg install hrneo hrweb hydraroute || return 1; }
install_nfqws2() { runq "install NFQWS2" opkg install nfqws2-keenetic || return 1; }
install_nfqwsweb() { runq "install NFQWS web" opkg install nfqws-keenetic-web || return 1; }
install_awg() { runq "install AWG Manager" opkg install awg-manager || return 1; }
install_cron() { runq "install cron" opkg install cron || return 1; }

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --lang) LANG="$2"; shift 2 ;;
      --debug|-debug) DEBUG=1; shift ;;
      --yes|-y) YES=1; shift ;;
      --branch) BRANCH="$2"; shift 2 ;;
      --token) BOT_TOKEN="$2"; shift 2 ;;
      --admin) ADMIN_ID="$2"; shift 2 ;;
      --bot) WITH_BOT=1; shift ;;
      --update-bot|--update) WITH_BOT=1; FORCE_UPDATE_BOT=1; shift ;;
      --hydra) WITH_HYDRA=1; shift ;;
      --nfqws2) WITH_NFQWS2=1; shift ;;
      --nfqwsweb) WITH_NFQWSWEB=1; shift ;;
      --awg) WITH_AWG=1; shift ;;
      --cron) WITH_CRON=1; shift ;;
      *) shift ;;
    esac
  done
}

main() {
  parse_args "$@"
  select_language
  need_entware
  install_base

  # interactive selection if not --yes and no explicit flags
  if [ "$YES" -eq 0 ] && [ "$WITH_BOT$WITH_HYDRA$WITH_NFQWS2$WITH_NFQWSWEB$WITH_AWG$WITH_CRON" = "000000" ]; then
    say "$(t "Интерактивный режим." "Interactive mode.")"
    ask "$(t "Установить HydraRoute Neo?" "Install HydraRoute Neo?")" && WITH_HYDRA=1
    ask "$(t "Установить NFQWS2?" "Install NFQWS2?")" && WITH_NFQWS2=1
    ask "$(t "Установить NFQWS web UI?" "Install NFQWS web UI?")" && WITH_NFQWSWEB=1
    ask "$(t "Установить AWG Manager?" "Install AWG Manager?")" && WITH_AWG=1
    ask "$(t "Установить cron (для расписаний)?" "Install cron?")" && WITH_CRON=1
    if installed_bot; then
      ask "$(t "Обновить файлы Telegram-бота?" "Update Telegram bot files?")" && { WITH_BOT=1; FORCE_UPDATE_BOT=1; }
    else
      ask "$(t "Установить Telegram-бот?" "Install Telegram bot?")" && WITH_BOT=1
    fi
  fi

  # install selected components
  [ "$WITH_HYDRA" -eq 1 ] && install_hydra || true
  [ "$WITH_NFQWS2" -eq 1 ] && install_nfqws2 || true
  [ "$WITH_NFQWSWEB" -eq 1 ] && install_nfqwsweb || true
  [ "$WITH_AWG" -eq 1 ] && install_awg || true
  [ "$WITH_CRON" -eq 1 ] && install_cron || true

  if [ "$WITH_BOT" -eq 1 ]; then
    install_python
    # stop service if exists
    [ -f /opt/etc/init.d/S99keenetic-tg-bot ] && sh /opt/etc/init.d/S99keenetic-tg-bot stop >/dev/null 2>&1 || true
    ensure_repo_files
    deploy_bot_files
    write_config
    cleanup_installer
    service_restart
  fi

  say "$(t "✅ Готово." "✅ Done.")"
  say "$(t "✅ Лог установки: /opt/var/log/keenetic-tg-bot-install.log" "✅ Install log: /opt/var/log/keenetic-tg-bot-install.log")"
}

main "$@"
