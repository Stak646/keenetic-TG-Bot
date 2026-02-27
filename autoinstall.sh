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

TOKEN=""
ADMIN_ID=""
LANG="ru"
YES=0
DEBUG=0
NO_START=0

log() { echo "[keenetic-tg-bot] $*" >&2; }
dbg() { [ "$DEBUG" -eq 1 ] && log "DEBUG: $*"; }
die() { log "ERROR: $*"; exit 1; }

cleanup() {
  [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

usage() {
  cat >&2 <<EOF
Usage: curl -Ls https://raw.githubusercontent.com/${REPO}/${BRANCH}/autoinstall.sh | sh -s -- [options]

Options:
  --branch <name>   Git branch (default: ${BRANCH})
  --token <token>   Set Telegram bot token into config.json
  --admin <id>      Add Telegram user id to admins list
  --lang ru|en      Language (default: ru)
  --yes             Non-interactive mode
  --debug           Verbose logs
  --no-start        Do not start service after install
EOF
}

confirm() {
  [ "$YES" -eq 1 ] && return 0
  printf "%s [y/N]: " "$1" >&2
  read ans </dev/tty 2>/dev/null || ans=""
  case "$ans" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

ensure_entware() {
  [ -x /opt/bin/opkg ] || die "Entware not found. Install Entware first (opkg missing)."
}

opkg_install() {
  pkgs="$1"
  dbg "opkg install: $pkgs"
  opkg update >/dev/null 2>&1 || opkg update || true
  opkg install $pkgs || die "opkg install failed: $pkgs"
}

pip_install() {
  pkg="$1"
  PY="/opt/bin/python3"
  [ -x "$PY" ] || PY="python3"
  dbg "pip install: $pkg"
  "$PY" -m pip install --no-cache-dir -U "$pkg" || die "pip install failed: $pkg"
}

download_repo() {
  need_cmd curl
  need_cmd tar
  mkdir -p "$TMP_BASE" >/dev/null 2>&1 || true
  TMP_DIR="$(mktemp -d "$TMP_BASE/keenetic-tg-bot.XXXXXX" 2>/dev/null || echo "$TMP_BASE/keenetic-tg-bot.$$")"
  mkdir -p "$TMP_DIR" || die "Cannot create temp dir: $TMP_DIR"

  url="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}"
  dbg "Downloading: $url"
  curl -fsSL "$url" -o "$TMP_DIR/repo.tar.gz" || die "Failed to download repo tarball"

  mkdir -p "$TMP_DIR/extract" || die "Cannot create extract dir"
  tar -xzf "$TMP_DIR/repo.tar.gz" -C "$TMP_DIR/extract" || die "Failed to extract tarball"
  # find extracted root directory
  EXTRACT_ROOT="$(find "$TMP_DIR/extract" -maxdepth 1 -type d -name 'keenetic-TG-Bot-*' | head -n 1)"
  [ -n "$EXTRACT_ROOT" ] || die "Extracted directory not found"
  echo "$EXTRACT_ROOT"
}

safe_copy_tree() {
  src="$1"
  dst="$2"
  [ -d "$src" ] || die "Missing source dir: $src"
  mkdir -p "$dst" || die "Cannot create: $dst"
  # Keep existing config.json
  if [ -f "$dst/config/config.json" ]; then
    dbg "Preserving existing config.json"
    mkdir -p "$TMP_DIR/backup" >/dev/null 2>&1 || true
    cp -f "$dst/config/config.json" "$TMP_DIR/backup/config.json" >/dev/null 2>&1 || true
  fi

  # Replace tree
  rm -rf "$dst" >/dev/null 2>&1 || true
  mkdir -p "$dst" || die "Cannot create: $dst"
  cp -a "$src/." "$dst/" || die "Copy failed: $src -> $dst"

  if [ -f "$TMP_DIR/backup/config.json" ]; then
    mkdir -p "$dst/config" >/dev/null 2>&1 || true
    cp -f "$TMP_DIR/backup/config.json" "$dst/config/config.json" >/dev/null 2>&1 || true
  fi
}

write_config_overrides() {
  cfg="$INSTALL_DIR/config/config.json"
  [ -f "$cfg" ] || return 0

  # Basic JSON patching with python (more reliable than sed)
  PY="/opt/bin/python3"
  [ -x "$PY" ] || PY="python3"

  "$PY" - "$cfg" "$TOKEN" "$ADMIN_ID" "$LANG" <<'PY'
import json, sys
path, token, admin, lang = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(path,'r',encoding='utf-8') as f:
    d=json.load(f)
if token:
    d['bot_token']=token
admins = d.get('admins') or []
if isinstance(admins, int):
    admins=[admins]
if admin:
    try:
        aid=int(admin)
        if aid not in admins:
            admins.append(aid)
    except Exception:
        pass
d['admins']=admins
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
  chmod +x "$INIT_SCRIPT" || true
}

stop_service() {
  if [ -x "$INIT_SCRIPT" ]; then
    dbg "Stopping service..."
    "$INIT_SCRIPT" stop >/dev/null 2>&1 || true
  fi
}

start_service() {
  [ "$NO_START" -eq 1 ] && return 0
  if [ -x "$INIT_SCRIPT" ]; then
    dbg "Starting service..."
    "$INIT_SCRIPT" start || true
  fi
}

main() {
  # args
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

  ensure_entware

  log "Install Keenetic TG Bot from ${REPO} branch '${BRANCH}'"
  if [ "$YES" -ne 1 ]; then
    confirm "Continue?" || exit 1
  fi

  # Dependencies
  opkg_install "ca-certificates curl coreutils-nohup python3 python3-pip"
  pip_install "pyTelegramBotAPI"

  # Download and deploy
  stop_service
  EXTRACT_ROOT="$(download_repo)"
  PKG_DIR="$EXTRACT_ROOT/keenetic-tg-bot"
  [ -d "$PKG_DIR" ] || die "Bot folder not found in repo: $PKG_DIR"

  safe_copy_tree "$PKG_DIR" "$INSTALL_DIR"

  # Ensure config exists
  [ -f "$INSTALL_DIR/config/config.json" ] || cp -f "$INSTALL_DIR/config/config.example.json" "$INSTALL_DIR/config/config.json" 2>/dev/null || true

  write_config_overrides
  install_init_script

  # optional symlink for convenience
  if [ -d /etc ] && [ ! -e /etc/keenetic-tg-bot ]; then
    ln -s "$INSTALL_DIR" /etc/keenetic-tg-bot >/dev/null 2>&1 || true
  fi

  start_service

  log "DONE"
  log "Config: $INSTALL_DIR/config/config.json"
  log "Logs:   /opt/var/log/keenetic-tg-bot.log and $LOGFILE"
}

main "$@"
