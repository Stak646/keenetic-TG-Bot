
from __future__ import annotations

import re
from typing import Optional

from .shell import Shell


def guess_router_ipv4(sh: Shell) -> Optional[str]:
    """
    Best effort: return first non-loopback IPv4 address assigned to an interface.
    """
    out = sh.run("ip -4 addr show 2>/dev/null || true", timeout_sec=5, cache_ttl_sec=5).out
    if not out:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", line)
            if not m:
                continue
            ip = m.group(1)
            if ip.startswith("127."):
                continue
            return ip
    return None
