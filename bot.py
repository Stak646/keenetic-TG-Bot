#!/opt/bin/python3
# -*- coding: utf-8 -*-
"""
Keenetic Telegram Router Bot
- Управление роутером (Keenetic/Entware) и OPKG приложениями:
  HydraRoute (Neo/Classic), NFQWS2(+web), AWG Manager.
- Меню на inline-кнопках с навигацией (Home/Back), редактирование одного сообщения.
- Мониторинг: падения сервисов, ошибки в логах, доступные обновления opkg, интернет/ресурсы. 
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import urllib.request
import urllib.parse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Any

import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
    InputFile,
)

# -----------------------------
# Константы / Пути
# -----------------------------
DEFAULT_CONFIG_PATH = "/opt/etc/keenetic-tg-bot/config.json"
LOG_PATH = "/opt/var/log/keenetic-tg-bot.log"

# HydraRoute Neo paths (из документации)
HR_DIR = Path("/opt/etc/HydraRoute")
HR_NEO_CONF = HR_DIR / "hrneo.conf"
HR_DOMAIN_CONF = HR_DIR / "domain.conf"
HR_IP_LIST = HR_DIR / "ip.list"
HR_NEO_LOG_DEFAULT = Path("/opt/var/log/LOGhrneo.log")

# NFQWS2 paths (из документации)
NFQWS_DIR = Path("/opt/etc/nfqws2")
NFQWS_CONF = NFQWS_DIR / "nfqws2.conf"
NFQWS_LISTS_DIR = NFQWS_DIR / "lists"
NFQWS_LOG = Path("/opt/var/log/nfqws2.log")
NFQWS_INIT = Path("/opt/etc/init.d/S51nfqws2")
NFQWS_NETFILTER_HOOK = Path("/opt/etc/ndm/netfilter.d/100-nfqws2.sh")

# NFQWS web (порт читаем из /opt/etc/nfqws_web.conf, если есть)
NFQWS_WEB_CONF = Path("/opt/etc/nfqws_web.conf")

# AWG Manager paths (из install.sh)
AWG_INIT = Path("/opt/etc/init.d/S99awg-manager")
AWG_SETTINGS = Path("/opt/etc/awg-manager/settings.json")

# Target packages
TARGET_PKGS = [
    "hrneo",
    "hrweb",
    "hydraroute",
    "nfqws2-keenetic",
    "nfqws-keenetic-web",
    "awg-manager",
]

# -----------------------------
# Утилиты
# -----------------------------
def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log_line(msg: str) -> None:
    try:
        Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{_now_ts()}] {msg}\n")
    except Exception:
        # не валим бота из-за логов
        pass


def escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s or "")

def clip_text(s: str, max_lines: int = 120, max_chars: int = 3500) -> str:
    s = s or ""
    lines = s.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["… (truncated)"]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n… (truncated)"
    return out

def fmt_code(s: str) -> str:
    return f"<pre><code>{escape_html(clip_text(s))}</code></pre>"

def fmt_ip_route(out: str) -> str:
    out = (out or "").strip()
    if not out:
        return out
    lines = out.splitlines()
    default = [ln for ln in lines if ln.startswith("default ")]
    rest = [ln for ln in lines if ln not in default]
    groups: Dict[str, List[str]] = {}
    for ln in rest:
        m = re.search(r"\bdev\s+(\S+)", ln)
        dev = m.group(1) if m else "other"
        groups.setdefault(dev, []).append(ln)
    res: List[str] = []
    if default:
        res += ["# default"] + default + [""]
    for dev in sorted(groups.keys()):
        res += [f"# dev {dev}"] + groups[dev] + [""]
    return "\n".join([x for x in res if x != ""])

def summarize_iptables(out: str) -> str:
    chains: Dict[str, Dict[str, Any]] = {}
    rules = 0
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("-P "):
            parts = ln.split()
            if len(parts) >= 3:
                chains.setdefault(parts[1], {"policy": parts[2], "rules": 0})
        elif ln.startswith("-A "):
            rules += 1
            parts = ln.split()
            if len(parts) >= 2:
                chains.setdefault(parts[1], {"policy": "?", "rules": 0})
                chains[parts[1]]["rules"] += 1
    lines = [f"Total rules: {rules}"]
    for ch in sorted(chains.keys()):
        lines.append(f"{ch:14} rules={chains[ch]['rules']} policy={chains[ch]['policy']}")
    return "\n".join(lines)

DHCP_RE = re.compile(r"(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<mac>(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\s*(?P<rest>.*)")

def parse_dhcp_bindings(raw: str) -> List[Dict[str, str]]:
    clients: List[Dict[str, str]] = []
    for ln in (raw or "").splitlines():
        m = DHCP_RE.search(ln)
        if not m:
            continue
        ip = m.group("ip")
        mac = m.group("mac").lower()
        rest = (m.group("rest") or "").strip()
        name = rest.split()[0] if rest else ""
        clients.append({"ip": ip, "mac": mac, "name": name, "rest": rest})
    return clients

def split_clients_lan_wifi(clients: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    lan: List[Dict[str, str]] = []
    wifi: List[Dict[str, str]] = []
    for c in clients:
        tag = (c.get("iface", "") + " " + c.get("rest", "")).lower()
        if any(k in tag for k in ["wlan", "wifi", "wl", "ssid", "hostap", "ap"]):
            wifi.append(c)
        else:
            lan.append(c)
    return lan, wifi


def chunk_text(text: str, limit: int = 3800) -> List[str]:
    """Telegram limit 4096. Для запаса держим 3800."""
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    cur = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > limit and cur:
            chunks.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd, path=os.environ.get("PATH", ""))


@dataclass
class BotConfig:
    bot_token: str
    admins: List[int]
    allow_chats: Optional[List[int]] = None  # если None/пусто — разрешаем личку админам
    command_timeout_sec: int = 30
    poll_interval_sec: int = 2

    monitor_enabled: bool = True
    monitor_interval_sec: int = 60
    opkg_update_interval_sec: int = 24 * 3600
    internet_check_interval_sec: int = 5 * 60

    cpu_load_threshold: float = 3.5
    disk_free_mb_threshold: int = 200

    # уведомления
    notify_on_updates: bool = True
    notify_on_service_down: bool = True
    notify_on_internet_down: bool = True
    notify_on_log_errors: bool = True

    # анти-спам
    notify_cooldown_sec: int = 300
    notify_disk_interval_sec: int = 6 * 3600
    notify_load_interval_sec: int = 30 * 60

    # debug
    debug_enabled: bool = False
    debug_log_output_max: int = 5000
def load_config(path: str) -> BotConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return BotConfig(
        bot_token=raw["bot_token"],
        admins=raw["admins"],
        allow_chats=raw.get("allow_chats"),
        command_timeout_sec=int(raw.get("command_timeout_sec", 30)),
        poll_interval_sec=int(raw.get("poll_interval_sec", 2)),
        monitor_enabled=bool(raw.get("monitor", {}).get("enabled", True)),
        monitor_interval_sec=int(raw.get("monitor", {}).get("interval_sec", 60)),
        opkg_update_interval_sec=int(raw.get("monitor", {}).get("opkg_update_interval_sec", 24 * 3600)),
        internet_check_interval_sec=int(raw.get("monitor", {}).get("internet_check_interval_sec", 5 * 60)),
        cpu_load_threshold=float(raw.get("monitor", {}).get("cpu_load_threshold", 3.5)),
        disk_free_mb_threshold=int(raw.get("monitor", {}).get("disk_free_mb_threshold", 200)),
        notify_on_updates=bool(raw.get("notify", {}).get("updates", True)),
        notify_on_service_down=bool(raw.get("notify", {}).get("service_down", True)),
        notify_on_internet_down=bool(raw.get("notify", {}).get("internet_down", True)),
        notify_on_log_errors=bool(raw.get("notify", {}).get("log_errors", True)),
        notify_cooldown_sec=int(raw.get("notify", {}).get("cooldown_sec", 300)),
        notify_disk_interval_sec=int(raw.get("notify", {}).get("disk_interval_sec", 6*3600)),
        notify_load_interval_sec=int(raw.get("notify", {}).get("load_interval_sec", 30*60)),
        debug_enabled=bool(raw.get("debug", {}).get("enabled", False)),
        debug_log_output_max=int(raw.get("debug", {}).get("log_output_max", 5000)),
    )


class Shell:
    def __init__(self, timeout_sec: int = 30, debug: bool = False, debug_output_max: int = 5000):
        self.timeout_sec = timeout_sec
        self.debug = debug
        self.debug_output_max = debug_output_max
        self.env = os.environ.copy()
        # entware binaries
        self.env["PATH"] = "/opt/bin:/opt/sbin:/usr/bin:/usr/sbin:/bin:/sbin:" + self.env.get("PATH", "")

    def run(self, args: List[str], timeout_sec: Optional[int] = None) -> Tuple[int, str]:
        timeout = timeout_sec if timeout_sec is not None else self.timeout_sec
        t0 = time.time()
        cmd = " ".join(args)
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=self.env,
                timeout=timeout,
            )
            out = strip_ansi((proc.stdout or "")).strip()
            rc = proc.returncode
            dt = time.time() - t0
            if self.debug:
                log_line(f"DEBUG cmd={cmd} rc={rc} dt={dt:.3f}s")
                if out:
                    log_line("DEBUG out:\n" + out[: self.debug_output_max])
            return rc, out
        except subprocess.TimeoutExpired as e:
            out = strip_ansi((e.stdout or "")).strip() if e.stdout else ""
            dt = time.time() - t0
            if self.debug:
                log_line(f"DEBUG cmd={cmd} rc=124 dt={dt:.3f}s")
                if out:
                    log_line("DEBUG out:\n" + out[: self.debug_output_max])
            return 124, f"TIMEOUT {timeout}s\n{out}"
        except FileNotFoundError:
            dt = time.time() - t0
            if self.debug:
                log_line(f"DEBUG cmd={cmd} rc=127 dt={dt:.3f}s")
            return 127, f"Команда не найдена: {args[0]}"
        except Exception as e:
            dt = time.time() - t0
            if self.debug:
                log_line(f"DEBUG cmd={cmd} rc=1 dt={dt:.3f}s")
            return 1, f"Ошибка запуска: {e}"

    def sh(self, cmdline: str, timeout_sec: Optional[int] = None) -> Tuple[int, str]:
        # Используем /bin/sh -lc для простых пайпов/грепа в диагностике.
        # ВНИМАНИЕ: НЕ передавать сюда пользовательский ввод!
        return self.run(["/bin/sh", "-lc", cmdline], timeout_sec=timeout_sec)

    def read_file(self, path: Path, max_bytes: int = 200_000) -> Tuple[bool, str]:
        try:
            if not path.exists():
                return False, f"Файл не найден: {path}"
            size = path.stat().st_size
            if size > max_bytes:
                # читаем хвост
                with open(path, "rb") as f:
                    f.seek(max(0, size - max_bytes))
                    data = f.read(max_bytes)
                text = data.decode("utf-8", errors="replace")
                return True, f"(показан хвост файла, {max_bytes} байт)\n{text}"
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return True, f.read()
        except Exception as e:
            return False, f"Не удалось прочитать {path}: {e}"

    def backup_file(self, path: Path) -> Optional[Path]:
        try:
            if not path.exists():
                return None
            ts = time.strftime("%Y%m%d-%H%M%S")
            bkp = path.with_suffix(path.suffix + f".bak-{ts}")
            shutil.copy2(path, bkp)
            return bkp
        except Exception:
            return None

    def write_file(self, path: Path, content: str) -> Tuple[bool, str]:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            bkp = self.backup_file(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True, f"Файл сохранён: {path}" + (f"\nБэкап: {bkp}" if bkp else "")
        except Exception as e:
            return False, f"Не удалось записать {path}: {e}"


# -----------------------------
# Драйверы сервисов / функций
# -----------------------------
class RouterDriver:
    def __init__(self, sh: Shell):
        self.sh = sh

    def lan_ip(self) -> str:
        # стараемся найти адрес на br0 или bridge
        candidates = ["br0", "bridge0", "br-lan"]
        for iface in candidates:
            rc, out = self.sh.run(["ip", "-4", "addr", "show", iface], timeout_sec=5)
            if rc == 0:
                m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", out)
                if m:
                    return m.group(1)
        # fallback
        rc, out = self.sh.run(["hostname", "-I"], timeout_sec=5)
        if rc == 0:
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out)
            if m:
                return m.group(1)
        return "192.168.1.1"

    def uptime(self) -> str:
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as f:
                sec = float(f.read().split()[0])
            mins = int(sec // 60)
            hrs = mins // 60
            days = hrs // 24
            return f"{days}д {hrs%24}ч {mins%60}м"
        except Exception:
            rc, out = self.sh.run(["uptime"], timeout_sec=5)
            return out if rc == 0 else "?"

    def loadavg(self) -> Tuple[float, float, float]:
        try:
            with open("/proc/loadavg", "r", encoding="utf-8") as f:
                a, b, c = f.read().split()[:3]
            return float(a), float(b), float(c)
        except Exception:
            return 0.0, 0.0, 0.0

    def meminfo(self) -> Tuple[int, int]:
        """returns (total_mb, free_mb)"""
        try:
            mem_total = 0
            mem_avail = 0
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1])  # kB
                    if line.startswith("MemAvailable:"):
                        mem_avail = int(line.split()[1])
            return mem_total // 1024, mem_avail // 1024
        except Exception:
            return 0, 0

    def disk_free_mb(self, path: str = "/opt") -> Tuple[int, int]:
        """returns (total_mb, avail_mb)"""
        try:
            st = os.statvfs(path)
            total = (st.f_frsize * st.f_blocks) // (1024 * 1024)
            avail = (st.f_frsize * st.f_bavail) // (1024 * 1024)
            return int(total), int(avail)
        except Exception:
            return 0, 0

    def opt_storage_info(self) -> Tuple[bool, str]:
        """
        Best-effort: returns (is_usb, source_string) for /opt mount.
        """
        rc, out = self.sh.sh("mount | grep ' on /opt ' | head -n 1", timeout_sec=5)
        src = out.split(" on /opt ")[0].strip() if out else ""
        if not src:
            rc, out = self.sh.sh("df -h /opt | tail -n 1", timeout_sec=5)
            src = out.split()[0] if out else "unknown"
        s = (src or "").lower()
        is_usb = any(k in s for k in ["/dev/sd", "usb", "uuid=", "/dev/usb"])
        return is_usb, (src or "unknown")

    def arp_iface_map(self) -> Dict[str, str]:
        """
        Try to map MAC->interface via ndmc 'show ip arp' (best-effort).
        """
        mp: Dict[str, str] = {}
        if not which("ndmc"):
            return mp
        rc, out = self.sh.run(["ndmc", "-c", "show", "ip", "arp"], timeout_sec=10)
        if rc != 0 or not out:
            return mp
        for ln in out.splitlines():
            # try to find MAC and iface tokens
            mm = re.search(r"((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})", ln)
            if not mm:
                continue
            mac = mm.group(1).lower()
            mi = re.search(r"\b(dev|iface|interface)\b\s*(\S+)", ln, flags=re.I)
            iface = ""
            if mi:
                iface = mi.group(2)
            else:
                # heuristic: last token sometimes is iface
                toks = ln.split()
                if toks:
                    iface = toks[-1]
            mp[mac] = iface
        return mp

    def dhcp_clients_enriched(self, limit: int = 200) -> List[Dict[str, str]]:
        raw = self.show_dhcp_clients(limit=limit)
        clients = parse_dhcp_bindings(raw)
        amap = self.arp_iface_map()
        for c in clients:
            mac = c.get("mac", "").lower()
            if mac in amap:
                c["iface"] = amap[mac]
            else:
                c["iface"] = ""
        return clients

    def internet_check(self) -> Tuple[bool, str]:
        # ping IP + DNS (если есть nslookup/getent)
        ping_ok = False
        details = []
        rc, out = self.sh.run(["ping", "-c", "1", "-W", "2", "1.1.1.1"], timeout_sec=5)
        if rc == 0:
            ping_ok = True
            details.append("✅ ping 1.1.1.1 OK")
        else:
            details.append("❌ ping 1.1.1.1 FAIL")

        dns_ok = False
        if which("nslookup"):
            rc2, out2 = self.sh.run(["nslookup", "example.com"], timeout_sec=6)
            dns_ok = (rc2 == 0 and "Address" in out2)
        elif which("getent"):
            rc2, out2 = self.sh.run(["getent", "hosts", "example.com"], timeout_sec=6)
            dns_ok = (rc2 == 0 and bool(out2.strip()))
        else:
            out2 = "нет nslookup/getent"
            rc2 = 127

        if dns_ok:
            details.append("✅ DNS example.com OK")
        else:
            details.append("⚠️ DNS example.com FAIL/нет утилиты")

        ok = ping_ok and dns_ok
        return ok, "\n".join(details)

    def reboot(self) -> Tuple[int, str]:
        # Предпочитаем ndmc/ndmq, если есть
        if which("ndmc"):
            return self.sh.run(["ndmc", "-c", "system", "reboot"], timeout_sec=5)
        if which("ndmq"):
            return self.sh.run(["ndmq", "-c", "system", "reboot"], timeout_sec=5)
        return self.sh.run(["reboot"], timeout_sec=5)

    def show_dhcp_clients(self, limit: int = 80) -> str:
        # Попытка через ndmc, иначе — пусто
        if which("ndmc"):
            rc, out = self.sh.run(["ndmc", "-c", "show", "ip", "dhcp", "binding"], timeout_sec=10)
            if rc == 0 and out:
                lines = out.splitlines()
                if len(lines) > limit:
                    lines = lines[:limit] + ["… (обрезано)"]
                return "\n".join(lines)
        return "Недоступно (нет ndmc или команда не поддерживается)."

    def export_running_config(self) -> Tuple[bool, str, Optional[Path]]:
        if which("ndmc"):
            rc, out = self.sh.run(["ndmc", "-c", "show", "running-config"], timeout_sec=20)
            if rc == 0 and out:
                p = Path("/tmp/running-config.txt")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(out + "\n")
                return True, "running-config экспортирован", p
            return False, out or "Ошибка получения running-config", None
        return False, "ndmc не найден", None

    def basic_status_text(self) -> str:
        host = socket.gethostname()
        ip = self.lan_ip()
        up = self.uptime()
        l1, l5, l15 = self.loadavg()
        mem_total, mem_avail = self.meminfo()
        d_total, d_avail = self.disk_free_mb("/opt")
        ok_net, net_msg = self.internet_check()
        status = [
            f"🧠 <b>Router</b>: <code>{escape_html(host)}</code>",
            f"🏠 LAN IP: <code>{ip}</code>",
            f"⏱ Uptime: <code>{up}</code>",
            f"📈 Load: <code>{l1:.2f} {l5:.2f} {l15:.2f}</code>",
            f"🧩 RAM: <code>{mem_avail}/{mem_total} MB</code> (avail/total)",
            f"💾 /opt: <code>{d_avail}/{d_total} MB</code> (free/total)",
            "",
            f"🌐 Internet: {'✅ OK' if ok_net else '⚠️ проблемы'}",
            f"<code>{escape_html(net_msg)}</code>",
        ]
        return "\n".join(status)


class OpkgDriver:
    def __init__(self, sh: Shell):
        self.sh = sh
        self.lock = threading.Lock()

    def _opkg(self, args: List[str], timeout: int = 600) -> Tuple[int, str]:
        # opkg может висеть при проблемах со сетью — даём большой timeout, но с lock.
        with self.lock:
            return self.sh.run(["opkg"] + args, timeout_sec=timeout)

    def update(self) -> Tuple[int, str]:
        return self._opkg(["update"], timeout=600)

    def list_installed(self) -> Tuple[int, str]:
        return self._opkg(["list-installed"], timeout=60)

    def list_upgradable(self) -> Tuple[int, str]:
        return self._opkg(["list-upgradable"], timeout=120)

    def upgrade(self, pkgs: Optional[List[str]] = None) -> Tuple[int, str]:
        if pkgs:
            # безопасно: только имя пакета, без опций
            safe = [p for p in pkgs if re.fullmatch(r"[a-zA-Z0-9._+-]+", p)]
            return self._opkg(["upgrade"] + safe, timeout=900)
        return self._opkg(["upgrade"], timeout=900)

    def install(self, pkg: str) -> Tuple[int, str]:
        if not re.fullmatch(r"[a-zA-Z0-9._+-]+", pkg):
            return 2, "Некорректное имя пакета"
        return self._opkg(["install", pkg], timeout=600)

    def remove(self, pkg: str) -> Tuple[int, str]:
        if not re.fullmatch(r"[a-zA-Z0-9._+-]+", pkg):
            return 2, "Некорректное имя пакета"
        return self._opkg(["remove", pkg], timeout=600)

    def target_versions(self) -> Dict[str, str]:
        rc, out = self.list_installed()
        versions: Dict[str, str] = {}
        if rc != 0:
            return versions
        for line in out.splitlines():
            # format: pkg - version
            m = re.match(r"^([^\s]+)\s+-\s+(.+)$", line.strip())
            if not m:
                continue
            pkg, ver = m.group(1), m.group(2)
            if pkg in TARGET_PKGS:
                versions[pkg] = ver
        return versions


class HydraRouteDriver:
    def __init__(self, sh: Shell, opkg: OpkgDriver, router: RouterDriver):
        self.sh = sh
        self.opkg = opkg
        self.router = router

    def is_neo_available(self) -> bool:
        return which("neo") is not None or Path("/opt/bin/neo").exists()

    def is_classic_available(self) -> bool:
        return which("hr") is not None or Path("/opt/bin/hr").exists()

    def neo_cmd(self, sub: str) -> Tuple[int, str]:
        # Управление из документации: neo start/stop/restart/status
        return self.sh.run(["neo", sub], timeout_sec=30)

    def classic_cmd(self, sub: str) -> Tuple[int, str]:
        return self.sh.run(["hr", sub], timeout_sec=30)

    def status_text(self) -> str:
        parts = ["🧬 <b>HydraRoute</b>"]
        if self.is_neo_available():
            rc, out = self.neo_cmd("status")
            parts.append(f"• Neo: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
            if out and self.sh.debug:
                parts.append(fmt_code(out[:900]))
            if ("hrweb" in self.opkg.target_versions()) or Path("/opt/share/hrweb").exists() or Path("/opt/etc/init.d/S50hrweb").exists():
                parts.append(f"• HRweb: <code>http://{self.router.lan_ip()}:2000</code>")
            else:
                parts.append("• HRweb: ➖ (не установлен)")
        elif self.is_classic_available():
            rc, out = self.classic_cmd("status")
            parts.append(f"• Classic: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
            if out and self.sh.debug:
                parts.append(fmt_code(out[:900]))
        else:
            parts.append("Не найдено (нет neo/hr).")
        # Версии пакетов
        vers = self.opkg.target_versions()
        for k in ("hrneo", "hrweb", "hydraroute"):
            if k in vers:
                parts.append(f"• {k}: <code>{escape_html(vers[k])}</code>")
        return "\n".join(parts)

    def installed_variant(self) -> str:
        if self.is_neo_available():
            return "neo"
        if self.is_classic_available():
            return "classic"
        return "none"

    def diag_ipset(self) -> str:
        if not which("ipset"):
            return "ipset не установлен/не найден."
        rc, out = self.sh.run(["ipset", "list", "-name"], timeout_sec=15)
        if rc != 0:
            return out or "Ошибка ipset"
        names = [x.strip() for x in out.splitlines() if x.strip()]
        # фильтруем hydraroute наборы по префиксам (часто HR_*)
        hr_names = [n for n in names if "Hydra" in n or n.lower().startswith(("hr", "hydra"))]
        show = hr_names[:60] if hr_names else names[:60]
        return "IPSet (первые 60):\n" + "\n".join(show)

    def diag_iptables(self) -> str:
        if not which("iptables"):
            return "iptables не найден."
        rc, out = self.sh.run(["iptables", "-t", "mangle", "-S"], timeout_sec=20)
        if rc != 0:
            return out or "Ошибка iptables"
        # вытащим строки с MARK/ipset/nflog
        lines = []
        for ln in out.splitlines():
            if any(k in ln for k in ("ipset", "MARK", "NFLOG", "Hydra", "hrneo", "HydraRoute")):
                lines.append(ln)
        if not lines:
            lines = out.splitlines()[:80] + ["… (обрезано)"]
        return "\n".join(lines)

    def file_get(self, kind: str) -> Tuple[bool, str, Optional[Path]]:
        mapping = {
            "hrneo.conf": HR_NEO_CONF,
            "domain.conf": HR_DOMAIN_CONF,
            "ip.list": HR_IP_LIST,
        }
        p = mapping.get(kind)
        if not p:
            return False, "Неизвестный файл", None
        if not p.exists():
            return False, f"Файл не найден: {p}", None
        return True, str(p), p

    def file_put(self, kind: str, content: str) -> Tuple[bool, str]:
        mapping = {
            "hrneo.conf": HR_NEO_CONF,
            "domain.conf": HR_DOMAIN_CONF,
            "ip.list": HR_IP_LIST,
        }
        p = mapping.get(kind)
        if not p:
            return False, "Неизвестный файл"
        return self.sh.write_file(p, content)

    def add_domain(self, domains: List[str], target: str) -> Tuple[bool, str]:
        """
        Добавить домены в domain.conf.
        Формат строки: домен1,домен2/Target
        """
        if not domains:
            return False, "Пустой список доменов"
        # валидация
        ok_domains = []
        for d in domains:
            d = d.strip().lower()
            if not d:
                continue
            # разрешаем geosite:TAG
            if d.startswith("geosite:"):
                if re.fullmatch(r"geosite:[A-Za-z0-9_-]{1,40}", d):
                    ok_domains.append(d)
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9\.-]{1,250}[a-z0-9]", d) or re.fullmatch(r"[a-z0-9]{1,63}", d):
                ok_domains.append(d)
        if not ok_domains:
            return False, "Не нашёл валидных доменов (разрешены домены и geosite:TAG)."

        # читаем файл
        if not HR_DOMAIN_CONF.exists():
            HR_DOMAIN_CONF.parent.mkdir(parents=True, exist_ok=True)
            HR_DOMAIN_CONF.write_text("", encoding="utf-8")
        text = HR_DOMAIN_CONF.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        target = target.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", target):
            return False, "Некорректное имя политики/интерфейса."

        # Ищем существующую строку вида ".../target" без geosite-only (чтобы не ломать)
        inserted = False
        new_lines = []
        for ln in lines:
            stripped = ln.strip()
            if (not inserted
                and stripped
                and not stripped.startswith("#")
                and "/" in stripped
                and stripped.rsplit("/", 1)[1] == target
                and "geosite:" not in stripped
            ):
                left, right = stripped.rsplit("/", 1)
                existing = [x.strip() for x in left.split(",") if x.strip()]
                merged = existing + [d for d in ok_domains if d not in existing]
                new_lines.append(",".join(merged) + "/" + right)
                inserted = True
            else:
                new_lines.append(ln)
        if not inserted:
            new_lines.append(",".join(ok_domains) + "/" + target)

        ok, msg = self.sh.write_file(HR_DOMAIN_CONF, "\n".join(new_lines) + "\n")
        if ok and self.is_neo_available():
            self.neo_cmd("restart")
        return ok, msg + ("\nNeo перезапущен." if ok and self.is_neo_available() else "")

    def remove_domain(self, domain: str) -> Tuple[bool, str]:
        domain = domain.strip().lower()
        if not domain:
            return False, "Пустой домен"
        if not HR_DOMAIN_CONF.exists():
            return False, "domain.conf не найден"
        text = HR_DOMAIN_CONF.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        changed = False
        new_lines = []
        for ln in lines:
            stripped = ln.strip()
            if not stripped or stripped.startswith("#") or "/" not in stripped:
                new_lines.append(ln)
                continue
            left, right = stripped.rsplit("/", 1)
            items = [x.strip() for x in left.split(",") if x.strip()]
            if domain in items:
                items = [x for x in items if x != domain]
                changed = True
                if items:
                    new_lines.append(",".join(items) + "/" + right)
                else:
                    # если больше ничего не осталось — комментируем строку, чтобы не потерять target
                    new_lines.append("# " + stripped)
            else:
                new_lines.append(ln)

        if not changed:
            return False, "Не нашёл домен в domain.conf"
        ok, msg = self.sh.write_file(HR_DOMAIN_CONF, "\n".join(new_lines) + "\n")
        if ok and self.is_neo_available():
            self.neo_cmd("restart")
        return ok, msg + ("\nNeo перезапущен." if ok and self.is_neo_available() else "")


    def parse_domain_conf(self) -> Tuple[bool, str, List[Tuple[int, str, str, List[str]]]]:
        """Парсит domain.conf: (line_no, raw_line, target, domains[])."""
        if not HR_DOMAIN_CONF.exists():
            return False, "domain.conf не найден", []
        try:
            lines = HR_DOMAIN_CONF.read_text(encoding="utf-8", errors="replace").splitlines()
            rules: List[Tuple[int, str, str, List[str]]] = []
            for i, ln in enumerate(lines, start=1):
                s = ln.strip()
                if not s or s.startswith("#") or "/" not in s:
                    continue
                left, target = s.rsplit("/", 1)
                domains = [x.strip() for x in left.split(",") if x.strip()]
                rules.append((i, ln, target.strip(), domains))
            return True, "OK", rules
        except Exception as e:
            return False, str(e), []

    def domain_summary(self, limit_targets: int = 25) -> str:
        ok, msg, rules = self.parse_domain_conf()
        if not ok:
            return msg
        per_target: Dict[str, int] = {}
        total = 0
        for _, _, target, domains in rules:
            per_target[target] = per_target.get(target, 0) + len(domains)
            total += len(domains)
        items = sorted(per_target.items(), key=lambda x: x[1], reverse=True)
        head = [f"Всего доменов: {total}", f"Правил: {len(rules)}", ""]
        for t, c in items[:limit_targets]:
            head.append(f"{t}: {c}")
        if len(items) > limit_targets:
            head.append("… (обрезано)")
        return "\n".join(head)

    def find_domain(self, query: str, limit: int = 20) -> str:
        query = query.strip().lower()
        if not query:
            return "Пустой запрос"
        ok, msg, rules = self.parse_domain_conf()
        if not ok:
            return msg
        hits: List[str] = []
        for ln_no, _, target, domains in rules:
            for d in domains:
                if query in d.lower():
                    hits.append(f"#{ln_no} -> {target}: {d}")
                    break
            if len(hits) >= limit:
                break
        return "\n".join(hits) if hits else "Совпадений не найдено."

    def duplicates(self, limit: int = 50) -> str:
        ok, msg, rules = self.parse_domain_conf()
        if not ok:
            return msg
        seen: Dict[str, List[str]] = {}
        for _, _, target, domains in rules:
            for d in domains:
                k = d.lower()
                seen.setdefault(k, []).append(target)
        dup = [(d, tgts) for d, tgts in seen.items() if len(set(tgts)) > 1]
        dup.sort(key=lambda x: len(set(x[1])), reverse=True)
        lines: List[str] = []
        for d, tgts in dup[:limit]:
            uniq = sorted(set(tgts))
            lines.append(f"{d}: {', '.join(uniq)}")
        if not lines:
            return "Дубликатов не найдено."
        if len(dup) > limit:
            lines.append("… (обрезано)")
        return "\n".join(lines)


class NfqwsDriver:
    def __init__(self, sh: Shell, opkg: OpkgDriver, router: RouterDriver):
        self.sh = sh
        self.opkg = opkg
        self.router = router

    def installed(self) -> bool:
        return NFQWS_INIT.exists() or which("nfqws2") is not None

    def init_action(self, action: str) -> Tuple[int, str]:
        if NFQWS_INIT.exists():
            return self.sh.run([str(NFQWS_INIT), action], timeout_sec=30)
        # fallback: try service
        return 127, "init-скрипт nfqws2 не найден"

    def detect_mode(self) -> str:
        # 1) config
        if NFQWS_CONF.exists():
            ok, txt = self.sh.read_file(NFQWS_CONF, max_bytes=60_000)
            if ok:
                kv = parse_env_like(txt)
                for k in ("MODE", "NFQWS_MODE", "mode"):
                    if kv.get(k):
                        return str(kv.get(k))
        # 2) process args
        rc, out = self.sh.sh("ps w | grep -E 'nfqws2' | grep -v grep | head -n 1", timeout_sec=5)
        if out:
            m = re.search(r"(?:--mode|-m)\s+(\S+)", out)
            if m:
                return m.group(1)
        return "?"

    def status_text(self) -> str:
        parts = ["🧷 <b>NFQWS2</b>"]
        if not self.installed():
            parts.append("Не установлено.")
            return "\n".join(parts)
        rc, out = self.init_action("status")
        parts.append(f"• Service: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
        if out and self.sh.debug:
                parts.append(fmt_code(out[:900]))

        # конфиг summary
        if NFQWS_CONF.exists():
            ok, txt = self.sh.read_file(NFQWS_CONF, max_bytes=60_000)
            if ok:
                # вытащим пару ключей
                kv = parse_env_like(txt)
                iface = kv.get("ISP_INTERFACE") or kv.get("ISP_IFACE") or kv.get("IFACE") or "?"
                ipv6 = kv.get("IPV6_ENABLED") or kv.get("IPV6") or "?"
                mode = self.detect_mode()
                parts.append(f"• iface: <code>{escape_html(str(iface))}</code>  ipv6: <code>{escape_html(str(ipv6))}</code>  mode: <code>{escape_html(str(mode))}</code>")

        parts.append(f"• Logs: <code>{NFQWS_LOG}</code>")
        if NFQWS_WEB_CONF.exists() or Path("/opt/share/nfqws-web").exists() or ("nfqws-keenetic-web" in self.opkg.target_versions()):
            parts.append(f"• WebUI: <code>{self.web_url()}</code>")
        else:
            parts.append("• WebUI: ➖ (не установлен)")
        return "\n".join(parts)

    def web_url(self) -> str:
        ip = self.router.lan_ip()
        port = self.web_port()
        return f"http://{ip}:{port}"

    def web_port(self) -> int:
        # по умолчанию 90 (как в описаниях), но пытаемся прочитать конфиг
        if NFQWS_WEB_CONF.exists():
            ok, txt = self.sh.read_file(NFQWS_WEB_CONF, max_bytes=40_000)
            if ok:
                # ищем первое число порта
                m = re.search(r"\bport\s*=\s*(\d+)\b", txt, flags=re.I)
                if not m:
                    m = re.search(r"\bPORT\s*=\s*(\d+)\b", txt)
                if m:
                    p = int(m.group(1))
                    if 1 <= p <= 65535:
                        return p
        return 90

    def lists_stats(self) -> str:
        if not NFQWS_LISTS_DIR.exists():
            return "lists/ не найден."
        rows = []
        for fn in sorted(NFQWS_LISTS_DIR.glob("*.list")):
            try:
                cnt = sum(1 for _ in open(fn, "r", encoding="utf-8", errors="ignore") if _.strip() and not _.lstrip().startswith("#"))
            except Exception:
                cnt = -1
            rows.append(f"{fn.name}: {cnt}")
        return "\n".join(rows) if rows else "Нет *.list"

    def add_to_list(self, list_name: str, domains: List[str]) -> Tuple[bool, str]:
        target = NFQWS_LISTS_DIR / list_name
        if not target.exists():
            return False, f"Файл не найден: {target}"
        ok_domains = []
        for d in domains:
            d = d.strip().lower()
            if not d:
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9\.-]{1,250}[a-z0-9]", d) or re.fullmatch(r"[a-z0-9]{1,63}", d):
                ok_domains.append(d)
        if not ok_domains:
            return False, "Нет валидных доменов."
        # читаем/дописываем уникально
        try:
            existing = set()
            with open(target, "r", encoding="utf-8", errors="ignore") as f:
                for ln in f:
                    ln = ln.strip().lower()
                    if ln and not ln.startswith("#"):
                        existing.add(ln)
            new = [d for d in ok_domains if d not in existing]
            if not new:
                return True, "Уже есть в списке."
            bkp = self.sh.backup_file(target)
            with open(target, "a", encoding="utf-8") as f:
                for d in new:
                    f.write(d + "\n")
            # reload
            self.init_action("reload")
            return True, f"Добавлено: {', '.join(new)}\nФайл: {target}" + (f"\nБэкап: {bkp}" if bkp else "")
        except Exception as e:
            return False, f"Ошибка: {e}"

    def clear_list(self, list_name: str) -> Tuple[bool, str]:
        target = NFQWS_LISTS_DIR / list_name
        if not target.exists():
            return False, f"Файл не найден: {target}"
        ok, msg = self.sh.write_file(target, "")
        if ok:
            self.init_action("reload")
        return ok, msg + ("\nreload выполнен." if ok else "")

    def diag_iptables_queue(self) -> str:
        if not which("iptables"):
            return "iptables не найден."
        # ищем NFQUEUE 300 (по докам nfqws2 использует queue-num 300)
        rc, out = self.sh.run(["iptables", "-t", "mangle", "-S"], timeout_sec=20)
        if rc != 0:
            return out or "Ошибка iptables"
        q_lines = [ln for ln in out.splitlines() if "NFQUEUE" in ln or "queue-num" in ln]
        if not q_lines:
            return "Не нашёл правил NFQUEUE в iptables -t mangle."
        # подсветим queue-num 300
        show = []
        for ln in q_lines[:80]:
            show.append(ln)
        if len(q_lines) > 80:
            show.append("… (обрезано)")
        return "\n".join(show)


class AwgDriver:
    def __init__(self, sh: Shell, opkg: OpkgDriver, router: RouterDriver):
        self.sh = sh
        self.opkg = opkg
        self.router = router

    def installed(self) -> bool:
        return AWG_INIT.exists() or which("awg-manager") is not None or Path("/opt/bin/awg-manager").exists()

    def init_action(self, action: str) -> Tuple[int, str]:
        if AWG_INIT.exists():
            return self.sh.run([str(AWG_INIT), action], timeout_sec=30)
        # fallback
        if which("awg-manager"):
            return self.sh.run(["awg-manager", "--service", action], timeout_sec=30)
        return 127, "awg-manager не найден"

    def web_port(self) -> int:
        # settings.json содержит порт (install.sh: /opt/etc/awg-manager/settings.json)
        if AWG_SETTINGS.exists():
            try:
                raw = json.loads(AWG_SETTINGS.read_text(encoding="utf-8"))
                p = int(raw.get("port") or raw.get("listenPort") or raw.get("listen_port") or 2222)
                if 1 <= p <= 65535:
                    return p
            except Exception:
                pass
        return 2222

    def web_url(self) -> str:
        return f"http://{self.router.lan_ip()}:{self.web_port()}"

    def health_check(self) -> Tuple[bool, str]:
        # без внешних зависимостей: пробуем curl/wget, иначе сокетом
        port = self.web_port()
        url = f"http://127.0.0.1:{port}/api/health"
        if which("curl"):
            rc, out = self.sh.run(["curl", "-sS", "--max-time", "3", url], timeout_sec=5)
            return (rc == 0 and out != ""), out if out else ("curl error" if rc != 0 else "empty")
        if which("wget"):
            rc, out = self.sh.run(["wget", "-qO-", url], timeout_sec=5)
            return (rc == 0 and out != ""), out if out else ("wget error" if rc != 0 else "empty")
        # минимальный HTTP GET через socket
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=3)
            req = f"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            s.sendall(req.encode("ascii"))
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            s.close()
            text = data.decode("utf-8", errors="replace")
            # crude parse
            body = text.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in text else text
            return True, body.strip()[:1000]
        except Exception as e:
            return False, str(e)


    def api_request(self, endpoint: str, method: str = "GET", body: Optional[dict] = None, timeout: int = 8) -> Tuple[bool, str, Optional[dict]]:
        """
        Универсальный запрос к AWG Manager API.
        endpoint: путь после /api, например '/tunnels/list'
        Возвращает (ok, message, json_dict)
        """
        port = self.web_port()
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = f"http://127.0.0.1:{port}/api{endpoint}"

        data = None
        headers = {
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        try:
            req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                ct = resp.headers.get("Content-Type", "")
        except Exception as e:
            return False, f"HTTP error: {e}", None

        if "application/json" not in (ct or ""):
            # иногда может отдать html
            return False, f"Non-JSON response ({ct}): {raw[:200]}", None

        try:
            j = json.loads(raw)
        except Exception as e:
            return False, f"JSON parse error: {e}", None

        # Частый формат: {error, message, data}
        if isinstance(j, dict) and (j.get("error") or j.get("success") is False):
            return False, j.get("message") or j.get("error") or "API error", j

        data_obj = j.get("data") if isinstance(j, dict) else j
        return True, "OK", data_obj if isinstance(data_obj, (dict, list)) else j

    def api_get(self, endpoint: str, timeout: int = 8) -> Tuple[bool, str, Optional[dict]]:
        return self.api_request(endpoint, "GET", None, timeout)

    def api_post(self, endpoint: str, body: Optional[dict] = None, timeout: int = 12) -> Tuple[bool, str, Optional[dict]]:
        return self.api_request(endpoint, "POST", body, timeout)

    def api_quick_summary(self) -> str:
        ok1, msg1, sysinfo = self.api_get("/system/info")
        ok2, msg2, wan = self.api_get("/wan/status")
        ok3, msg3, st = self.api_get("/status/all")
        parts = []
        parts.append("API: " + ("✅" if (ok1 or ok2 or ok3) else "⚠️"))
        if ok1 and isinstance(sysinfo, dict):
            # попытка вытащить пару полей
            parts.append(f"Версия: {sysinfo.get('version') or sysinfo.get('appVersion') or '?'}")
            parts.append(f"Backend: {sysinfo.get('backend') or sysinfo.get('mode') or '?'}")
        if ok2 and isinstance(wan, (dict, list)):
            parts.append("WAN: OK")
        if ok3 and isinstance(st, (dict, list)):
            parts.append("Tunnels status: OK")
        if not parts:
            return f"API недоступен: {msg1 or msg2 or msg3}"
        return "\n".join(parts)
    def wg_status(self) -> str:
        # Пытаемся показать wg/amneziawg
        if which("wg"):
            rc, out = self.sh.run(["wg", "show"], timeout_sec=10)
            return out if rc == 0 and out else (out or "wg show пусто/ошибка")
        if which("amneziawg"):
            rc, out = self.sh.run(["amneziawg", "show"], timeout_sec=10)
            return out if rc == 0 and out else (out or "amneziawg show пусто/ошибка")
        return "Не найдено: wg/amneziawg."

    def status_text(self) -> str:
        parts = ["🧿 <b>AWG Manager</b>"]
        if not self.installed():
            parts.append("Не установлено.")
            return "\n".join(parts)
        rc, out = self.init_action("status")
        parts.append(f"• Service: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
        if out and self.sh.debug:
                parts.append(fmt_code(out[:900]))
        if NFQWS_WEB_CONF.exists() or Path("/opt/share/nfqws-web").exists() or ("nfqws-keenetic-web" in self.opkg.target_versions()):
            parts.append(f"• WebUI: <code>{self.web_url()}</code>")
        else:
            parts.append("• WebUI: ➖ (не установлен)")
        ok, h = self.health_check()
        parts.append(f"• Health: {'✅' if ok else '⚠️'} <code>{escape_html(h[:500])}</code>")
        vers = self.opkg.target_versions()
        if "awg-manager" in vers:
            parts.append(f"• awg-manager: <code>{escape_html(vers['awg-manager'])}</code>")
        return "\n".join(parts)


# -----------------------------
# Парсеры конфигов (env-like)
# -----------------------------
def parse_env_like(text: str) -> Dict[str, str]:
    """
    Парсит конфиги вида KEY=VALUE, игнорируя комментарии.
    """
    kv: Dict[str, str] = {}
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            kv[k] = v
    return kv


# -----------------------------
# Меню / UI
# -----------------------------
def kb_row(*btns: Tuple[str, str]) -> List[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=t, callback_data=d) for t, d in btns]


def kb_home_back(home: str = "m:main", back: str = "m:main") -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🏠 Home", callback_data=home),
        InlineKeyboardButton("⬅️ Back", callback_data=back),
    )
    return kb


def kb_main(snapshot: Dict[str, str], caps: Dict[str, bool]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()

    # Router всегда доступен
    kb.row(
        InlineKeyboardButton(f"🧠 Роутер {snapshot.get('router', '')}", callback_data="m:router"),
    )

    # HydraRoute
    if caps.get("hydra"):
        kb.row(
            InlineKeyboardButton(f"🧬 HydraRoute {snapshot.get('hydra', '')}", callback_data="m:hydra"),
        )
    else:
        kb.row(
            InlineKeyboardButton("🧬 HydraRoute ➕ (не установлен)", callback_data="m:install"),
        )

    # NFQWS2
    if caps.get("nfqws2"):
        kb.row(
            InlineKeyboardButton(f"🧷 NFQWS2 {snapshot.get('nfqws', '')}", callback_data="m:nfqws"),
        )
    else:
        kb.row(
            InlineKeyboardButton("🧷 NFQWS2 ➕ (не установлен)", callback_data="m:install"),
        )

    # AWG
    if caps.get("awg"):
        kb.row(
            InlineKeyboardButton(f"🧿 AWG {snapshot.get('awg', '')}", callback_data="m:awg"),
        )
    else:
        kb.row(
            InlineKeyboardButton("🧿 AWG ➕ (не установлен)", callback_data="m:install"),
        )

    kb.row(
        InlineKeyboardButton("📦 OPKG", callback_data="m:opkg"),
        InlineKeyboardButton("📝 Логи", callback_data="m:logs"),
    )

    # Установка/сервис (если что-то отсутствует)
    if (not caps.get("hydra")) or (not caps.get("nfqws2")) or (not caps.get("awg")) or (not caps.get("cron")):
        kb.row(InlineKeyboardButton("🧩 Установка/Сервис", callback_data="m:install"))

    kb.row(InlineKeyboardButton("⚙️ Настройки", callback_data="m:settings"))

    return kb



def kb_router() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="router:status"),
        InlineKeyboardButton("🌐 Интернет тест", callback_data="router:net"),
    )
    kb.row(
        InlineKeyboardButton("👥 DHCP клиенты", callback_data="router:dhcpmenu"),
        InlineKeyboardButton("🌐 Сеть", callback_data="router:netmenu"),
    )
    kb.row(
        InlineKeyboardButton("🧱 Firewall", callback_data="router:fwmenu"),
        InlineKeyboardButton("📤 Export config", callback_data="router:exportcfg"),
    )
    kb.row(
        InlineKeyboardButton("🔄 Reboot", callback_data="router:reboot?confirm=1"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_router_net() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📡 ip addr (brief)", callback_data="router:ipaddr_br"),
        InlineKeyboardButton("🧭 ip route (v4)", callback_data="router:iproute4"),
    )
    kb.row(
        InlineKeyboardButton("🧭 ip route (v6)", callback_data="router:iproute6"),
        InlineKeyboardButton("⬅️ Back", callback_data="m:router"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_router_fw() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("mangle summary", callback_data="router:iptables:sum:mangle"),
        InlineKeyboardButton("mangle raw", callback_data="router:iptables:raw:mangle"),
    )
    kb.row(
        InlineKeyboardButton("filter summary", callback_data="router:iptables:sum:filter"),
        InlineKeyboardButton("filter raw", callback_data="router:iptables:raw:filter"),
    )
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="m:router"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_router_dhcp() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("LAN", callback_data="router:dhcp:list:lan"),
        InlineKeyboardButton("Wi‑Fi", callback_data="router:dhcp:list:wifi"),
        InlineKeyboardButton("All", callback_data="router:dhcp:list:all"),
    )
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="m:router"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb



def kb_hydra(variant: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="hydra:status"),
        InlineKeyboardButton("🛠 Диагностика", callback_data="hydra:diag"),
    )
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data="hydra:start"),
        InlineKeyboardButton("⏹ Stop", callback_data="hydra:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data="hydra:restart"),
    )
    if variant == "neo":
        kb.row(
            InlineKeyboardButton("🌐 HRweb (2000)", callback_data="hydra:hrweb"),
        )
        kb.row(
            InlineKeyboardButton("📄 domain.conf", callback_data="hydra:file:domain.conf"),
            InlineKeyboardButton("📄 ip.list", callback_data="hydra:file:ip.list"),
        )
        kb.row(
            InlineKeyboardButton("⚙️ hrneo.conf", callback_data="hydra:file:hrneo.conf"),
        )
        kb.row(
            InlineKeyboardButton("📚 Правила", callback_data="hydra:rules"),
            InlineKeyboardButton("🔎 Поиск домена", callback_data="hydra:search_domain"),
        )
        kb.row(
            InlineKeyboardButton("🧩 Дубликаты", callback_data="hydra:dupes"),
            InlineKeyboardButton("⬆️ Импорт domain.conf", callback_data="hydra:import:domain.conf"),
        )
        kb.row(
            InlineKeyboardButton("➕ Add domain", callback_data="hydra:add_domain"),
            InlineKeyboardButton("➖ Remove domain", callback_data="hydra:rm_domain"),
        )
    kb.row(
        InlineKeyboardButton("⬆️ Обновить (opkg)", callback_data="hydra:update?confirm=1"),
        InlineKeyboardButton("🗑 Удалить", callback_data="hydra:remove?confirm=1"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_nfqws() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="nfqws:status"),
        InlineKeyboardButton("🛠 Диагностика", callback_data="nfqws:diag"),
    )
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data="nfqws:start"),
        InlineKeyboardButton("⏹ Stop", callback_data="nfqws:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data="nfqws:restart"),
        InlineKeyboardButton("♻️ Reload", callback_data="nfqws:reload"),
    )
    kb.row(
        InlineKeyboardButton("🌐 WebUI", callback_data="nfqws:web"),
        InlineKeyboardButton("📄 nfqws2.conf", callback_data="nfqws:file:nfqws2.conf"),
    )
    kb.row(
        InlineKeyboardButton("📚 Lists stats", callback_data="nfqws:lists"),
        InlineKeyboardButton("📄 user.list", callback_data="nfqws:filelist:user.list"),
        InlineKeyboardButton("📄 exclude.list", callback_data="nfqws:filelist:exclude.list"),
    )
    kb.row(
        InlineKeyboardButton("📄 auto.list", callback_data="nfqws:filelist:auto.list"),
        InlineKeyboardButton("⬆️ Импорт списка", callback_data="nfqws:import:list?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("➕ + user.list", callback_data="nfqws:add:user.list"),
        InlineKeyboardButton("🚫 + exclude.list", callback_data="nfqws:add:exclude.list"),
    )
    kb.row(
        InlineKeyboardButton("🧹 Clear auto.list", callback_data="nfqws:clear:auto.list?confirm=1"),
        InlineKeyboardButton("📜 Tail log", callback_data="nfqws:log"),
    )
    kb.row(
        InlineKeyboardButton("⬆️ Обновить (opkg)", callback_data="nfqws:update?confirm=1"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_awg() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="awg:status"),
        InlineKeyboardButton("💓 Health", callback_data="awg:health"),
    )
    kb.row(
        InlineKeyboardButton("🧭 Туннели", callback_data="awg:api:tunnels"),
        InlineKeyboardButton("📊 Status all", callback_data="awg:api:statusall"),
    )
    kb.row(
        InlineKeyboardButton("🧾 API logs", callback_data="awg:api:logs"),
        InlineKeyboardButton("ℹ️ System/WAN", callback_data="awg:api:systeminfo"),
    )
    kb.row(
        InlineKeyboardButton("🧪 Diag run", callback_data="awg:api:diagr"),
        InlineKeyboardButton("🧪 Diag status", callback_data="awg:api:diags"),
    )
    kb.row(
        InlineKeyboardButton("⬆️ Update check", callback_data="awg:api:updatecheck"),
        InlineKeyboardButton("⬆️ Apply update", callback_data="awg:api:updateapply?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data="awg:start"),
        InlineKeyboardButton("⏹ Stop", callback_data="awg:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data="awg:restart"),
    )
    kb.row(
        InlineKeyboardButton("🌐 WebUI", callback_data="awg:web"),
        InlineKeyboardButton("🧵 wg show", callback_data="awg:wg"),
    )
    kb.row(InlineKeyboardButton("⬅️ Back", callback_data="m:main"))
    return kb

def kb_awg_tunnel(idx: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data=f"awg:tunnelact:{idx}:start"),
        InlineKeyboardButton("⏹ Stop", callback_data=f"awg:tunnelact:{idx}:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data=f"awg:tunnelact:{idx}:restart"),
    )
    kb.row(
        InlineKeyboardButton("✅ Enable/Disable", callback_data=f"awg:tunnelact:{idx}:toggle"),
        InlineKeyboardButton("🧭 Default route", callback_data=f"awg:tunnelact:{idx}:default"),
    )
    kb.row(
        InlineKeyboardButton("📋 Details", callback_data=f"awg:tunnel:{idx}"),
        InlineKeyboardButton("⬅️ Back", callback_data="awg:api:tunnels"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_opkg() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🔄 opkg update", callback_data="opkg:update"),
        InlineKeyboardButton("⬆️ list-upgradable", callback_data="opkg:upg"),
    )
    kb.row(
        InlineKeyboardButton("📦 версии пакетов", callback_data="opkg:versions"),
        InlineKeyboardButton("⬆️ upgrade TARGET", callback_data="opkg:upgrade?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("📃 list-installed (target)", callback_data="opkg:installed"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_logs() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📜 bot log", callback_data="logs:bot"),
        InlineKeyboardButton("📜 nfqws2.log", callback_data="logs:nfqws"),
    )
    kb.row(
        InlineKeyboardButton("📜 hrneo.log", callback_data="logs:hrneo"),
        InlineKeyboardButton("📜 dmesg", callback_data="logs:dmesg"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_install(caps: Dict[str, bool]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    # Предлагаем то, чего нет
    if not caps.get("hydra"):
        kb.row(InlineKeyboardButton("➕ Установить HydraRoute Neo", callback_data="install:hydra?confirm=1"))
    if not caps.get("nfqws2"):
        kb.row(InlineKeyboardButton("➕ Установить NFQWS2", callback_data="install:nfqws2?confirm=1"))
    if caps.get("nfqws2") and (not caps.get("nfqws_web")):
        kb.row(InlineKeyboardButton("➕ Установить NFQWS web", callback_data="install:nfqwsweb?confirm=1"))
    if not caps.get("awg"):
        kb.row(InlineKeyboardButton("➕ Установить AWG Manager", callback_data="install:awg?confirm=1"))
    if not caps.get("cron"):
        kb.row(InlineKeyboardButton("➕ Установить cron", callback_data="install:cron?confirm=1"))

    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_confirm(action_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Подтвердить", callback_data=action_cb),
        InlineKeyboardButton("❌ Отмена", callback_data=back_cb),
    )
    return kb


def kb_notice_actions(primary_cb: str = "m:main", restart_cb: str | None = None, logs_cb: str | None = None) -> InlineKeyboardMarkup:
    """Inline-кнопки для уведомлений: Меню / Restart / Логи."""
    kb = InlineKeyboardMarkup()
    row = [InlineKeyboardButton("🏠 Меню", callback_data=primary_cb)]
    if restart_cb:
        row.append(InlineKeyboardButton("🔄 Restart", callback_data=restart_cb))
    if logs_cb:
        row.append(InlineKeyboardButton("📝 Логи", callback_data=logs_cb))
    kb.row(*row)
    return kb


# -----------------------------
# Pending interactions
# -----------------------------
@dataclass
class Pending:
    kind: str
    data: Dict[str, Any]
    expires_at: float


class PendingStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[Tuple[int, int], Pending] = {}

    def set(self, chat_id: int, user_id: int, kind: str, data: Dict[str, Any], ttl_sec: int = 300) -> None:
        with self._lock:
            self._pending[(chat_id, user_id)] = Pending(kind=kind, data=data, expires_at=time.time() + ttl_sec)

    def pop(self, chat_id: int, user_id: int) -> Optional[Pending]:
        with self._lock:
            p = self._pending.pop((chat_id, user_id), None)
        if p and p.expires_at < time.time():
            return None
        return p

    def peek(self, chat_id: int, user_id: int) -> Optional[Pending]:
        with self._lock:
            p = self._pending.get((chat_id, user_id))
        if p and p.expires_at < time.time():
            return None
        return p


# -----------------------------
# Мониторинг / уведомления
# -----------------------------
class Monitor(threading.Thread):
    def __init__(
        self,
        bot: telebot.TeleBot,
        cfg: BotConfig,
        sh: Shell,
        router: RouterDriver,
        opkg: OpkgDriver,
        hydra: HydraRouteDriver,
        nfqws: NfqwsDriver,
        awg: AwgDriver,
    ):
        super().__init__(daemon=True)
        self.bot = bot
        self.cfg = cfg
        self.sh = sh
        self.router = router
        self.opkg = opkg
        self.hydra = hydra
        self.nfqws = nfqws
        self.awg = awg

        self._stop = threading.Event()

        self._last_opkg_check = 0.0
        self._last_net_check = 0.0

        self._last_upgradable: str = ""
        self._service_state: Dict[str, bool] = {}
        self._internet_state: Optional[bool] = None

        self._last_log_pos: Dict[Path, int] = {}
        self._notify_last: Dict[str, float] = {}

    def stop(self) -> None:
        self._stop.set()

    def _cooldown_ok(self, key: str, interval_sec: Optional[int] = None) -> bool:
        now = time.time()
        last = self._notify_last.get(key, 0)
        min_iv = interval_sec if interval_sec is not None else self.cfg.notify_cooldown_sec
        if now - last >= min_iv:
            self._notify_last[key] = now
            return True
        return False


    def _fmt_notice(self, title: str, summary_lines: list[str], details: str | None = None, hint: str | None = None) -> str:
        """
        Формирует читабельный текст уведомления (HTML).
        - title: заголовок
        - summary_lines: короткие строки-итоги
        - details: подробности (лог/вывод), будет оформлено как pre
        - hint: подсказка "что делать"
        """
        parts: list[str] = []
        parts.append(f"{title}")
        parts.append(f"🕒 <code>{escape_html(_now_ts())}</code>")
        if summary_lines:
            parts.append("")
            parts.extend(summary_lines)
        if hint:
            parts.append("")
            parts.append(f"👉 <b>Что сделать:</b> {escape_html(hint)}")
        if details:
            d = details.strip()
            if len(d) > 3200:
                d = d[-3200:]  # показываем хвост
            parts.append("")
            parts.append(f"<pre><code>{escape_html(d)}</code></pre>")
        return "\n".join(parts)

    def _notify_admins(self, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        # text already formatted HTML
        for uid in self.cfg.admins:
            try:
                self.bot.send_message(uid, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_markup)
            except Exception as e:
                log_line(f"notify error to {uid}: {e}")


    def _check_services(self) -> None:
        # грубая проверка: pidof по процессам/скриптам
        def pidof(name: str) -> bool:
            rc, out = self.sh.run(["pidof", name], timeout_sec=5)
            return rc == 0 and bool(out.strip())

        # HydraRoute Neo: process hrneo, Classic: hydraroute maybe; но используем status команду если есть
        hydra_up = False
        if self.hydra.is_neo_available():
            rc, _ = self.hydra.neo_cmd("status")
            hydra_up = (rc == 0) or pidof("hrneo")
        elif self.hydra.is_classic_available():
            rc, _ = self.hydra.classic_cmd("status")
            hydra_up = (rc == 0) or pidof("hydraroute")
        else:
            hydra_up = False

        nfqws_up = False
        if self.nfqws.installed():
            rc, _ = self.nfqws.init_action("status")
            nfqws_up = (rc == 0) or pidof("nfqws2")

        awg_up = False
        if self.awg.installed():
            rc, _ = self.awg.init_action("status")
            awg_up = (rc == 0) or pidof("awg-manager")

        current = {
            "hydra": hydra_up,
            "nfqws": nfqws_up,
            "awg": awg_up,
        }
        for k, v in current.items():
            prev = self._service_state.get(k)
            self._service_state[k] = v
            if prev is None:
                continue
            if prev and (not v) and self.cfg.notify_on_service_down and self._cooldown_ok(f"svc:{k}"):
                restart_cb = None
                logs_cb = None
                if k == "nfqws":
                    restart_cb = "nfqws:restart"
                    logs_cb = "logs:nfqws"
                elif k == "hydra":
                    restart_cb = "hydra:restart"
                    logs_cb = "logs:hrneo"
                elif k == "awg":
                    restart_cb = "awg:restart"
                self._notify_admins(
                    self._fmt_notice(
                        title=f"🚨 <b>Сервис остановлен</b>: <code>{k}</code>",
                        summary_lines=[f"Статус: <b>STOPPED</b>"],
                        hint="Открой /menu → нужный раздел → Status/Restart"
                    ),
                    reply_markup=kb_notice_actions(primary_cb="m:main", restart_cb=restart_cb, logs_cb=logs_cb)
                )

    def _check_internet(self) -> None:
        ok, msg = self.router.internet_check()
        prev = self._internet_state
        self._internet_state = ok
        if prev is None:
            return
        if prev and (not ok) and self.cfg.notify_on_internet_down and self._cooldown_ok("net:down"):
            self._notify_admins(
                self._fmt_notice(
                    title="🌐⚠️ <b>Интернет недоступен</b>",
                    summary_lines=["Проверка ping/DNS не прошла или нестабильна."],
                    details=msg,
                    hint="Проверь WAN/провайдера/маршрутизацию до api.telegram.org"
                ),
                reply_markup=kb_notice_actions(primary_cb="router:net", logs_cb="logs:bot")
            )
        if (not prev) and ok and self._cooldown_ok("net:up"):
            self._notify_admins(
                self._fmt_notice(
                    title="🌐✅ <b>Интернет восстановлен</b>",
                    summary_lines=["Доступ до сети снова есть."],
                    hint="Если бот/сервисы были недоступны — проверь Status в меню"
                ),
                reply_markup=kb_notice_actions(primary_cb="m:main")
            )

    def _check_resources(self) -> None:
        l1, _, _ = self.router.loadavg()
        _, free_mb = self.router.disk_free_mb("/opt")
        if l1 >= self.cfg.cpu_load_threshold and self._cooldown_ok("res:load", interval_sec=self.cfg.notify_load_interval_sec):
            self._notify_admins(
                self._fmt_notice(
                    title="📈⚠️ <b>Высокая нагрузка</b>",
                    summary_lines=[f"load1: <code>{l1:.2f}</code>"],
                    hint="Проверь процессы/логи (NFQWS2/Hydra/AWG), перезапусти при необходимости"
                ),
                reply_markup=kb_notice_actions(primary_cb="router:status", logs_cb="logs:bot")
            )
        if free_mb <= self.cfg.disk_free_mb_threshold and self._cooldown_ok("res:disk", interval_sec=self.cfg.notify_disk_interval_sec):
            is_usb, src = self.router.opt_storage_info()
            hint = "Удалить лишнее: очистить логи/кэш, убрать ненужные пакеты"
            if not is_usb:
                hint = "Похоже, /opt на внутренней памяти. Лучше перенести Entware на USB/SSD или освободить место (opkg remove, очистка логов)."
            self._notify_admins(
                self._fmt_notice(
                    title="💾⚠️ <b>Мало места на /opt</b>",
                    summary_lines=[f"Свободно: <code>{free_mb} MB</code>", f"Носитель: <code>{escape_html(src)}</code>"],
                    hint=hint
                ),
                reply_markup=kb_notice_actions(primary_cb="m:opkg")
            )

    def _check_opkg_updates(self) -> None:
        # делаем opkg update редко, но list-upgradable можно чаще после update
        if not self.cfg.notify_on_updates:
            return
        # update repo
        rc, out = self.opkg.update()
        if rc != 0:
            # не спамим
            if self._cooldown_ok("opkg:update_fail"):
                self._notify_admins(
                self._fmt_notice(
                    title="📦⚠️ <b>Ошибка opkg update</b>",
                    summary_lines=["Не удалось обновить списки пакетов."],
                    details=out,
                    hint="Проверь интернет/DNS и повтори позже (OPKG → opkg update)"
                ),
                reply_markup=kb_notice_actions(primary_cb="opkg:update", logs_cb="logs:bot")
            )
            return
        rc2, out2 = self.opkg.list_upgradable()
        if rc2 != 0:
            return
        if out2.strip() and out2.strip() != self._last_upgradable:
            self._last_upgradable = out2.strip()
            count = len([ln for ln in out2.splitlines() if ln.strip()])
            preview = "\n".join(out2.splitlines()[:20])
            self._notify_admins(
                self._fmt_notice(
                    title="📦⬆️ <b>Доступны обновления opkg</b>",
                    summary_lines=[f"Пакетов: <code>{count}</code>", "Первые строки:"],
                    details=preview,
                    hint="Открой /menu → OPKG → upgrade TARGET (или обнови нужные пакеты)"
                ),
                reply_markup=kb_notice_actions(primary_cb="m:opkg", restart_cb="opkg:upgrade?confirm=1")
            )

    def _tail_new_errors(self, path: Path, pattern: re.Pattern) -> Optional[str]:
        try:
            if not path.exists():
                return None
            size = path.stat().st_size
            pos = self._last_log_pos.get(path, max(0, size - 8192))
            if pos > size:
                pos = max(0, size - 8192)
            if size == pos:
                return None
            read_len = min(65536, size - pos)
            with open(path, "rb") as f:
                f.seek(pos)
                data = f.read(read_len)
            self._last_log_pos[path] = size
            text = data.decode("utf-8", errors="replace")
            # берём только строки с ошибками
            hits = [ln for ln in text.splitlines() if pattern.search(ln)]
            if not hits:
                return None
            # ограничим
            if len(hits) > 20:
                hits = hits[-20:]
            return "\n".join(hits)
        except Exception:
            return None

    def _check_logs(self) -> None:
        if not self.cfg.notify_on_log_errors:
            return
        err_re = re.compile(r"\b(ERROR|FATAL|PANIC)\b", re.I)
        for p, tag in [(Path(LOG_PATH), "bot"), (NFQWS_LOG, "nfqws2"), (HR_NEO_LOG_DEFAULT, "hrneo")]:
            hit = self._tail_new_errors(p, err_re)
            if hit and self._cooldown_ok(f"log:{tag}"):
                restart_cb = None
            logs_cb = "logs:bot"
            if tag == "nfqws2":
                restart_cb = "nfqws:restart"
                logs_cb = "logs:nfqws"
            elif tag == "hrneo":
                restart_cb = "hydra:restart"
                logs_cb = "logs:hrneo"
            self._notify_admins(
                self._fmt_notice(
                    title=f"🧾⚠️ <b>Ошибки в логах</b> (<code>{tag}</code>)",
                    summary_lines=["Найдены строки с ERROR/FATAL/PANIC (показан хвост)."],
                    details=hit,
                    hint="Открой /menu → Логи и проверь подробности; при необходимости Restart сервиса"
                ),
                reply_markup=kb_notice_actions(primary_cb="m:logs", restart_cb=restart_cb, logs_cb=logs_cb)
            )


    def _handle_install_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        """
        Мини-инсталлятор из бота. Все действия с подтверждением.
        """
        def confirm(title: str, do_cb: str):
            self.send_or_edit(
                chat_id,
                title,
                reply_markup=kb_confirm(do_cb, "m:install"),
                message_id=msg_id,
            )

        if data == "install:hydra?confirm=1":
            confirm(
                "➕ <b>Установить HydraRoute Neo</b>\n"
                "Будет выполнено:\n"
                "<code>opkg update && opkg install curl && curl -Ls https://ground-zerro.github.io/release/keenetic/install-neo.sh | sh</code>",
                "install:hydra!do",
            )
            return
        if data == "install:hydra!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю HydraRoute Neo…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            rc, out = self.sh.sh('opkg update && opkg install curl && curl -Ls "https://ground-zerro.github.io/release/keenetic/install-neo.sh" | sh', timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:nfqws2?confirm=1":
            confirm(
                "➕ <b>Установить NFQWS2</b>\n"
                "Будет добавлен feed и установлен <code>nfqws2-keenetic</code>.",
                "install:nfqws2!do",
            )
            return
        if data == "install:nfqws2!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю NFQWS2…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            script = """set -e
opkg update
opkg install ca-certificates wget-ssl
opkg remove wget-nossl || true
mkdir -p /opt/etc/opkg
if opkg print-architecture | grep -q aarch64-3.10; then
  FEED=https://nfqws.github.io/nfqws2-keenetic/aarch64
else
  FEED=https://nfqws.github.io/nfqws2-keenetic/aarch64
fi
echo "src/gz nfqws2-keenetic $FEED" > /opt/etc/opkg/nfqws2-keenetic.conf
opkg update
opkg install nfqws2-keenetic
"""
            rc, out = self.sh.sh(script, timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:nfqwsweb?confirm=1":
            confirm(
                "➕ <b>Установить NFQWS web</b>\n"
                "Будет добавлен feed и установлен <code>nfqws-keenetic-web</code>.",
                "install:nfqwsweb!do",
            )
            return
        if data == "install:nfqwsweb!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю NFQWS web…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            script = """set -e
opkg update
opkg install ca-certificates wget-ssl
opkg remove wget-nossl || true
mkdir -p /opt/etc/opkg
echo "src/gz nfqws-keenetic-web https://nfqws.github.io/nfqws-keenetic-web/all" > /opt/etc/opkg/nfqws-keenetic-web.conf
opkg update
opkg install nfqws-keenetic-web
"""
            rc, out = self.sh.sh(script, timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:awg?confirm=1":
            confirm(
                "➕ <b>Установить AWG Manager</b>\n"
                "Будет выполнено:\n"
                "<code>curl -sL https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh | sh</code>",
                "install:awg!do",
            )
            return
        if data == "install:awg!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю AWG Manager…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            rc, out = self.sh.sh('opkg update && opkg install ca-certificates curl && curl -sL "https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh" | sh', timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:cron?confirm=1":
            confirm(
                "➕ <b>Установить cron</b>\n"
                "Будет выполнено: <code>opkg update && opkg install cron</code>",
                "install:cron!do",
            )
            return
        if data == "install:cron!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю cron…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            rc, out = self.sh.sh("opkg update && opkg install cron && /opt/etc/init.d/S10cron start || true", timeout_sec=600)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        self.send_or_edit(chat_id, "Нечего устанавливать или неизвестная команда.", reply_markup=kb_install(self.capabilities()), message_id=msg_id)

    def run(self) -> None:
        log_line("monitor started")
        # init baseline
        try:
            self._check_services()
            self._check_internet()
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                self._check_services()
                self._check_resources()

                now = time.time()
                if now - self._last_net_check >= self.cfg.internet_check_interval_sec:
                    self._last_net_check = now
                    self._check_internet()

                if now - self._last_opkg_check >= self.cfg.opkg_update_interval_sec:
                    self._last_opkg_check = now
                    self._check_opkg_updates()

                self._check_logs()
            except Exception as e:
                log_line(f"monitor loop error: {e}")
            self._stop.wait(self.cfg.monitor_interval_sec)


# -----------------------------
# Telegram bot app
# -----------------------------
class App:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.bot = telebot.TeleBot(cfg.bot_token, parse_mode="HTML", threaded=True)
        self.sh = Shell(timeout_sec=cfg.command_timeout_sec, debug=cfg.debug_enabled, debug_output_max=cfg.debug_log_output_max)

        self.router = RouterDriver(self.sh)
        self.opkg = OpkgDriver(self.sh)
        self.hydra = HydraRouteDriver(self.sh, self.opkg, self.router)
        self.nfqws = NfqwsDriver(self.sh, self.opkg, self.router)
        self.awg = AwgDriver(self.sh, self.opkg, self.router)

        self.pending = PendingStore()
        self.awg_tunnel_cache: Dict[Tuple[int, int], Dict[str, Any]] = {}

        self.monitor: Optional[Monitor] = None
        if cfg.monitor_enabled:
            self.monitor = Monitor(self.bot, cfg, self.sh, self.router, self.opkg, self.hydra, self.nfqws, self.awg)

        self._register_handlers()

    # ---- ACL ----
    def is_admin(self, user_id: int) -> bool:
        return user_id in set(self.cfg.admins)

    def is_chat_allowed(self, chat_id: int, user_id: int) -> bool:
        if not self.is_admin(user_id):
            return False
        if not self.cfg.allow_chats:
            # разрешаем личку админам
            return chat_id == user_id
        return chat_id in set(self.cfg.allow_chats) or chat_id == user_id

    def _deny(self, chat_id: int) -> None:
        try:
            self.bot.send_message(chat_id, "⛔ Доступ запрещён.")
        except Exception:
            pass

    # ---- UI helpers ----
    def snapshot(self) -> Dict[str, str]:
        # короткий статус для главного меню
        snap = {}

        # router internet
        ok_net, _ = self.router.internet_check()
        snap["router"] = "✅" if ok_net else "⚠️"

        # hydra
        if self.hydra.is_neo_available() or self.hydra.is_classic_available():
            up = False
            if self.hydra.is_neo_available():
                rc, _ = self.hydra.neo_cmd("status")
                up = (rc == 0)
            else:
                rc, _ = self.hydra.classic_cmd("status")
                up = (rc == 0)
            snap["hydra"] = "✅" if up else "⛔"
        else:
            snap["hydra"] = "➖"

        # nfqws
        if self.nfqws.installed():
            rc, _ = self.nfqws.init_action("status")
            snap["nfqws"] = "✅" if rc == 0 else "⛔"
        else:
            snap["nfqws"] = "➖"

        # awg
        if self.awg.installed():
            rc, _ = self.awg.init_action("status")
            snap["awg"] = "✅" if rc == 0 else "⛔"
        else:
            snap["awg"] = "➖"

        return snap


    def capabilities(self) -> Dict[str, bool]:
        """
        Определяем, что реально установлено/доступно на роутере.
        Используется для меню (скрывать/помечать отсутствующие модули).
        """
        caps: Dict[str, bool] = {}
        caps["opkg"] = which("opkg") is not None
        caps["ndmc"] = which("ndmc") is not None
        caps["iptables"] = which("iptables") is not None
        caps["ipset"] = which("ipset") is not None

        # Hydra variants
        caps["hydra_neo"] = self.hydra.is_neo_available()
        caps["hydra_classic"] = self.hydra.is_classic_available()
        caps["hydra"] = caps["hydra_neo"] or caps["hydra_classic"]

        vers = self.opkg.target_versions() if caps["opkg"] else {}

        # HRweb: пакет или типичные файлы
        caps["hrweb"] = ("hrweb" in vers) or Path("/opt/share/hrweb").exists() or Path("/opt/etc/init.d/S50hrweb").exists()

        # NFQWS2 + web
        caps["nfqws2"] = self.nfqws.installed()
        caps["nfqws_web"] = ("nfqws-keenetic-web" in vers) or NFQWS_WEB_CONF.exists() or Path("/opt/share/nfqws-web").exists()

        # AWG manager
        caps["awg"] = self.awg.installed()

        # Cron (для автообновлений/планировщика)
        caps["cron"] = Path("/opt/etc/init.d/S10cron").exists()

        return caps


    def _awg_cache_set(self, chat_id: int, user_id: int, tunnels: List[dict], ttl_sec: int = 300) -> None:
        self.awg_tunnel_cache[(chat_id, user_id)] = {"expires": time.time() + ttl_sec, "tunnels": tunnels}

    def _awg_cache_get(self, chat_id: int, user_id: int) -> Optional[List[dict]]:
        v = self.awg_tunnel_cache.get((chat_id, user_id))
        if not v:
            return None
        if v.get("expires", 0) < time.time():
            self.awg_tunnel_cache.pop((chat_id, user_id), None)
            return None
        return v.get("tunnels")

    def send_or_edit(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        message_id: Optional[int] = None,
        disable_preview: bool = True,
    ) -> None:
        # Telegram limit 4096 for text; if too long - send as file
        if len(text) > 3900:
            # send as document
            tmp = Path("/tmp/tg-bot-output.txt")
            tmp.write_text(re.sub(r"<[^>]+>", "", text), encoding="utf-8", errors="replace")
            self.bot.send_document(chat_id, InputFile(str(tmp)), caption="Вывод слишком длинный, отправляю файлом.")
            return

        if message_id:
            try:
                self.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_preview,
                )
                return
            except Exception as e:
                # message is not modified / etc.
                log_line(f"edit_message_text error: {e}")

        self.bot.send_message(chat_id, text, reply_markup=reply_markup, disable_web_page_preview=disable_preview)

    # ---- Handlers ----
    def _register_handlers(self) -> None:
        @self.bot.message_handler(commands=["start", "menu"])
        def _start(m: Message) -> None:
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)
            text = self.render_main()
            self.send_or_edit(m.chat.id, text, reply_markup=kb_main(self.snapshot(), self.capabilities()))

        @self.bot.message_handler(commands=["debug_on"])
        def _debug_on(m: Message) -> None:
            if m.from_user.id not in self.cfg.admins:
                return
            self.cfg.debug_enabled = True
            self.sh.debug = True
            self.bot.send_message(m.chat.id, "🐞 Debug: <b>ON</b>")

        @self.bot.message_handler(commands=["debug_off"])
        def _debug_off(m: Message) -> None:
            if m.from_user.id not in self.cfg.admins:
                return
            self.cfg.debug_enabled = False
            self.sh.debug = False
            self.bot.send_message(m.chat.id, "🐞 Debug: <b>OFF</b>")

        @self.bot.message_handler(commands=["help"])
        def _help(m: Message) -> None:
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)
            help_text = (
                "Команды:\n"
                "/menu — открыть меню\n"
                "/start — то же\n\n"
                "Все действия доступны через кнопки."
            )
            self.bot.send_message(m.chat.id, escape_html(help_text))

        @self.bot.callback_query_handler(func=lambda c: True)
        def _cb(cq: CallbackQuery) -> None:
            try:
                if not self.is_chat_allowed(cq.message.chat.id, cq.from_user.id):
                    return self._deny(cq.message.chat.id)

                data = cq.data or ""
                log_line(f"callback {cq.from_user.id}: {data}")

                # ack
                try:
                    self.bot.answer_callback_query(cq.id)
                except Exception:
                    pass

                self.handle_callback(cq)
            except Exception as e:
                log_line(f"callback error: {e}")
                try:
                    self.bot.send_message(cq.message.chat.id, f"⚠️ Ошибка: <code>{escape_html(str(e))}</code>")
                except Exception:
                    pass

        @self.bot.message_handler(content_types=["text", "document"])
        def _any(m: Message) -> None:
            # если ждём ввод — обрабатываем
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)

            p = self.pending.peek(m.chat.id, m.from_user.id)
            if not p:
                return  # игнорируем произвольные сообщения
            self.pending.pop(m.chat.id, m.from_user.id)

            try:
                if p.kind == "hydra_add_domain_text" and m.content_type == "text":
                    target = p.data["target"]
                    domains = re.split(r"[,\s]+", m.text.strip())
                    ok, msg = self.hydra.add_domain(domains, target)
                    self.bot.send_message(m.chat.id, ("✅ " if ok else "⚠️ ") + escape_html(msg))
                elif p.kind == "hydra_rm_domain_text" and m.content_type == "text":
                    domain = m.text.strip()
                    ok, msg = self.hydra.remove_domain(domain)
                    self.bot.send_message(m.chat.id, ("✅ " if ok else "⚠️ ") + escape_html(msg))

                elif p.kind == "hydra_search_domain_text" and m.content_type == "text":
                    q = m.text.strip()
                    res = self.hydra.find_domain(q)
                    self.bot.send_message(m.chat.id, "<b>Поиск domain.conf</b>\n<pre><code>" + escape_html(res) + "</code></pre>")
                elif p.kind == "hydra_import_domain_conf" and m.content_type == "document":
                    dest = HR_DOMAIN_CONF
                    self._handle_document_upload(m, dest)
                    if self.hydra.is_neo_available():
                        self.hydra.neo_cmd("restart")
                    self.bot.send_message(m.chat.id, "✅ domain.conf импортирован (с бэкапом). Neo перезапущен.")
                elif p.kind == "nfqws_import_list" and m.content_type == "document":
                    list_name = p.data.get("list_name", "user.list")
                    dest = NFQWS_LISTS_DIR / list_name
                    self._handle_document_upload(m, dest)
                    self.nfqws.init_action("reload")
                    self.bot.send_message(m.chat.id, f"✅ Импортирован список: <code>{escape_html(list_name)}</code> (с бэкапом). Выполнен reload.")
                elif p.kind == "nfqws_add_list_text" and m.content_type == "text":
                    list_name = p.data["list_name"]
                    domains = re.split(r"[,\s]+", m.text.strip())
                    ok, msg = self.nfqws.add_to_list(list_name, domains)
                    self.bot.send_message(m.chat.id, ("✅ " if ok else "⚠️ ") + escape_html(msg))
                elif p.kind == "file_upload" and m.content_type == "document":
                    dest = Path(p.data["dest"])
                    kind = p.data.get("kind", "file")
                    self._handle_document_upload(m, dest)
                    self.bot.send_message(m.chat.id, f"✅ Загружено: <code>{escape_html(str(dest))}</code>\nПерезапустите сервис при необходимости.")
                else:
                    self.bot.send_message(m.chat.id, "⚠️ Неожиданный тип ввода. Попробуйте ещё раз.")
            except Exception as e:
                log_line(f"pending handler error: {e}")
                self.bot.send_message(m.chat.id, f"⚠️ Ошибка: <code>{escape_html(str(e))}</code>")

    def _handle_document_upload(self, m: Message, dest: Path) -> None:
        # download from telegram
        file_id = m.document.file_id
        file_info = self.bot.get_file(file_id)
        data = self.bot.download_file(file_info.file_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # backup
        self.sh.backup_file(dest)
        with open(dest, "wb") as f:
            f.write(data)

    # ---- Rendering ----
    def render_main(self) -> str:
        vers = self.opkg.target_versions()
        v_lines = []
        for p in TARGET_PKGS:
            if p in vers:
                v_lines.append(f"{p}={vers[p]}")
        versions = " | ".join(v_lines) if v_lines else "—"

        caps = self.capabilities()
        mods = []
        mods.append("Router ✅")
        mods.append("HydraRoute ✅" if caps.get("hydra") else "HydraRoute ➖")
        mods.append("NFQWS2 ✅" if caps.get("nfqws2") else "NFQWS2 ➖")
        mods.append("NFQWS web ✅" if caps.get("nfqws_web") else "NFQWS web ➖")
        mods.append("AWG ✅" if caps.get("awg") else "AWG ➖")
        mods.append("cron ✅" if caps.get("cron") else "cron ➖")

        text = "\n".join([
            "🧰 <b>Keenetic Router Bot</b>",
            f"📍 IP: <code>{self.router.lan_ip()}</code>",
            f"⏱ Uptime: <code>{self.router.uptime()}</code>",
            f"🧩 Модули: <code>{escape_html(' | '.join(mods))}</code>",
            f"📦 Target packages: <code>{escape_html(versions)}</code>",
            "",
            "Выберите раздел:",
        ])
        return text


    # ---- Callback dispatcher ----
    def handle_callback(self, cq: CallbackQuery) -> None:
        chat_id = cq.message.chat.id
        msg_id = cq.message.message_id
        data = cq.data or ""

        # Menus
        if data.startswith("m:"):
            m = data.split(":", 1)[1]
            if m == "main":
                self.send_or_edit(chat_id, self.render_main(), reply_markup=kb_main(self.snapshot(), self.capabilities()), message_id=msg_id)
                return
            if m == "router":
                self.send_or_edit(chat_id, "🧠 <b>Router</b>", reply_markup=kb_router(), message_id=msg_id)
                return
            if m == "hydra":
                variant = self.hydra.installed_variant()
                self.send_or_edit(chat_id, self.hydra.status_text(), reply_markup=kb_hydra(variant), message_id=msg_id)
                return
            if m == "nfqws":
                self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
                return
            if m == "awg":
                self.send_or_edit(chat_id, self.awg.status_text(), reply_markup=kb_awg(), message_id=msg_id)
                return
            if m == "opkg":
                self.send_or_edit(chat_id, "📦 <b>OPKG</b>", reply_markup=kb_opkg(), message_id=msg_id)
                return
            if m == "logs":
                self.send_or_edit(chat_id, "📝 <b>Логи</b>", reply_markup=kb_logs(), message_id=msg_id)
                return

            if m == "install":
                caps = self.capabilities()
                txt = (
                    "🧩 <b>Установка/Сервис</b>\n"
                    "Здесь отображаются только отсутствующие компоненты.\n\n"
                    "⚠️ Установка меняет систему (opkg/скрипты)."
                )
                self.send_or_edit(chat_id, txt, reply_markup=kb_install(caps), message_id=msg_id)
                return
            if m == "settings":
                txt = (
                    "⚙️ <b>Настройки</b>\n"
                    f"CONFIG: <code>{escape_html(os.getenv('BOT_CONFIG', DEFAULT_CONFIG_PATH))}</code>\n"
                    f"ADMINS: <code>{', '.join(map(str, self.cfg.admins))}</code>\n"
                    f"MONITOR: <code>{'on' if self.cfg.monitor_enabled else 'off'}</code>\n"
                )
                self.send_or_edit(chat_id, txt, reply_markup=kb_home_back(), message_id=msg_id)
                return

        # Router actions
        if data.startswith("router:"):
            self._handle_router_cb(chat_id, msg_id, data)
            return

        # Hydra
        if data.startswith("hydra:"):
            self._handle_hydra_cb(chat_id, msg_id, data, cq.from_user.id)
            return

        # nfqws
        if data.startswith("nfqws:"):
            self._handle_nfqws_cb(chat_id, msg_id, data, cq.from_user.id)
            return

        # awg
        if data.startswith("awg:"):
            self._handle_awg_cb(chat_id, msg_id, data, cq.from_user.id)
            return

        # opkg
        if data.startswith("opkg:"):
            self._handle_opkg_cb(chat_id, msg_id, data)
            return

        # logs
        if data.startswith("logs:"):
            self._handle_logs_cb(chat_id, msg_id, data)
            return

        # install
        if data.startswith("install:"):
            self._handle_install_cb(chat_id, msg_id, data)
            return

        self.send_or_edit(chat_id, "Неизвестная команда.", reply_markup=kb_main(self.snapshot(), self.capabilities()), message_id=msg_id)

    def _handle_router_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        if data == "router:status":
            self.send_or_edit(chat_id, self.router.basic_status_text(), reply_markup=kb_router(), message_id=msg_id)
            return

        if data == "router:net":
            self.send_or_edit(chat_id, "⏳ Проверяю интернет…", reply_markup=kb_router(), message_id=msg_id)
            ok, txt = self.router.internet_check()
            self.send_or_edit(
                chat_id,
                f"🌐 <b>Интернет тест</b>\n{'✅ OK' if ok else '⚠️ проблемы'}\n{fmt_code(txt)}",
                reply_markup=kb_router(),
                message_id=msg_id,
            )
            return

        if data == "router:netmenu":
            self.send_or_edit(chat_id, "🌐 <b>Сеть</b>", reply_markup=kb_router_net(), message_id=msg_id)
            return
        if data == "router:fwmenu":
            self.send_or_edit(chat_id, "🧱 <b>Firewall</b>", reply_markup=kb_router_fw(), message_id=msg_id)
            return
        if data == "router:dhcpmenu":
            self.send_or_edit(chat_id, "👥 <b>DHCP клиенты</b>", reply_markup=kb_router_dhcp(), message_id=msg_id)
            return

        if data == "router:ipaddr_br":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router_net(), message_id=msg_id)
            rc, out = self.sh.run(["ip", "-br", "addr"], timeout_sec=10)
            if rc != 0:
                rc, out = self.sh.run(["ip", "addr"], timeout_sec=10)
            self.send_or_edit(chat_id, f"📡 <b>ip addr</b>\n{fmt_code(out)}", reply_markup=kb_router_net(), message_id=msg_id)
            return

        if data == "router:iproute4":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router_net(), message_id=msg_id)
            rc, out = self.sh.run(["ip", "-4", "route"], timeout_sec=10)
            self.send_or_edit(chat_id, f"🧭 <b>ip route -4</b>\n{fmt_code(fmt_ip_route(out))}", reply_markup=kb_router_net(), message_id=msg_id)
            return

        if data == "router:iproute6":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router_net(), message_id=msg_id)
            rc, out = self.sh.run(["ip", "-6", "route"], timeout_sec=10)
            self.send_or_edit(chat_id, f"🧭 <b>ip route -6</b>\n{fmt_code(fmt_ip_route(out))}", reply_markup=kb_router_net(), message_id=msg_id)
            return

        if data.startswith("router:iptables:"):
            if not which("iptables"):
                self.send_or_edit(chat_id, "iptables не найден.", reply_markup=kb_router_fw(), message_id=msg_id)
                return
            _, view, table = data.split(":")
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router_fw(), message_id=msg_id)
            rc, out = self.sh.run(["iptables", "-t", table, "-S"], timeout_sec=15)
            if view == "sum":
                out2 = summarize_iptables(out)
                self.send_or_edit(chat_id, f"🧱 <b>iptables -t {escape_html(table)} summary</b>\n{fmt_code(out2)}", reply_markup=kb_router_fw(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"🧱 <b>iptables -t {escape_html(table)} -S</b>\n{fmt_code(out)}", reply_markup=kb_router_fw(), message_id=msg_id)
            return

        if data.startswith("router:dhcp:list:"):
            kind = data.split(":")[-1]
            self.send_or_edit(chat_id, "⏳ Загружаю DHCP…", reply_markup=kb_router_dhcp(), message_id=msg_id)
            clients = self.router.dhcp_clients_enriched(limit=400)
            # cache
            self.dhcp_cache = getattr(self, "dhcp_cache", {})
            self.dhcp_cache[chat_id] = {"ts": time.time(), "clients": clients}

            lan, wifi = split_clients_lan_wifi(clients)
            view = clients
            title = "All"
            if kind == "lan":
                view, title = lan, "LAN"
            elif kind == "wifi":
                view, title = wifi, "Wi‑Fi"

            if not view:
                self.send_or_edit(chat_id, f"👥 <b>DHCP {escape_html(title)}</b>\nНет данных (или не удалось определить).", reply_markup=kb_router_dhcp(), message_id=msg_id)
                return

            kb = InlineKeyboardMarkup()
            for i, c in enumerate(view[:15]):
                label = f"{c.get('ip','?')}  {c.get('name') or c.get('mac','')}"
                kb.row(InlineKeyboardButton(label[:60], callback_data=f"router:dhcp:detail:{kind}:{i}"))
            kb.row(InlineKeyboardButton("⬅️ Back", callback_data="router:dhcpmenu"), InlineKeyboardButton("🏠 Home", callback_data="m:main"))

            lines = []
            for c in view[:40]:
                iface = c.get("iface","")
                suffix = f" ({iface})" if iface else ""
                lines.append(f"{c.get('ip','?'):15} {c.get('mac',''):17} {c.get('name','')}{suffix}")
            lst = "\n".join(lines)
            self.send_or_edit(chat_id, f"👥 <b>DHCP {escape_html(title)}</b>\n{fmt_code(lst)}", reply_markup=kb, message_id=msg_id)
            return

        if data.startswith("router:dhcp:detail:"):
            parts = data.split(":")
            kind = parts[3]
            idx = int(parts[4])
            cache = getattr(self, "dhcp_cache", {}).get(chat_id)
            if not cache or (time.time() - cache.get("ts", 0) > 600):
                self.send_or_edit(chat_id, "⚠️ Кэш устарел. Открой DHCP заново.", reply_markup=kb_router_dhcp(), message_id=msg_id)
                return
            clients = cache.get("clients", [])
            lan, wifi = split_clients_lan_wifi(clients)
            view = clients
            if kind == "lan":
                view = lan
            elif kind == "wifi":
                view = wifi
            if idx < 0 or idx >= len(view):
                self.send_or_edit(chat_id, "⚠️ Не найдено. Открой DHCP заново.", reply_markup=kb_router_dhcp(), message_id=msg_id)
                return
            c = view[idx]
            detail = (
                f"👤 <b>DHCP client</b>\n"
                f"• IP: <code>{escape_html(c.get('ip','?'))}</code>\n"
                f"• MAC: <code>{escape_html(c.get('mac','?'))}</code>\n"
                f"• Name: <code>{escape_html(c.get('name',''))}</code>\n"
                f"• Iface: <code>{escape_html(c.get('iface',''))}</code>\n"
                f"• Raw: <code>{escape_html(c.get('rest',''))}</code>"
            )
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton("⬅️ Back", callback_data=f"router:dhcp:list:{kind}"), InlineKeyboardButton("🏠 Home", callback_data="m:main"))
            self.send_or_edit(chat_id, detail, reply_markup=kb, message_id=msg_id)
            return

        if data == "router:exportcfg":
            ok, msg, p = self.router.export_running_config()
            if ok and p:
                try:
                    self.bot.send_document(chat_id, InputFile(str(p)), caption=msg)
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ Не удалось отправить файл: <code>{escape_html(str(e))}</code>")
            else:
                self.bot.send_message(chat_id, f"⚠️ {escape_html(msg)}")
            return

        if data.startswith("router:reboot?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🔄 <b>Reboot</b>\nТочно перезагрузить роутер?",
                reply_markup=kb_confirm("router:reboot!do", "m:router"),
                message_id=msg_id,
            )
            return
        if data == "router:reboot!do":
            self.send_or_edit(chat_id, "Перезагружаю… (соединение может пропасть)", reply_markup=kb_home_back(), message_id=msg_id)
            self.router.reboot()
            return

    def _handle_hydra_cb(self, chat_id: int, msg_id: int, data: str, user_id: int) -> None:
        variant = self.hydra.installed_variant()

        # confirmations
        if data.startswith("hydra:update?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Обновление HydraRoute</b>\nВыполнить: <code>opkg update && opkg upgrade hrneo hrweb hydraroute</code> ?",
                reply_markup=kb_confirm("hydra:update!do", "m:hydra"),
                message_id=msg_id,
            )
            return
        if data == "hydra:update!do":
            self.send_or_edit(chat_id, "📦 Выполняю обновление…", reply_markup=kb_home_back(back="m:hydra"), message_id=msg_id)
            rc1, out1 = self.opkg.update()
            rc2, out2 = self.opkg.upgrade([p for p in ["hrneo", "hrweb", "hydraroute"] if p])
            txt = f"<b>opkg update</b> rc={rc1}\n<code>{escape_html(out1[:1500])}</code>\n\n<b>opkg upgrade</b> rc={rc2}\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(variant), message_id=msg_id)
            return

        if data.startswith("hydra:remove?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🗑 <b>Удаление HydraRoute</b>\nУдалить пакеты (opkg remove) и остановить сервис?",
                reply_markup=kb_confirm("hydra:remove!do", "m:hydra"),
                message_id=msg_id,
            )
            return
        if data == "hydra:remove!do":
            # остановим и удалим
            if variant == "neo":
                self.hydra.neo_cmd("stop")
                rc, out = self.opkg.remove("hrneo")
                rc2, out2 = self.opkg.remove("hrweb")
            elif variant == "classic":
                self.hydra.classic_cmd("stop")
                rc, out = self.opkg.remove("hydraroute")
                rc2, out2 = 0, ""
            else:
                rc, out, rc2, out2 = 1, "не установлен", 0, ""
            txt = f"opkg remove rc={rc}\n<code>{escape_html(out[:1500])}</code>\n\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(self.hydra.installed_variant()), message_id=msg_id)
            return

        if data == "hydra:status":
            self.send_or_edit(chat_id, self.hydra.status_text(), reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:diag":
            self.send_or_edit(chat_id, "⏳ Диагностика…", reply_markup=kb_hydra(variant), message_id=msg_id)
            ipset_txt = self.hydra.diag_ipset()
            ipt_txt = self.hydra.diag_iptables()
            txt = "🛠 <b>HydraRoute diag</b>\n\n<b>ipset</b>\n" + fmt_code(ipset_txt) + "\n\n<b>iptables</b>\n" + fmt_code(ipt_txt)
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:start":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_hydra(variant), message_id=msg_id)
            if variant == "neo":
                rc, out = self.hydra.neo_cmd("start")
            elif variant == "classic":
                rc, out = self.hydra.classic_cmd("start")
            else:
                rc, out = 127, "не установлен"
            status = "✅ OK" if rc == 0 else "⚠️ FAIL"
            txt = f"▶️ <b>start</b> — {status} (rc={rc})\n"
            if self.sh.debug and out:
                txt += fmt_code(out)
                txt += "\n"
            txt += self.hydra.status_text()
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(self.hydra.installed_variant()), message_id=msg_id)
            return
        if data == "hydra:stop":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_hydra(variant), message_id=msg_id)
            if variant == "neo":
                rc, out = self.hydra.neo_cmd("stop")
            elif variant == "classic":
                rc, out = self.hydra.classic_cmd("stop")
            else:
                rc, out = 127, "не установлен"
            status = "✅ OK" if rc == 0 else "⚠️ FAIL"
            txt = f"⏹ <b>stop</b> — {status} (rc={rc})\n"
            if self.sh.debug and out:
                txt += fmt_code(out)
                txt += "\n"
            txt += self.hydra.status_text()
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(self.hydra.installed_variant()), message_id=msg_id)
            return
        if data == "hydra:restart":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_hydra(variant), message_id=msg_id)
            if variant == "neo":
                rc, out = self.hydra.neo_cmd("restart")
            elif variant == "classic":
                rc, out = self.hydra.classic_cmd("restart")
            else:
                rc, out = 127, "не установлен"
            status = "✅ OK" if rc == 0 else "⚠️ FAIL"
            txt = f"🔄 <b>restart</b> — {status} (rc={rc})\n"
            if self.sh.debug and out:
                txt += fmt_code(out)
                txt += "\n"
            txt += self.hydra.status_text()
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(self.hydra.installed_variant()), message_id=msg_id)
            return
        if data == "hydra:hrweb":
            url = f"http://{self.router.lan_ip()}:2000"
            self.send_or_edit(chat_id, f"🌐 HRweb: <code>{url}</code>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data.startswith("hydra:file:"):
            kind = data.split(":", 2)[2]
            ok, msg, p = self.hydra.file_get(kind)
            if ok and p:
                # отправим как документ
                try:
                    self.bot.send_document(chat_id, InputFile(str(p)), caption=f"{kind}")
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ Не удалось отправить: <code>{escape_html(str(e))}</code>")
                self.send_or_edit(chat_id, self.hydra.status_text(), reply_markup=kb_hydra(variant), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"⚠️ {escape_html(msg)}", reply_markup=kb_hydra(variant), message_id=msg_id)
            return

        if data == "hydra:rules":
            res = self.hydra.domain_summary()
            self.send_or_edit(chat_id, f"📚 <b>HydraRoute правила</b>\n<pre><code>{escape_html(res)}</code></pre>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:dupes":
            res = self.hydra.duplicates()
            self.send_or_edit(chat_id, f"🧩 <b>Дубликаты доменов</b>\n<pre><code>{escape_html(res)}</code></pre>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:search_domain":
            self.pending.set(chat_id, user_id, "hydra_search_domain_text", {}, ttl_sec=300)
            self.bot.send_message(chat_id, "Введите домен/подстроку для поиска в <code>domain.conf</code> (например: <code>telegram</code>).")
            return
        if data == "hydra:import:domain.conf":
            self.pending.set(chat_id, user_id, "hydra_import_domain_conf", {}, ttl_sec=300)
            self.bot.send_message(chat_id, "Отправьте файлом новый <code>domain.conf</code>. Я заменю текущий (с бэкапом) и перезапущу Neo.")
            return

        if data == "hydra:add_domain":
            # просим текст
            self.pending.set(chat_id, user_id, "hydra_add_domain_text", {"target": "HydraRoute"}, ttl_sec=300)
            self.bot.send_message(chat_id, "Введите домены через пробел/запятую (или geosite:TAG). Будет добавлено в <code>domain.conf</code> для цели <code>HydraRoute</code>.")
            return
        if data == "hydra:rm_domain":
            self.pending.set(chat_id, user_id, "hydra_rm_domain_text", {}, ttl_sec=300)
            self.bot.send_message(chat_id, "Введите домен для удаления из <code>domain.conf</code> (например: <code>youtube.com</code>).")
            return

    def _handle_nfqws_cb(self, chat_id: int, msg_id: int, data: str, user_id: int) -> None:
        # confirmations
        if data.startswith("nfqws:update?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Обновление NFQWS2</b>\nВыполнить: <code>opkg update && opkg upgrade nfqws2-keenetic nfqws-keenetic-web</code> ?",
                reply_markup=kb_confirm("nfqws:update!do", "m:nfqws"),
                message_id=msg_id,
            )
            return
        if data == "nfqws:update!do":
            self.send_or_edit(chat_id, "📦 Выполняю обновление…", reply_markup=kb_home_back(back="m:nfqws"), message_id=msg_id)
            rc1, out1 = self.opkg.update()
            rc2, out2 = self.opkg.upgrade(["nfqws2-keenetic", "nfqws-keenetic-web"])
            txt = f"<b>opkg update</b> rc={rc1}\n<code>{escape_html(out1[:1500])}</code>\n\n<b>opkg upgrade</b> rc={rc2}\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_nfqws(), message_id=msg_id)
            return

        if data.startswith("nfqws:clear:auto.list?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🧹 <b>Очистка auto.list</b>\nТочно очистить <code>auto.list</code>?",
                reply_markup=kb_confirm("nfqws:clear:auto.list!do", "m:nfqws"),
                message_id=msg_id,
            )
            return
        if data == "nfqws:clear:auto.list!do":
            ok, msg = self.nfqws.clear_list("auto.list")
            self.send_or_edit(chat_id, ("✅ " if ok else "⚠️ ") + escape_html(msg), reply_markup=kb_nfqws(), message_id=msg_id)
            return


        if data.startswith("nfqws:filelist:"):
            name = data.split(":", 2)[2]
            target = NFQWS_LISTS_DIR / name
            if target.exists():
                try:
                    self.bot.send_document(chat_id, InputFile(str(target)), caption=name)
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ {escape_html(str(e))}")
            else:
                self.bot.send_message(chat_id, f"Файл не найден: <code>{escape_html(str(target))}</code>")
            self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
            return

        if data == "nfqws:import:list?confirm=1":
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Импорт списка</b>\n"
                "Я попрошу прислать файл и заменю <code>user.list</code> (с бэкапом), затем сделаю <code>reload</code>.",
                reply_markup=kb_confirm("nfqws:import:list!do", "m:nfqws"),
                message_id=msg_id,
            )
            return
        if data == "nfqws:import:list!do":
            self.pending.set(chat_id, user_id, "nfqws_import_list", {"list_name": "user.list"}, ttl_sec=300)
            self.bot.send_message(chat_id, "Пришлите файлом новый <code>user.list</code> (я заменю текущий, сделаю бэкап и reload).")
            return

        if data == "nfqws:status":
            self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:diag":
            self.send_or_edit(chat_id, "⏳ Диагностика…", reply_markup=kb_nfqws(), message_id=msg_id)
            diag = self.nfqws.diag_iptables_queue()
            txt = "🛠 <b>NFQWS2 diag</b>\n\n" + fmt_code(diag)
            self.send_or_edit(chat_id, txt, reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data in ("nfqws:start", "nfqws:stop", "nfqws:restart", "nfqws:reload"):
            action = data.split(":", 1)[1]
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_nfqws(), message_id=msg_id)
            rc, out = self.nfqws.init_action(action)
            status = "✅ OK" if rc == 0 else "⚠️ FAIL"
            txt = f"🧷 <b>{escape_html(action)}</b> — {status} (rc={rc})\n"
            if self.sh.debug and out:
                txt += fmt_code(out)
                txt += "\n"
            txt += self.nfqws.status_text()
            self.send_or_edit(chat_id, txt, reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:web":
            caps = self.capabilities()
            if not caps.get("nfqws_web"):
                self.send_or_edit(chat_id, "🌐 WebUI: ➖ (nfqws-keenetic-web не установлен)", reply_markup=kb_nfqws(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"🌐 WebUI: <code>{self.nfqws.web_url()}</code>", reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:file:nfqws2.conf":
            if NFQWS_CONF.exists():
                try:
                    self.bot.send_document(chat_id, InputFile(str(NFQWS_CONF)), caption="nfqws2.conf")
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ {escape_html(str(e))}")
            else:
                self.bot.send_message(chat_id, "nfqws2.conf не найден.")
            self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:lists":
            self.send_or_edit(chat_id, f"📚 <b>Lists</b>\n<code>{escape_html(self.nfqws.lists_stats())}</code>", reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data.startswith("nfqws:add:"):
            list_name = data.split(":", 2)[2]
            self.pending.set(chat_id, user_id, "nfqws_add_list_text", {"list_name": list_name}, ttl_sec=300)
            self.bot.send_message(chat_id, f"Введите домены для добавления в <code>{escape_html(list_name)}</code> (через пробел/запятую).")
            return
        if data == "nfqws:log":
            ok, txt = self.sh.read_file(NFQWS_LOG, max_bytes=30_000)
            if not ok:
                self.send_or_edit(chat_id, f"⚠️ {escape_html(txt)}", reply_markup=kb_nfqws(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"📜 <b>nfqws2.log</b>\n<code>{escape_html(txt[-3500:])}</code>", reply_markup=kb_nfqws(), message_id=msg_id)
            return

    def _handle_awg_cb(self, chat_id: int, msg_id: int, data: str, user_id: int) -> None:
        if data.startswith("awg:update?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Обновление AWG Manager</b>\nВыполнить: <code>opkg update && opkg upgrade awg-manager</code> ?",
                reply_markup=kb_confirm("awg:update!do", "m:awg"),
                message_id=msg_id,
            )
            return
        if data == "awg:update!do":
            self.send_or_edit(chat_id, "📦 Выполняю обновление…", reply_markup=kb_home_back(back="m:awg"), message_id=msg_id)
            rc1, out1 = self.opkg.update()
            rc2, out2 = self.opkg.upgrade(["awg-manager"])
            txt = f"<b>opkg update</b> rc={rc1}\n<code>{escape_html(out1[:1500])}</code>\n\n<b>opkg upgrade</b> rc={rc2}\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_awg(), message_id=msg_id)
            return

        if data.startswith("awg:remove?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🗑 <b>Удаление AWG Manager</b>\nУдалить пакет <code>awg-manager</code> (opkg remove)?",
                reply_markup=kb_confirm("awg:remove!do", "m:awg"),
                message_id=msg_id,
            )
            return
        if data == "awg:remove!do":
            self.awg.init_action("stop")
            rc, out = self.opkg.remove("awg-manager")
            self.send_or_edit(chat_id, f"opkg remove rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return

        # --- AWG API (локальный, т.к. authDisabled=true) ---
        if data == "awg:api:statusall":
            ok, msg, obj = self.awg.api_get("/status/all")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"📊 <b>AWG status/all</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:updatecheck":
            ok, msg, obj = self.awg.api_get("/system/update/check")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"⬆️ <b>AWG update/check</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:logs":
            ok, msg, obj = self.awg.api_get("/logs")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"🧾 <b>AWG logs</b>\n<pre><code>{escape_html(pretty[-3500:])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:tunnels":
            ok, msg, obj = self.awg.api_get("/tunnels/list")
            if not ok or obj is None:
                self.send_or_edit(chat_id, f"⚠️ tunnels/list: {escape_html(msg)}", reply_markup=kb_awg(), message_id=msg_id)
                return
            tunnels = obj if isinstance(obj, list) else (obj.get("items") if isinstance(obj, dict) else None)
            if not isinstance(tunnels, list):
                pretty = json.dumps(obj, ensure_ascii=False, indent=2) if isinstance(obj, (dict, list)) else str(obj)
                self.send_or_edit(chat_id, f"⚠️ Неожиданный формат tunnels/list\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
                return
            self._awg_cache_set(chat_id, user_id, tunnels, ttl_sec=300)

            lines = []
            kb = InlineKeyboardMarkup()
            max_btn = 10
            for i, t in enumerate(tunnels[:max_btn]):
                tid = t.get("id") or t.get("tunnelId") or t.get("interface") or str(i)
                name = t.get("name") or t.get("title") or t.get("interfaceName") or tid
                lines.append(f"{i}. {name} ({tid})")
                kb.row(InlineKeyboardButton(f"{i}. {name}"[:50], callback_data=f"awg:tunnel:{i}"))
            kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))

            txt = "🧭 <b>AWG туннели</b>\n" + "<pre><code>" + escape_html("\n".join(lines)[:3500]) + "</code></pre>"
            self.send_or_edit(chat_id, txt, reply_markup=kb, message_id=msg_id)
            return

        if data.startswith("awg:tunnel:"):
            try:
                idx = int(data.split(":")[2])
            except Exception:
                self.send_or_edit(chat_id, "⚠️ Некорректный индекс туннеля.", reply_markup=kb_awg(), message_id=msg_id)
                return
            tunnels = self._awg_cache_get(chat_id, user_id)
            if not tunnels or idx < 0 or idx >= len(tunnels):
                self.send_or_edit(chat_id, "⚠️ Кэш туннелей устарел. Открой 'Туннели' заново.", reply_markup=kb_awg(), message_id=msg_id)
                return

            t = tunnels[idx]
            tid = t.get("id") or t.get("tunnelId") or t.get("interface") or str(idx)

            # подтянем актуальный статус
            ok_s, msg_s, st = self.awg.api_get("/status/all")
            if ok_s and isinstance(st, list):
                for item in st:
                    if (item.get("id") or item.get("tunnelId")) == tid:
                        # аккуратно "поверх" добавляем статусные поля
                        for k, v in item.items():
                            t[f"status_{k}"] = v
                        break

            pretty = json.dumps(t, ensure_ascii=False, indent=2)
            self.send_or_edit(
                chat_id,
                f"📋 <b>Туннель #{idx}</b> (<code>{escape_html(str(tid))}</code>)\n<pre><code>{escape_html(pretty[:3500])}</code></pre>",
                reply_markup=kb_awg_tunnel(idx),
                message_id=msg_id,
            )
            return


        if data.startswith("awg:tunnelact:"):
            parts = data.split(":")
            if len(parts) < 4:
                self.send_or_edit(chat_id, "⚠️ Некорректная команда.", reply_markup=kb_awg(), message_id=msg_id)
                return
            idx = int(parts[2])
            action = parts[3]
            tunnels = self._awg_cache_get(chat_id, user_id)
            if not tunnels or idx < 0 or idx >= len(tunnels):
                self.send_or_edit(chat_id, "⚠️ Кэш туннелей устарел. Открой 'Туннели' заново.", reply_markup=kb_awg(), message_id=msg_id)
                return
            t = tunnels[idx]
            tid = t.get("id") or t.get("tunnelId") or t.get("interface")
            enc = urllib.parse.quote(str(tid))

            if action == "start":
                endpoint = f"/control/start?id={enc}"
            elif action == "stop":
                endpoint = f"/control/stop?id={enc}"
            elif action == "restart":
                endpoint = f"/control/restart?id={enc}"
            elif action == "toggle":
                endpoint = f"/control/toggle-enabled?id={enc}"
            elif action == "default":
                endpoint = f"/control/toggle-default-route?id={enc}"
            else:
                self.send_or_edit(chat_id, "⚠️ Неизвестное действие.", reply_markup=kb_awg_tunnel(idx), message_id=msg_id)
                return

            ok, msg, obj = self.awg.api_post(endpoint, body=None)
            payload = obj if obj is not None else {"message": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"✅ <b>{action}</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg_tunnel(idx), message_id=msg_id)
            return



        if data == "awg:api:systeminfo":
            ok1, msg1, info = self.awg.api_get("/system/info")
            ok2, msg2, wan = self.awg.api_get("/wan/status")
            payload = {"system/info": info if ok1 else {"error": msg1}, "wan/status": wan if ok2 else {"error": msg2}}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
            self.send_or_edit(chat_id, f"ℹ️ <b>AWG system/wan</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:diagr":
            ok, msg, obj = self.awg.api_post("/diagnostics/run", body=None)
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"🧪 <b>AWG diagnostics/run</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:diags":
            ok, msg, obj = self.awg.api_get("/diagnostics/status")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"🧪 <b>AWG diagnostics/status</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:updateapply?confirm=1":
            self.send_or_edit(
                chat_id,
                "⬆️ <b>AWG update/apply</b>\nТочно применить обновление (это может перезапустить сервис/модули)?",
                reply_markup=kb_confirm("awg:api:updateapply!do", "m:awg"),
                message_id=msg_id,
            )
            return
        if data == "awg:api:updateapply!do":
            ok, msg, obj = self.awg.api_post("/system/update/apply", body=None)
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"⬆️ <b>AWG update/apply</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:status":
            self.send_or_edit(chat_id, self.awg.status_text(), reply_markup=kb_awg(), message_id=msg_id)
            return
        if data in ("awg:start", "awg:stop", "awg:restart"):
            action = data.split(":", 1)[1]
            rc, out = self.awg.init_action(action)
            self.send_or_edit(chat_id, f"{action} rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:web":
            self.send_or_edit(chat_id, f"🌐 WebUI: <code>{self.awg.web_url()}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:health":
            ok, out = self.awg.health_check()
            self.send_or_edit(chat_id, f"💓 Health: {'✅' if ok else '⚠️'}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:wg":
            txt = self.awg.wg_status()
            self.send_or_edit(chat_id, f"🧵 <b>wg show</b>\n<code>{escape_html(txt[:3500])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:file:settings.json":
            if AWG_SETTINGS.exists():
                try:
                    self.bot.send_document(chat_id, InputFile(str(AWG_SETTINGS)), caption="settings.json")
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ {escape_html(str(e))}")
            else:
                self.bot.send_message(chat_id, "settings.json не найден.")
            self.send_or_edit(chat_id, self.awg.status_text(), reply_markup=kb_awg(), message_id=msg_id)
            return

    def _handle_opkg_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        if data == "opkg:update":
            self.send_or_edit(chat_id, "🔄 Выполняю <code>opkg update</code>…", reply_markup=kb_opkg(), message_id=msg_id)
            rc, out = self.opkg.update()
            self.send_or_edit(chat_id, f"opkg update rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data == "opkg:upg":
            rc, out = self.opkg.list_upgradable()
            if rc != 0:
                self.send_or_edit(chat_id, f"⚠️ rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"⬆️ <b>list-upgradable</b>\n<code>{escape_html(out[:3500] or 'нет обновлений')}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data == "opkg:versions":
            vers = self.opkg.target_versions()
            if not vers:
                self.send_or_edit(chat_id, "Не удалось получить версии (opkg).", reply_markup=kb_opkg(), message_id=msg_id)
            else:
                lines = [f"{k}={v}" for k, v in vers.items()]
                self.send_or_edit(chat_id, "📦 <b>Версии</b>\n<code>" + escape_html("\n".join(lines)) + "</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data.startswith("opkg:upgrade?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Upgrade TARGET</b>\nОбновить только целевые пакеты?\n<code>{}</code>".format(" ".join(TARGET_PKGS)),
                reply_markup=kb_confirm("opkg:upgrade!do", "m:opkg"),
                message_id=msg_id,
            )
            return
        if data == "opkg:upgrade!do":
            self.send_or_edit(chat_id, "⬆️ Выполняю upgrade…", reply_markup=kb_opkg(), message_id=msg_id)
            rc, out = self.opkg.upgrade(TARGET_PKGS)
            self.send_or_edit(chat_id, f"opkg upgrade rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data == "opkg:installed":
            rc, out = self.opkg.list_installed()
            if rc != 0:
                self.send_or_edit(chat_id, f"⚠️ rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
                return
            # фильтруем target
            lines = []
            for ln in out.splitlines():
                pkg = ln.split(" ", 1)[0]
                if pkg in TARGET_PKGS:
                    lines.append(ln)
            self.send_or_edit(chat_id, "📃 <b>Installed (target)</b>\n<code>" + escape_html("\n".join(lines) or "—") + "</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return

    def _handle_logs_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        kind = data.split(":", 1)[1]
        if kind == "bot":
            p = Path(LOG_PATH)
        elif kind == "nfqws":
            p = NFQWS_LOG
        elif kind == "hrneo":
            p = HR_NEO_LOG_DEFAULT
        elif kind == "dmesg":
            rc, out = self.sh.run(["dmesg", "-T"], timeout_sec=10)
            self.send_or_edit(chat_id, f"📜 <b>dmesg</b>\n<code>{escape_html(out[-3500:])}</code>", reply_markup=kb_logs(), message_id=msg_id)
            return
        else:
            self.send_or_edit(chat_id, "Неизвестный лог.", reply_markup=kb_logs(), message_id=msg_id)
            return

        ok, txt = self.sh.read_file(p, max_bytes=40_000)
        if not ok:
            self.send_or_edit(chat_id, f"⚠️ {escape_html(txt)}", reply_markup=kb_logs(), message_id=msg_id)
            return
        self.send_or_edit(chat_id, f"📜 <b>{escape_html(p.name)}</b>\n<code>{escape_html(txt[-3500:])}</code>", reply_markup=kb_logs(), message_id=msg_id)

    def run(self) -> None:
        log_line("bot starting")
        if self.monitor:
            try:
                self.monitor.start()
            except Exception as e:
                log_line(f"monitor start error: {e}")

        # уведомим админов
        try:
            for uid in self.cfg.admins:
                self.bot.send_message(uid, "✅ Keenetic Router Bot запущен.", disable_web_page_preview=True)
        except Exception:
            pass

        self.bot.infinity_polling(timeout=30, long_polling_timeout=30, interval=self.cfg.poll_interval_sec)


def main() -> None:
    cfg_path = os.getenv("BOT_CONFIG", DEFAULT_CONFIG_PATH)
    if not os.path.exists(cfg_path):
        raise SystemExit(
            f"Config not found: {cfg_path}\n"
            f"Create it from config.example.json and set BOT_CONFIG or put it at {DEFAULT_CONFIG_PATH}"
        )
    cfg = load_config(cfg_path)
    app = App(cfg)
    app.run()


if __name__ == "__main__":
    main()
