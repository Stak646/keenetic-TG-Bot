#!/bin/sh
# Keenetic TG Bot installer (Entware)
# Safe for BusyBox ash.
set -u

REPO="Stak646/keenetic-TG-Bot"
BRANCH="alfa"

INSTALL_DIR="/opt/etc/keenetic-tg-bot"
INIT_DIR="/opt/etc/init.d"
INIT_SCRIPT="$INIT_DIR/S99keenetic-tg-bot"

TMP_BASE="/opt/tmp"
TMP_DIR=""

LOGFILE="/opt/var/log/keenetic-tg-bot-install.log"

TOKEN=""
ADMIN_ID=""
LANG="ru"
YES=0
DEBUG=0
NO_START=0

# ---------------- utils ----------------

log() {
  echo "[keenetic-tg-bot] $*" >&2
  (mkdir -p "$(dirname "$LOGFILE")" >/dev/null 2>&1 || true; echo "[keenetic-tg-bot] $*" >>"$LOGFILE" 2>/dev/null || true) || true
}

dbg() { [ "$DEBUG" -eq 1 ] && log "DEBUG: $*"; }

die() {
  log "ERROR: $*"
  [ -f "$LOGFILE" ] && { log "--- last log lines ($LOGFILE) ---"; tail -n 40 "$LOGFILE" >&2 2>/dev/null || true; }
  exit 1
}

cleanup() {
  [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

usage() {
  cat >&2 <<EOF
Usage:
  curl -Ls https://raw.githubusercontent.com/${REPO}/${BRANCH}/autoinstall.sh | sh

Options (optional):
  --branch <name>   Git branch (default: ${BRANCH})
  --token <token>   Set Telegram bot token (non-interactive)
  --admin <id>      Add Telegram user id to admins list (non-interactive)
  --lang ru|en      Language (skip prompt)
  --yes             Non-interactive mode (accept defaults)
  --debug           Verbose installer output
  --no-start        Do not start service after install
EOF
}

confirm() {
  # confirm "question" "Y|N"  (default)
  q="$1"; def="$2"
  if [ "$YES" -eq 1 ]; then
    [ "$def" = "Y" ] && return 0
    return 1
  fi

  if [ "$def" = "Y" ]; then
    suf="[Y/n]"
  else
    suf="[y/N]"
  fi

  printf "%s %s: " "$q" "$suf" >&2
  read ans </dev/tty 2>/dev/null || ans=""
  case "$ans" in
    "") [ "$def" = "Y" ] && return 0 || return 1 ;;
    y|Y|yes|YES) return 0 ;;
    n|N|no|NO) return 1 ;;
    *) [ "$def" = "Y" ] && return 0 || return 1 ;;
  esac
}

prompt() {
  # prompt "question" "default" -> prints chosen value
  q="$1"; def="$2"
  if [ "$YES" -eq 1 ]; then
    echo "$def"
    return 0
  fi
  if [ -n "$def" ]; then
    printf "%s [%s]: " "$q" "$def" >&2
  else
    printf "%s: " "$q" >&2
  fi
  read ans </dev/tty 2>/dev/null || ans=""
  [ -n "$ans" ] && echo "$ans" || echo "$def"
}

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

ensure_entware() {
  [ -x /opt/bin/opkg ] || die "Entware not found. Install Entware first (opkg missing)."
}

init_tmp() {
  mkdir -p "$TMP_BASE" >/dev/null 2>&1 || true
  TMP_DIR="$(mktemp -d "$TMP_BASE/keenetic-tg-bot.XXXXXX" 2>/dev/null || echo "$TMP_BASE/keenetic-tg-bot.$$")"
  mkdir -p "$TMP_DIR" || die "Cannot create temp dir: $TMP_DIR"
}

spinner_wait() {
  pid="$1"; title="$2"
  while kill -0 "$pid" >/dev/null 2>&1; do
    for c in '-' '\\' '|' '/'; do
      printf "\r%s %s" "$title" "$c" >&2
      sleep 0.12
      kill -0 "$pid" >/dev/null 2>&1 || break
    done
  done
}

run_step() {
  title="$1"; shift
  mkdir -p "$(dirname "$LOGFILE")" >/dev/null 2>&1 || true
  touch "$LOGFILE" >/dev/null 2>&1 || true

  if [ "$DEBUG" -eq 1 ]; then
    log "==> $title"
    rcfile="$TMP_DIR/.rc"
    : >"$rcfile" 2>/dev/null || true
    # capture real command exit code while still streaming output
    ( "$@" 2>&1; echo $? >"$rcfile" ) | tee -a "$LOGFILE" >&2
    rc="$(cat "$rcfile" 2>/dev/null || echo 1)"
    [ "$rc" -eq 0 ] || die "$title failed"
    return 0
  fi

  printf "%s " "$title" >&2
  "$@" >>"$LOGFILE" 2>&1 &
  pid=$!
  spinner_wait "$pid" "$title"
  wait "$pid"; rc=$?
  if [ "$rc" -eq 0 ]; then
    printf "\r%s [OK]\n" "$title" >&2
    return 0
  fi
  printf "\r%s [FAIL]\n" "$title" >&2
  die "$title failed"
}

mask_token() {
  t="$1"
  [ -z "$t" ] && { echo ""; return 0; }
  # show first 6 and last 4 if long enough
  len=${#t}
  if [ "$len" -le 12 ]; then
    echo "****"
  else
    pre="$(printf "%s" "$t" | cut -c 1-6 2>/dev/null)"
    suf="$(printf "%s" "$t" | rev | cut -c 1-4 2>/dev/null | rev)"
    echo "${pre}…${suf}"
  fi
}

is_placeholder_token() {
  [ -z "$1" ] && return 0
  [ "$1" = "PASTE_YOUR_TOKEN_HERE" ] && return 0
  return 1
}

is_placeholder_admin() {
  [ -z "$1" ] && return 0
  [ "$1" = "123456789" ] && return 0
  return 1
}

# ---------------- i18n (minimal) ----------------

say() {
  key="$1"
  case "$LANG" in
    en)
      case "$key" in
        choose_lang) echo "Language (ru/en)" ;;
        continue) echo "Continue" ;;
        arch) echo "Detected arch" ;;
        deps_check) echo "Checking dependencies" ;;
        deps_install) echo "Install missing dependencies" ;;
        deps_unavail) echo "Some required packages are not available for this Entware architecture" ;;
        bot_present) echo "Bot is already installed. Reinstall/update" ;;
        bot_install) echo "Install bot now" ;;
        cfg_found) echo "config.json found. Overwrite it (reset settings)" ;;
        ask_token) echo "Telegram bot token" ;;
        ask_admin) echo "Admin Telegram ID" ;;
        download) echo "Downloading repository" ;;
        deploy) echo "Deploying files" ;;
        init) echo "Installing service script" ;;
        start) echo "Starting service" ;;
        done) echo "DONE" ;;
        log) echo "Installer log" ;;
        cfg) echo "Config" ;;
        *) echo "$key" ;;
      esac
      ;;
    *)
      case "$key" in
        choose_lang) echo "Язык (ru/en)" ;;
        continue) echo "Продолжить" ;;
        arch) echo "Обнаружена архитектура" ;;
        deps_check) echo "Проверка зависимостей" ;;
        deps_install) echo "Установить недостающие зависимости" ;;
        deps_unavail) echo "Часть обязательных пакетов отсутствует в репозитории Entware для этой архитектуры" ;;
        bot_present) echo "Бот уже установлен. Переустановить/обновить" ;;
        bot_install) echo "Установить бота" ;;
        cfg_found) echo "Найден config.json. Перезаписать его (сбросить настройки)" ;;
        ask_token) echo "Токен Telegram бота" ;;
        ask_admin) echo "ID администратора Telegram" ;;
        download) echo "Загрузка репозитория" ;;
        deploy) echo "Развёртывание файлов" ;;
        init) echo "Установка init-скрипта" ;;
        start) echo "Запуск сервиса" ;;
        done) echo "ГОТОВО" ;;
        log) echo "Лог установки" ;;
        cfg) echo "Конфиг" ;;
        *) echo "$key" ;;
      esac
      ;;
  esac
}

# ---------------- core actions ----------------

opkg_update() {
  opkg update
}

opkg_pkg_available() {
  pkg="$1"
  opkg info "$pkg" 2>/dev/null | grep -q "^Package: $pkg$"
}

opkg_pkg_installed() {
  pkg="$1"
  opkg list-installed 2>/dev/null | grep -q "^$pkg -"
}

opkg_install() {
  pkgs="$1"
  [ -z "$pkgs" ] && return 0
  opkg install $pkgs
}

pip_install() {
  pkg="$1"
  PY="/opt/bin/python3"; [ -x "$PY" ] || PY="python3"
  "$PY" -m pip install --no-cache-dir -U "$pkg"
}

python_import_ok() {
  mod="$1"
  PY="/opt/bin/python3"; [ -x "$PY" ] || PY="python3"
  "$PY" -c "import $mod" >/dev/null 2>&1
}

download_repo() {
  need_cmd curl
  need_cmd tar

  url="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}"
  dbg "Downloading: $url"
  rm -rf "$TMP_DIR/extract" >/dev/null 2>&1 || true
  mkdir -p "$TMP_DIR/extract" || die "Cannot create extract dir"

  run_step "$(say download)" curl -fsSL "$url" -o "$TMP_DIR/repo.tar.gz"
  run_step "Extract" tar -xzf "$TMP_DIR/repo.tar.gz" -C "$TMP_DIR/extract"

  EXTRACT_ROOT="$(find "$TMP_DIR/extract" -maxdepth 1 -type d -name 'keenetic-TG-Bot-*' | head -n 1)"
  [ -n "$EXTRACT_ROOT" ] || die "Extracted directory not found"
  echo "$EXTRACT_ROOT"
}

safe_copy_tree() {
  src="$1"; dst="$2"; preserve_cfg="$3" # 1 preserve, 0 overwrite
  [ -d "$src" ] || die "Missing source dir: $src"

  if [ "$preserve_cfg" = "1" ] && [ -f "$dst/config/config.json" ]; then
    dbg "Preserving existing config.json"
    mkdir -p "$TMP_DIR/backup" >/dev/null 2>&1 || true
    cp -f "$dst/config/config.json" "$TMP_DIR/backup/config.json" >/dev/null 2>&1 || true
  else
    rm -f "$TMP_DIR/backup/config.json" >/dev/null 2>&1 || true
  fi

  rm -rf "$dst" >/dev/null 2>&1 || true
  mkdir -p "$dst" || die "Cannot create: $dst"
  cp -a "$src/." "$dst/" || die "Copy failed: $src -> $dst"

  if [ -f "$TMP_DIR/backup/config.json" ]; then
    mkdir -p "$dst/config" >/dev/null 2>&1 || true
    cp -f "$TMP_DIR/backup/config.json" "$dst/config/config.json" >/dev/null 2>&1 || true
  fi
}

read_current_config() {
  cfg="$1"
  PY="/opt/bin/python3"; [ -x "$PY" ] || PY="python3"
  "$PY" - "$cfg" <<'PY'
import json, sys
p=sys.argv[1]
try:
  d=json.load(open(p,'r',encoding='utf-8'))
except Exception:
  d={}
print(d.get('bot_token',''))
admins=d.get('admins') or []
if isinstance(admins,int): admins=[admins]
admins=[str(x) for x in admins]
print(','.join(admins))
print(d.get('language',''))
PY
}

write_config_overrides() {
  cfg="$1"
  PY="/opt/bin/python3"; [ -x "$PY" ] || PY="python3"

  "$PY" - "$cfg" "$TOKEN" "$ADMIN_ID" "$LANG" <<'PY'
import json, sys
path, token, admin, lang = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(path,'r',encoding='utf-8') as f:
    d=json.load(f)

# token
if token and token != 'PASTE_YOUR_TOKEN_HERE':
    d['bot_token']=token

# admins
admins = d.get('admins') or []
if isinstance(admins, int):
    admins=[admins]
# drop placeholder
admins=[a for a in admins if str(a) != '123456789']
if admin:
    try:
        aid=int(admin)
        if aid not in admins:
            admins.append(aid)
    except Exception:
        pass
if not admins:
    d['admins']=[]
else:
    d['admins']=admins

# language
if lang:
    d['language']='en' if lang.lower().startswith('en') else 'ru'

with open(path,'w',encoding='utf-8') as f:
    json.dump(d,f,ensure_ascii=False,indent=2)
PY
}

install_init_script() {
  src="$INSTALL_DIR/scripts/S99keenetic-tg-bot"
  [ -f "$src" ] || die "Init script not found in package: $src"
  mkdir -p "$INIT_DIR" || die "Cannot create: $INIT_DIR"
  cp -f "$src" "$INIT_SCRIPT" || die "Failed to install init script"
  chmod +x "$INIT_SCRIPT" >/dev/null 2>&1 || true
}

stop_service() {
  if [ -x "$INIT_SCRIPT" ]; then
    dbg "Stopping service..."
    "$INIT_SCRIPT" stop >>"$LOGFILE" 2>&1 || true
  fi
}

start_service() {
  [ "$NO_START" -eq 1 ] && return 0
  if [ -x "$INIT_SCRIPT" ]; then
    run_step "$(say start)" "$INIT_SCRIPT" start
  fi
}

choose_language() {
  [ -n "$LANG" ] || LANG="ru"
  [ "$YES" -eq 1 ] && return 0
  ans="$(prompt "$(say choose_lang)" "ru")"
  case "${ans}" in
    en|EN|Eng|ENG|english|English) LANG="en" ;;
    ru|RU|Rus|RUS|russian|Russian|"") LANG="ru" ;;
    *) LANG="ru" ;;
  esac
}

check_and_install_deps() {
  ARCH_UNAME="$(uname -m 2>/dev/null || echo unknown)"
  log "$(say arch): $ARCH_UNAME"

  run_step "opkg update" opkg_update

  PKGS="ca-certificates curl coreutils-nohup python3 python3-pip"

  missing=""
  unavailable=""

  log "$(say deps_check):"
  for p in $PKGS; do
    if opkg_pkg_available "$p"; then
      avail="yes"
    else
      avail="NO"
      unavailable="$unavailable $p"
    fi
    if opkg_pkg_installed "$p"; then
      inst="yes"
    else
      inst="no"
      missing="$missing $p"
    fi

    if [ "$LANG" = "en" ]; then
      log " - $p: installed=$inst, available=$avail"
    else
      log " - $p: установлен=$inst, доступен=$avail"
    fi
  done

  [ -n "$unavailable" ] && {
    log "$(say deps_unavail):$unavailable"
    die "Unsupported Entware feed / architecture for required dependencies."
  }

  if [ -n "$missing" ]; then
    if confirm "$(say deps_install)?" "Y"; then
      run_step "opkg install" opkg_install "$missing"
    else
      die "Dependencies are missing: $missing"
    fi
  fi

  # pip module
  if ! python_import_ok telebot; then
    if confirm "Install/upgrade pyTelegramBotAPI?" "Y"; then
      run_step "pip install" pip_install "pyTelegramBotAPI"
    else
      die "Python module pyTelegramBotAPI is missing."
    fi
  fi
}

prompt_token_admin() {
  cfg="$1"
  cur_token=""; cur_admins=""; cur_lang=""
  if [ -f "$cfg" ]; then
    out="$(read_current_config "$cfg" 2>/dev/null || true)"
    cur_token="$(printf "%s" "$out" | sed -n '1p')"
    cur_admins="$(printf "%s" "$out" | sed -n '2p')"
    cur_lang="$(printf "%s" "$out" | sed -n '3p')"
  fi

  # TOKEN
  if [ -z "$TOKEN" ]; then
    masked="$(mask_token "$cur_token")"
    if is_placeholder_token "$cur_token"; then
      def=""
    else
      def=""
    fi

    while :; do
      if [ -n "$masked" ] && ! is_placeholder_token "$cur_token"; then
        if [ "$LANG" = "en" ]; then
          ans="$(prompt "$(say ask_token) (current: $masked, Enter to keep)" "$def")"
        else
          ans="$(prompt "$(say ask_token) (текущий: $masked, Enter чтобы оставить)" "$def")"
        fi
      else
        ans="$(prompt "$(say ask_token)" "$def")"
      fi

      if [ -z "$ans" ]; then
        # keep current
        TOKEN=""
        if is_placeholder_token "$cur_token"; then
          [ "$YES" -eq 1 ] && die "Bot token is required in non-interactive mode."
          log "Token is required."
          continue
        fi
        break
      fi

      TOKEN="$ans"
      if is_placeholder_token "$TOKEN"; then
        [ "$YES" -eq 1 ] && die "Invalid bot token provided."
        log "Invalid token."
        TOKEN=""
        continue
      fi
      break
    done
  fi

  # ADMIN
  if [ -z "$ADMIN_ID" ]; then
    first_admin="$(printf "%s" "$cur_admins" | cut -d',' -f1 2>/dev/null)"

    while :; do
      if [ -n "$first_admin" ] && ! is_placeholder_admin "$first_admin"; then
        if [ "$LANG" = "en" ]; then
          ans="$(prompt "$(say ask_admin) (current: $first_admin, Enter to keep)" "")"
        else
          ans="$(prompt "$(say ask_admin) (текущий: $first_admin, Enter чтобы оставить)" "")"
        fi
      else
        ans="$(prompt "$(say ask_admin)" "")"
      fi

      if [ -z "$ans" ]; then
        ADMIN_ID=""
        if is_placeholder_admin "$first_admin"; then
          [ "$YES" -eq 1 ] && die "Admin ID is required in non-interactive mode."
          log "Admin ID is required."
          continue
        fi
        break
      fi

      # validate numeric
      case "$ans" in
        *[!0-9]* )
          [ "$YES" -eq 1 ] && die "Admin ID must be numeric."
          log "Admin ID must be numeric."
          continue
          ;;
      esac

      if is_placeholder_admin "$ans"; then
        [ "$YES" -eq 1 ] && die "Admin ID cannot be placeholder 123456789."
        log "Please provide your real Telegram ID (not 123456789)."
        continue
      fi
      ADMIN_ID="$ans"
      break
    done
  fi
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --branch) BRANCH="$2"; shift 2 ;;
      --token) TOKEN="$2"; shift 2 ;;
      --admin) ADMIN_ID="$2"; shift 2 ;;
      --lang) LANG="$2"; shift 2 ;;
      --yes) YES=1; shift 1 ;;
      --debug) DEBUG=1; shift 1 ;;
      --no-start) NO_START=1; shift 1 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown option: $1" ;;
    esac
  done

  # Language prompt first (as requested)
  choose_language

  ensure_entware
  init_tmp

  mkdir -p "$(dirname "$LOGFILE")" >/dev/null 2>&1 || true
  : >"$LOGFILE" 2>/dev/null || true

  if [ "$DEBUG" -eq 1 ]; then
    log "Installer debug enabled"
  fi

  if ! confirm "$(say continue)?" "Y"; then
    exit 1
  fi

  check_and_install_deps

  # Install/reinstall bot?
  if [ -d "$INSTALL_DIR" ]; then
    if ! confirm "$(say bot_present)?" "Y"; then
      log "Exit: bot installation skipped"
      exit 0
    fi
  else
    if ! confirm "$(say bot_install)?" "Y"; then
      log "Exit: bot installation skipped"
      exit 0
    fi
  fi

  # Config overwrite decision BEFORE replacing tree
  preserve_cfg="1"
  if [ -f "$INSTALL_DIR/config/config.json" ]; then
    if confirm "$(say cfg_found)?" "N"; then
      preserve_cfg="0"
    fi
  fi

  stop_service
  EXTRACT_ROOT="$(download_repo)"
  PKG_DIR="$EXTRACT_ROOT/keenetic-tg-bot"
  [ -d "$PKG_DIR" ] || die "Bot folder not found in repo: $PKG_DIR"

  run_step "$(say deploy)" safe_copy_tree "$PKG_DIR" "$INSTALL_DIR" "$preserve_cfg"

  # Ensure config exists
  mkdir -p "$INSTALL_DIR/config" >/dev/null 2>&1 || true
  if [ "$preserve_cfg" = "0" ] || [ ! -f "$INSTALL_DIR/config/config.json" ]; then
    cp -f "$INSTALL_DIR/config/config.example.json" "$INSTALL_DIR/config/config.json" || die "Cannot create config.json"
  fi

  # Token + Admin prompts
  prompt_token_admin "$INSTALL_DIR/config/config.json"
  write_config_overrides "$INSTALL_DIR/config/config.json"

  run_step "$(say init)" install_init_script

  # optional symlink for convenience
  if [ -d /etc ] && [ ! -e /etc/keenetic-tg-bot ]; then
    ln -s "$INSTALL_DIR" /etc/keenetic-tg-bot >/dev/null 2>&1 || true
  fi

  start_service

  log "$(say done)"
  log "$(say cfg): $INSTALL_DIR/config/config.json"
  log "$(say log): $LOGFILE"
  log "Main logs: /opt/var/log/keenetic-tg-bot.log and /opt/var/log/keenetic-tg-bot-console.log"
}

main "$@"
