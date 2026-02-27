#!/bin/sh
# Keenetic TG Bot installer (Entware)
# Interactive by default, supports --debug.
# BusyBox ash compatible.

set -u

REPO="Stak646/keenetic-TG-Bot"
BRANCH="alfa"

INSTALL_DIR="/opt/etc/keenetic-tg-bot"
INIT_DIR="/opt/etc/init.d"
INIT_SCRIPT="$INIT_DIR/S99keenetic-tg-bot"

TMP_BASE="/opt/tmp"
TMP_DIR=""

LOGFILE="/opt/var/log/keenetic-tg-bot-install.log"

LANG="ru"      # ru/en
YES=0
DEBUG=0
NO_START=0

TOKEN=""
ADMIN_ID=""

msg() { echo "$*" >&2; }
dbg() { [ "$DEBUG" -eq 1 ] && msg "[debug] $*"; }
die() { msg "ERROR: $*"; msg "Log: $LOGFILE"; exit 1; }

cleanup() {
  [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ensure_entware() {
  [ -x /opt/bin/opkg ] || die "Entware not found (opkg missing). Install Entware first."
}

ensure_logdir() {
  mkdir -p /opt/var/log >/dev/null 2>&1 || true
  : >"$LOGFILE" 2>/dev/null || true
}

prompt() {
  # $1=question, $2=default
  q="$1"; def="$2";
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
  [ -z "$ans" ] && ans="$def"
  echo "$ans"
}

confirm_yn() {
  # $1=question, $2=default (Y/N)
  q="$1"; def="$2";
  [ "$YES" -eq 1 ] && [ "$def" = "Y" ] && return 0
  [ "$YES" -eq 1 ] && return 1

  if [ "$def" = "Y" ]; then
    printf "%s [Y/n]: " "$q" >&2
  else
    printf "%s [y/N]: " "$q" >&2
  fi
  read ans </dev/tty 2>/dev/null || ans=""
  ans="${ans:-$def}"
  case "$ans" in
    y|Y|yes|YES) return 0 ;;
    n|N|no|NO) return 1 ;;
    Y) return 0 ;;
    N) return 1 ;;
    *) [ "$def" = "Y" ] && return 0 || return 1 ;;
  esac
}

run_step() {
  # run_step "Title" command...
  title="$1"; shift
  if [ "$DEBUG" -eq 1 ]; then
    msg "==> $title"
    "$@" || return $?
    return 0
  fi

  msg "$title"
  ("$@") >>"$LOGFILE" 2>&1 &
  pid=$!
  spin='-|\\|/'
  i=0
  while kill -0 "$pid" >/dev/null 2>&1; do
    i=$(( (i + 1) % 4 ))
    c=$(printf "%s" "$spin" | cut -c $((i + 1)))
    printf "\r%s %s" "$title" "$c" >&2
    sleep 1
  done
  wait "$pid"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    printf "\r%s ✅\n" "$title" >&2
  else
    printf "\r%s ❌ (rc=%s)\n" "$title" "$rc" >&2
    msg "See log: $LOGFILE"
  fi
  return "$rc"
}

detect_arch() {
  # prints: arch entware_arch hoaxisr_arch
  archs="$(/opt/bin/opkg print-architecture 2>/dev/null | awk '{print $2}' | tr '\n' ' ' | tr -s ' ')"
  cand=""
  for a in $archs; do
    [ "$a" = "all" ] && continue
    cand="$a"
    break
  done
  cand="$(echo "$cand" | tr 'A-Z' 'a-z')"
  um="$(uname -m 2>/dev/null | tr 'A-Z' 'a-z' || true)"
  if echo "$cand$um" | grep -q "aarch64\|arm64"; then
    echo "aarch64 aarch64-k3.10 aarch64-3.10-kn"
    return 0
  fi
  if echo "$cand$um" | grep -q "mipsel"; then
    echo "mipsel mipsel-k3.4 mipsel-3.4-kn"
    return 0
  fi
  if echo "$cand$um" | grep -q "mips"; then
    echo "mips mips-k3.4 mips-3.4-kn"
    return 0
  fi
  echo "unknown  "
}

ensure_src_line() {
  # $1=name, $2=url, $3=filename
  name="$1"; url="$2"; fn="$3"
  dir="/opt/etc/opkg"
  mkdir -p "$dir" >/dev/null 2>&1 || true
  # If url already present anywhere, do nothing
  if grep -R "$url" /opt/etc/opkg*.conf /opt/etc/opkg/*.conf 2>/dev/null | grep -q .; then
    return 0
  fi
  echo "src/gz $name $url" >>"$dir/$fn" 2>/dev/null || true
}

opkg_installed_ver() {
  pkg="$1"
  /opt/bin/opkg status "$pkg" 2>/dev/null | awk -F': ' '/^Version: /{print $2; exit}'
}

opkg_available_ver() {
  pkg="$1"
  /opt/bin/opkg info "$pkg" 2>/dev/null | awk -F': ' '/^Version: /{print $2; exit}'
}

opkg_is_installed() {
  pkg="$1"
  /opt/bin/opkg status "$pkg" 2>/dev/null | grep -q '^Status: install ok installed'
}

opkg_is_available() {
  pkg="$1"
  /opt/bin/opkg info "$pkg" >/dev/null 2>&1
}

refresh_upgradable_cache() {
  UPGRADABLE_LIST="$(/opt/bin/opkg list-upgradable 2>/dev/null | awk '{print $1}' | tr '\n' ' ')"
}

opkg_is_upgradable() {
  pkg="$1"
  echo " $UPGRADABLE_LIST " | grep -q " $pkg "
}

ensure_pkg_with_prompt() {
  # $1=pkg, $2=human name
  pkg="$1"; name="$2"

  inst="$(opkg_installed_ver "$pkg" 2>/dev/null | head -n1 | tr -d '\r')"
  avail="$(opkg_available_ver "$pkg" 2>/dev/null | head -n1 | tr -d '\r')"
  [ -z "$inst" ] && inst="-"
  [ -z "$avail" ] && avail="-"
  msg "${name}: ${inst} -> ${avail}"

  if [ "$inst" = "-" ]; then
    if [ "$avail" = "-" ]; then
      msg "${name}: not available for this architecture / repo"
      return 0
    fi
    if confirm_yn "Install ${name}?" "Y"; then
      run_step "Installing ${name}" /opt/bin/opkg install "$pkg" || return $?
    fi
    return 0
  fi

  if opkg_is_upgradable "$pkg"; then
    if confirm_yn "Upgrade ${name}?" "Y"; then
      run_step "Upgrading ${name}" /opt/bin/opkg upgrade "$pkg" || return $?
    fi
  fi
  return 0
}

detect_hydra_variant() {
  if opkg_is_installed "hrneo"; then
    echo "neo"; return 0
  fi
  if opkg_is_installed "hydraroute"; then
    echo "classic"; return 0
  fi
  if [ -f /opt/etc/AdGuardHome/ipset.conf ]; then
    echo "relic"; return 0
  fi
  echo "none"
}

download_repo() {
  mkdir -p "$TMP_BASE" >/dev/null 2>&1 || true
  TMP_DIR="$(mktemp -d "$TMP_BASE/keenetic-tg-bot.XXXXXX" 2>/dev/null || echo "$TMP_BASE/keenetic-tg-bot.$$")"
  mkdir -p "$TMP_DIR" || die "Cannot create temp dir: $TMP_DIR"
  url="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}"
  run_step "Downloading repository" /opt/bin/curl -fsSL "$url" -o "$TMP_DIR/repo.tar.gz" || return 1
  mkdir -p "$TMP_DIR/extract" || return 1
  run_step "Extracting repository" tar -xzf "$TMP_DIR/repo.tar.gz" -C "$TMP_DIR/extract" || return 1
  EXTRACT_ROOT="$(find "$TMP_DIR/extract" -maxdepth 1 -type d -name 'keenetic-TG-Bot-*' | head -n 1)"
  [ -n "$EXTRACT_ROOT" ] || die "Extracted directory not found"
  echo "$EXTRACT_ROOT"
}

deploy_bot_files() {
  src_root="$1"
  pkg_dir="$src_root/keenetic-tg-bot"
  [ -d "$pkg_dir" ] || die "Bot folder not found in repo: $pkg_dir"

  mkdir -p "$(dirname "$INSTALL_DIR")" >/dev/null 2>&1 || true

  # Preserve config if requested
  if [ -f "$INSTALL_DIR/config/config.json" ] && [ "$RESET_CONFIG" -eq 0 ]; then
    mkdir -p "$TMP_DIR/backup" >/dev/null 2>&1 || true
    cp -f "$INSTALL_DIR/config/config.json" "$TMP_DIR/backup/config.json" >/dev/null 2>&1 || true
  fi

  run_step "Deploying files" sh -c "rm -rf '$INSTALL_DIR' && mkdir -p '$INSTALL_DIR' && cp -a '$pkg_dir/.' '$INSTALL_DIR/'" || return 1

  if [ -f "$TMP_DIR/backup/config.json" ]; then
    mkdir -p "$INSTALL_DIR/config" >/dev/null 2>&1 || true
    cp -f "$TMP_DIR/backup/config.json" "$INSTALL_DIR/config/config.json" >/dev/null 2>&1 || true
  fi

  # Ensure config exists
  if [ ! -f "$INSTALL_DIR/config/config.json" ]; then
    cp -f "$INSTALL_DIR/config/config.example.json" "$INSTALL_DIR/config/config.json" 2>/dev/null || true
  fi
}

write_config() {
  cfg="$INSTALL_DIR/config/config.json"
  [ -f "$cfg" ] || return 0
  PY="/opt/bin/python3"
  [ -x "$PY" ] || PY="python3"
  "$PY" - "$cfg" "$TOKEN" "$ADMIN_ID" "$LANG" <<'PY'
import json, sys
path, token, admin, lang = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(path,'r',encoding='utf-8') as f:
    d=json.load(f)
def is_placeholder_token(t:str)->bool:
    return (not t) or t.strip()=="PASTE_YOUR_TOKEN_HERE"
def is_placeholder_admin(a)->bool:
    try:
        return int(a)==123456789
    except Exception:
        return False

if token:
    d['bot_token']=token

admins = d.get('admins') or []
if isinstance(admins, int):
    admins=[admins]
admins = [int(x) for x in admins if str(x).strip().isdigit()]
admins = [x for x in admins if not is_placeholder_admin(x)]

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

# Safety: if token left placeholder, keep as is (installer should ask).
with open(path,'w',encoding='utf-8') as f:
    json.dump(d,f,ensure_ascii=False,indent=2)
PY
}

install_init() {
  src="$INSTALL_DIR/scripts/S99keenetic-tg-bot"
  [ -f "$src" ] || die "Init script not found in package: $src"
  mkdir -p "$INIT_DIR" || true
  cp -f "$src" "$INIT_SCRIPT" || return 1
  chmod +x "$INIT_SCRIPT" >/dev/null 2>&1 || true
}

stop_service() {
  if [ -x "$INIT_SCRIPT" ]; then
    "$INIT_SCRIPT" stop >>"$LOGFILE" 2>&1 || true
  fi
}

start_service() {
  [ "$NO_START" -eq 1 ] && return 0
  if [ -x "$INIT_SCRIPT" ]; then
    "$INIT_SCRIPT" start >>"$LOGFILE" 2>&1 || true
  fi
}

read_existing_cfg_defaults() {
  cfg="$INSTALL_DIR/config/config.json"
  [ -f "$cfg" ] || return 0
  PY="/opt/bin/python3"
  [ -x "$PY" ] || return 0
  out="$($PY - "$cfg" 2>/dev/null <<'PY'
import json, sys
try:
    d=json.load(open(sys.argv[1],'r',encoding='utf-8'))
except Exception:
    print('')
    raise SystemExit
tok=d.get('bot_token','')
admins=d.get('admins') or []
if isinstance(admins,int):
    admins=[admins]
aid=str(admins[0]) if admins else ''
print(tok)
print(aid)
PY
)"
  tok="$(echo "$out" | sed -n '1p')"
  aid="$(echo "$out" | sed -n '2p')"
  [ "$tok" = "PASTE_YOUR_TOKEN_HERE" ] && tok=""
  [ "$aid" = "123456789" ] && aid=""
  [ -z "$TOKEN" ] && TOKEN="$tok"
  [ -z "$ADMIN_ID" ] && ADMIN_ID="$aid"
}

main() {
  # args (optional)
  while [ $# -gt 0 ]; do
    case "$1" in
      --debug) DEBUG=1; shift 1 ;;
      --yes) YES=1; shift 1 ;;
      --lang) LANG="$2"; shift 2 ;;
      --token) TOKEN="$2"; shift 2 ;;
      --admin) ADMIN_ID="$2"; shift 2 ;;
      --branch) BRANCH="$2"; shift 2 ;;
      --no-start) NO_START=1; shift 1 ;;
      -h|--help)
        msg "Usage: curl -Ls https://raw.githubusercontent.com/${REPO}/${BRANCH}/autoinstall.sh | sh"
        msg "Options: --debug --yes --lang ru|en --token <t> --admin <id> --branch <name> --no-start"
        exit 0
        ;;
      *) die "Unknown option: $1" ;;
    esac
  done

  ensure_entware
  ensure_logdir
  export PATH="/opt/bin:/opt/sbin:$PATH"

  # language prompt
  if [ "$YES" -ne 1 ] && [ -z "${LANG:-}" ]; then
    LANG="ru"
  fi
  if [ "$YES" -ne 1 ]; then
    ans="$(prompt "Language / Язык (ru/en)" "ru")"
    case "$(echo "$ans" | tr 'A-Z' 'a-z')" in
      en|eng|english) LANG="en" ;;
      *) LANG="ru" ;;
    esac
  fi

  msg "Keenetic TG Bot installer (${REPO}:${BRANCH})"
  msg "Log: $LOGFILE"

  # Detect architecture
  set -- $(detect_arch)
  ARCH="$1"; ENTWARE_ARCH="$2"; HOAXISR_ARCH="$3"
  msg "Arch: $ARCH"

  # Add known repos (safe if already added)
  if [ "$ENTWARE_ARCH" != "" ]; then
    ensure_src_line "ground_zerro" "https://ground-zerro.github.io/release/keenetic/$ENTWARE_ARCH" "ground-zerro.conf"
  fi
  if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "mipsel" ] || [ "$ARCH" = "mips" ]; then
    ensure_src_line "nfqws2-keenetic" "https://nfqws.github.io/nfqws2-keenetic/$ARCH" "nfqws2.conf"
  fi
  ensure_src_line "nfqws_web" "https://nfqws.github.io/nfqws-keenetic-web/all" "nfqws-web.conf"
  if [ "$HOAXISR_ARCH" != "" ]; then
    ensure_src_line "keenetic_custom" "https://hoaxisr.github.io/entware-repo/$HOAXISR_ARCH" "hoaxisr-awg.conf"
  fi

  # update lists
  run_step "opkg update" /opt/bin/opkg update || die "opkg update failed"
  refresh_upgradable_cache

  # Required base deps
  msg "\n== Base dependencies =="
  ensure_pkg_with_prompt "ca-certificates" "ca-certificates" || die "failed"
  ensure_pkg_with_prompt "curl" "curl" || die "failed"
  ensure_pkg_with_prompt "coreutils-nohup" "coreutils-nohup" || die "failed"
  ensure_pkg_with_prompt "python3" "python3" || die "failed"
  ensure_pkg_with_prompt "python3-pip" "python3-pip" || die "failed"

  # pip module
  msg "pyTelegramBotAPI: checking..."
  PY="/opt/bin/python3"; [ -x "$PY" ] || PY="python3"
  if "$PY" -c "import telebot" >/dev/null 2>&1; then
    if confirm_yn "Upgrade pyTelegramBotAPI?" "Y"; then
      run_step "Upgrading pyTelegramBotAPI" "$PY" -m pip install --no-cache-dir -U pyTelegramBotAPI || die "pip failed"
    fi
  else
    if confirm_yn "Install pyTelegramBotAPI?" "Y"; then
      run_step "Installing pyTelegramBotAPI" "$PY" -m pip install --no-cache-dir -U pyTelegramBotAPI || die "pip failed"
    fi
  fi

  # Detect mutually exclusive traffic routers
  MAGI_INSTALLED=0
  HYDRA_VARIANT="$(detect_hydra_variant)"
  if opkg_is_installed "magitrickle"; then MAGI_INSTALLED=1; fi

  msg "\n== Supported components =="
  msg "NFQWS2 core: nfqws2-keenetic"
  msg "NFQWS web:  nfqws-keenetic-web"
  msg "HydraRoute: hrneo/hrweb (Neo), hydraroute (Classic), Relic (file-based)"
  msg "MagiTrickle: magitrickle"
  msg "AWG Manager: awg-manager"

  # Selection if neither installed
  CHOICE=""
  if [ "$MAGI_INSTALLED" -eq 1 ]; then
    CHOICE="M"
    msg "Traffic router: MagiTrickle detected (HydraRoute ignored)"
  elif [ "$HYDRA_VARIANT" != "none" ]; then
    CHOICE="H"
    msg "Traffic router: HydraRoute $HYDRA_VARIANT detected (MagiTrickle ignored)"
  else
    if [ "$YES" -eq 1 ]; then
      CHOICE="H"
    else
      ans="$(prompt "Select traffic router: (M)agiTrickle / (H)ydraRoute Neo / (N)one" "H")"
      case "$(echo "$ans" | tr 'a-z' 'A-Z')" in
        M) CHOICE="M";;
        N) CHOICE="N";;
        *) CHOICE="H";;
      esac
    fi
  fi

  # Handle component installs/upgrades
  msg "\n== Components =="

  # NFQWS2 core (always compatible, if repo supports)
  ensure_pkg_with_prompt "nfqws2-keenetic" "NFQWS2" || true
  # NFQWS web (optional)
  ensure_pkg_with_prompt "nfqws-keenetic-web" "NFQWS web" || true

  # AWG
  ensure_pkg_with_prompt "awg-manager" "AWG Manager" || true

  # Traffic router choice
  if [ "$CHOICE" = "H" ]; then
    # If Classic/Relic exists, we only offer installing Neo (update path)
    if [ "$HYDRA_VARIANT" = "classic" ] || [ "$HYDRA_VARIANT" = "relic" ]; then
      msg "HydraRoute ${HYDRA_VARIANT} detected: only Neo is supported for installation."
      if confirm_yn "Install HydraRoute Neo (hrneo/hrweb)?" "Y"; then
        ensure_pkg_with_prompt "hrneo" "HydraRoute Neo" || true
        ensure_pkg_with_prompt "hrweb" "HydraRoute Web" || true
      fi
    else
      ensure_pkg_with_prompt "hrneo" "HydraRoute Neo" || true
      ensure_pkg_with_prompt "hrweb" "HydraRoute Web" || true
    fi
  elif [ "$CHOICE" = "M" ]; then
    # add repo helper then install/upgrade
    run_step "Adding MagiTrickle repo" sh -c "curl -fsSL http://bin.magitrickle.dev/packages/add_repo.sh | sh" || true
    run_step "opkg update" /opt/bin/opkg update || true
    refresh_upgradable_cache
    ensure_pkg_with_prompt "magitrickle" "MagiTrickle" || true
  else
    msg "Traffic router: none"
  fi

  # Bot install / reinstall
  RESET_CONFIG=0
  BOT_EXISTS=0
  [ -d "$INSTALL_DIR" ] && BOT_EXISTS=1

  msg "\n== Keenetic TG Bot =="
  if [ "$BOT_EXISTS" -eq 1 ]; then
    if confirm_yn "Bot is already installed. Reinstall/update files?" "Y"; then
      :
    else
      msg "Skipped bot deployment."
      exit 0
    fi
    if [ -f "$INSTALL_DIR/config/config.json" ]; then
      if confirm_yn "Overwrite config.json (reset settings)?" "N"; then
        RESET_CONFIG=1
      fi
    fi
  else
    if ! confirm_yn "Install bot now?" "Y"; then
      msg "Aborted."
      exit 0
    fi
  fi

  # Read defaults from existing config
  read_existing_cfg_defaults || true

  # Ask token/id
  if [ "$YES" -ne 1 ]; then
    TOKEN="$(prompt "Telegram BOT TOKEN" "$TOKEN")"
    ADMIN_ID="$(prompt "Admin ID" "$ADMIN_ID")"
  fi

  if [ -z "$TOKEN" ] || [ "$TOKEN" = "PASTE_YOUR_TOKEN_HERE" ]; then
    die "Bot token is empty. Provide a valid Telegram token."
  fi

  stop_service
  src_root="$(download_repo)" || die "download failed"
  deploy_bot_files "$src_root" || die "deploy failed"
  write_config || true
  install_init || die "init install failed"
  start_service

  msg "\nDONE ✅"
  msg "Config: $INSTALL_DIR/config/config.json"
  msg "Log:    $LOGFILE"
}

main "$@"
