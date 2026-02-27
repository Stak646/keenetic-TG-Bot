# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ..constants import *
from ..utils import *
from ..shell import Shell

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

    
    def get_dhcp_clients(self) -> List[Dict[str, str]]:
        """
        Returns parsed DHCP bindings as list of dicts:
        {ip, mac, name, iface, raw}
        Best-effort parser for `ndmc -c show ip dhcp binding`.
        """
        if not which("ndmc"):
            return []
        rc, out = self.sh.run(["ndmc", "-c", "show", "ip", "dhcp", "binding"], timeout_sec=10)
        if rc != 0 or not out:
            return []
        lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
        if not lines:
            return []
        # try table with header
        header = lines[0].lower()
        data_lines = lines[1:] if ("ip" in header and "mac" in header) else lines
        items: List[Dict[str, str]] = []
        for ln in data_lines:
            # split by 2+ spaces first
            cols = re.split(r"\s{2,}", ln.strip())
            ip = mac = name = iface = ""
            if len(cols) >= 2 and re.match(r"^\d+\.\d+\.\d+\.\d+$", cols[0]):
                ip = cols[0]
                mac = cols[1] if len(cols) > 1 else ""
                # heuristic: remaining could be name/iface
                rest = cols[2:] if len(cols) > 2 else []
                if rest:
                    # try to detect iface token
                    if len(rest) >= 2 and any(x in rest[-1].lower() for x in ["wifi", "wlan", "wireless", "wl", "ssid"]):
                        iface = rest[-1]
                        name = " ".join(rest[:-1]).strip()
                    else:
                        name = " ".join(rest).strip()
            else:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+).*?([0-9a-fA-F:]{17})", ln)
                if m:
                    ip = m.group(1)
                    mac = m.group(2).lower()
                    tail = ln[m.end():].strip()
                    name = tail
            if ip and mac:
                items.append({"ip": ip, "mac": mac, "name": name, "iface": iface, "raw": ln})
        return items

    def split_clients_lan_wifi(self, items: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        lan: List[Dict[str, str]] = []
        wifi: List[Dict[str, str]] = []
        for it in items:
            s = (it.get("iface","") + " " + it.get("raw","") + " " + it.get("name","")).lower()
            if any(k in s for k in ["wifi", "wlan", "wireless", "ssid", "wl"]):
                wifi.append(it)
            else:
                lan.append(it)
        return lan, wifi

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
