
from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .base import DriverBase
from ..utils.shell import ShellResult


@dataclass(frozen=True)
class DhcpClient:
    mac: str
    ip: str
    hostname: str
    expires_at: Optional[str] = None  # ISO string
    source: str = ""  # leases file path


class RouterDriver(DriverBase):
    def get_system_info(self) -> str:
        lines: List[str] = []
        # Basic info
        uname = self.sh.run("uname -a", timeout_sec=5, cache_ttl_sec=10).out
        if uname:
            lines.append(f"uname: {uname}")

        # Uptime / load
        up = self.sh.run("uptime 2>/dev/null", timeout_sec=5, cache_ttl_sec=5).out
        if up:
            lines.append(up)

        # CPU / mem
        mem_total_kb = 0
        mem_free_kb = 0
        try:
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
                for ln in f:
                    if ln.startswith("MemTotal:"):
                        mem_total_kb = int(ln.split()[1])
                    elif ln.startswith("MemAvailable:"):
                        mem_free_kb = int(ln.split()[1])
        except Exception:
            pass
        if mem_total_kb:
            lines.append(f"RAM: {int(mem_free_kb/1024)} MB free / {int(mem_total_kb/1024)} MB total")

        # /opt space
        df = self.sh.run("df -h /opt 2>/dev/null | tail -n +2", timeout_sec=5, cache_ttl_sec=10).out
        if df:
            lines.append(f"/opt: {df}")

        # Keenetic info (best-effort)
        if self.sh.exists("ndmc"):
            ver = self.sh.run("ndmc -c 'show version' 2>/dev/null | head -n 5", timeout_sec=5, cache_ttl_sec=30).out
            if ver:
                lines.append("Keenetic:")
                lines.extend([f"  {x}" for x in ver.splitlines()])

        # Entware arch
        arch = self.sh.run("opkg print-architecture 2>/dev/null | head -n 5", timeout_sec=5, cache_ttl_sec=30).out
        if arch:
            lines.append("opkg architectures:")
            lines.extend([f"  {x}" for x in arch.splitlines()])

        return "\n".join(lines).strip() or "N/A"

    def ip_route(self) -> Tuple[List[str], List[str]]:
        v4 = self.sh.run("ip -4 route 2>/dev/null || true", timeout_sec=5, cache_ttl_sec=3).out
        v6 = self.sh.run("ip -6 route 2>/dev/null || true", timeout_sec=5, cache_ttl_sec=3).out
        return (v4.splitlines() if v4 else []), (v6.splitlines() if v6 else [])

    def ip_addr(self) -> List[str]:
        out = self.sh.run("ip addr show 2>/dev/null || ifconfig 2>/dev/null || true", timeout_sec=6, cache_ttl_sec=3).out
        return out.splitlines() if out else []

    def iptables(self) -> Tuple[List[str], List[str]]:
        v4 = self.sh.run("iptables -S 2>/dev/null || true", timeout_sec=6, cache_ttl_sec=3).out
        v6 = self.sh.run("ip6tables -S 2>/dev/null || true", timeout_sec=6, cache_ttl_sec=3).out
        return (v4.splitlines() if v4 else []), (v6.splitlines() if v6 else [])

    def reboot(self) -> bool:
        if self.sh.exists("ndmc"):
            res = self.sh.run("ndmc -c 'system reboot' 2>/dev/null", timeout_sec=5, cache_ttl_sec=0)
            return res.rc == 0
        res = self.sh.run("reboot", timeout_sec=5, cache_ttl_sec=0)
        return res.rc == 0

    def _find_leases_file(self) -> Optional[str]:
        candidates = [
            "/tmp/dhcp.leases",
            "/tmp/dnsmasq.leases",
            "/var/lib/misc/dnsmasq.leases",
            "/tmp/var/lib/misc/dnsmasq.leases",
            "/opt/var/lib/misc/dnsmasq.leases",
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        # As a fallback try find (may be slow; do it with low TTL)
        out = self.sh.run("find /tmp /var /opt -maxdepth 4 -name 'dnsmasq.leases' 2>/dev/null | head -n 1", timeout_sec=5, cache_ttl_sec=60).out
        return out.strip() or None

    def dhcp_clients(self) -> List[DhcpClient]:
        leases = self._find_leases_file()
        if not leases:
            return []
        clients: List[DhcpClient] = []
        try:
            with open(leases, "r", encoding="utf-8", errors="ignore") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    parts = ln.split()
                    # dnsmasq format: <expiry> <mac> <ip> <hostname> <clientid>
                    if len(parts) < 4:
                        continue
                    exp_raw, mac, ip, host = parts[0], parts[1], parts[2], parts[3]
                    expires_at = None
                    if exp_raw.isdigit():
                        try:
                            ts = int(exp_raw)
                            # some builds use 0 for "infinite"
                            if ts > 0:
                                expires_at = _dt.datetime.utcfromtimestamp(ts).isoformat() + "Z"
                        except Exception:
                            expires_at = None
                    clients.append(DhcpClient(mac=mac.lower(), ip=ip, hostname=host, expires_at=expires_at, source=leases))
        except Exception:
            return []
        # Sort by IP
        def ip_key(c: DhcpClient):
            return [int(x) if x.isdigit() else 0 for x in c.ip.split(".")] + [c.ip]
        return sorted(clients, key=ip_key)

    def wifi_station_macs(self) -> List[str]:
        macs: List[str] = []
        if self.sh.exists("iw"):
            devs = self.sh.run("iw dev 2>/dev/null | awk '/Interface/ {print $2}'", timeout_sec=5, cache_ttl_sec=10).out
            if devs:
                for iface in [x.strip() for x in devs.splitlines() if x.strip()]:
                    dump = self.sh.run(f"iw dev {iface} station dump 2>/dev/null | awk '/Station/ {{print $2}}'", timeout_sec=6, cache_ttl_sec=10).out
                    if dump:
                        macs.extend([m.strip().lower() for m in dump.splitlines() if m.strip()])
        # Fallback: arp neighbor type "lladdr" from wireless bridge is not reliable; keep empty
        return sorted(set(macs))
