# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .constants import *
from .utils import *
from .shell import Shell

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
        No shell pipes to avoid BusyBox quirks.
        """
        rc, out = self.sh.run(["mount"], timeout_sec=8)
        src = ""
        if rc == 0 and out:
            for ln in out.splitlines():
                if " on /opt " in ln:
                    src = ln.split(" on /opt ")[0].strip()
                    break
        if not src:
            rc, out2 = self.sh.run(["df", "-h", "/opt"], timeout_sec=8)
            if rc == 0 and out2:
                parts = out2.splitlines()[-1].split()
                if parts:
                    src = parts[0]
        s = (src or "").lower()
        is_usb = any(k in s for k in ["/dev/sd", "usb", "uuid=", "/dev/usb"])
        return is_usb, (src or "unknown")


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
            if out:
                parts.append(f"<code>{escape_html(out[:900])}</code>")
            if ("hrweb" in self.opkg.target_versions()) or Path("/opt/share/hrweb").exists() or Path("/opt/etc/init.d/S50hrweb").exists():
                parts.append(f"• HRweb: <code>http://{self.router.lan_ip()}:2000</code>")
            else:
                parts.append("• HRweb: ➖ (не установлен)")
        elif self.is_classic_available():
            rc, out = self.classic_cmd("status")
            parts.append(f"• Classic: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
            if out:
                parts.append(f"<code>{escape_html(out[:900])}</code>")
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

    def status_text(self) -> str:
        parts = ["🧷 <b>NFQWS2</b>"]
        if not self.installed():
            parts.append("Не установлено.")
            return "\n".join(parts)
        rc, out = self.init_action("status")
        parts.append(f"• Service: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
        if out:
            parts.append(f"<code>{escape_html(out[:900])}</code>")

        # конфиг summary
        if NFQWS_CONF.exists():
            ok, txt = self.sh.read_file(NFQWS_CONF, max_bytes=60_000)
            if ok:
                # вытащим пару ключей
                kv = parse_env_like(txt)
                iface = kv.get("ISP_INTERFACE") or kv.get("ISP_IFACE") or kv.get("IFACE") or "?"
                ipv6 = kv.get("IPV6_ENABLED") or kv.get("IPV6") or "?"
                mode = kv.get("MODE") or kv.get("NFQWS_MODE") or "?"
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
        if out:
            parts.append(f"<code>{escape_html(out[:900])}</code>")
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

