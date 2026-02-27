# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
import re
import time

TG_HOST = "api.telegram.org"

def _first_ip_from_nslookup(out: str) -> Optional[str]:
    # nslookup output varies
    # Try to find first IPv4
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)", out or "")
    return m.group(1) if m else None

def telegram_connectivity(shell) -> str:
    """
    Best-effort connectivity report to api.telegram.org.
    Uses only safe fixed commands (no user input).
    """
    parts = []
    # DNS
    rc, ns = shell.run(["nslookup", TG_HOST], timeout_sec=12)
    parts.append(f"DNS rc={rc}")
    ip = _first_ip_from_nslookup(ns)
    if ip:
        parts.append(f"IP: {ip}")
        rc2, route = shell.run(["ip", "route", "get", ip], timeout_sec=8)
        parts.append(f"route rc={rc2}")
        if route:
            r = route.strip()
            parts.append(r)
            mdev = re.search(r"\bdev\s+(\S+)", r)
            dev = mdev.group(1) if mdev else ""
            if dev and any(x in dev for x in ["opkgtun", "tun", "wg", "awg"]):
                parts.append(f"Hint: api.telegram.org seems routed via tunnel dev={dev}. Consider excluding Telegram from tunnels / route it via WAN.")
        # Quick TLS head
        rc3, curl = shell.run(["curl", "-IksS", "--connect-timeout", "10", "--max-time", "20", f"https://{TG_HOST}/"], timeout_sec=25)
        parts.append(f"curl rc={rc3}")
        if curl:
            parts.append("\n".join(curl.splitlines()[:15]))
    else:
        parts.append("IP: not resolved (see nslookup output)")
        parts.append("\n".join((ns or "").splitlines()[:25]))
    return "\n".join(parts).strip()

def dns_diagnostics(shell) -> str:
    parts = []
    rc, resolv = shell.run(["cat", "/etc/resolv.conf"], timeout_sec=5)
    parts.append(f"/etc/resolv.conf rc={rc}")
    if resolv:
        parts.append(resolv.strip())
    rc2, ns1 = shell.run(["nslookup", "google.com"], timeout_sec=10)
    parts.append(f"nslookup google.com rc={rc2}")
    parts.append("\n".join((ns1 or "").splitlines()[:25]))
    rc3, ns2 = shell.run(["nslookup", TG_HOST], timeout_sec=10)
    parts.append(f"nslookup {TG_HOST} rc={rc3}")
    parts.append("\n".join((ns2 or "").splitlines()[:25]))
    return "\n".join(parts).strip()

def net_quick(shell) -> str:
    parts = []
    rc, ipbr = shell.run(["ip", "-br", "addr"], timeout_sec=8)
    parts.append("ip -br addr:")
    parts.append(ipbr.strip() if ipbr else "(empty)")
    rc2, r4 = shell.run(["ip", "-4", "route"], timeout_sec=8)
    parts.append("\nip -4 route:")
    parts.append("\n".join((r4 or "").splitlines()[:60]))
    return "\n".join(parts).strip()
