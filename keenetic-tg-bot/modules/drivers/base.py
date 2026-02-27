
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import shlex

from ..utils.shell import Shell


@dataclass
class ServiceStatus:
    installed: bool
    running: bool
    version: Optional[str] = None
    detail: str = ""


class DriverBase:
    def __init__(self, sh: Shell):
        self.sh = sh

    def opkg_installed(self, pkg: str, cache_ttl_sec: int = 5) -> bool:
        """Robust check that an opkg package is *installed*.

        We parse opkg output instead of relying on exit codes because on some
        environments/plugins `opkg status <pkg>` may exit with 0 even when the
        package is missing (printing an error message instead).
        """
        p = shlex.quote(str(pkg))
        cmd = (
            f"opkg status {p} 2>/dev/null | "
            "grep -q '^Status: install ok installed' && echo yes || echo no"
        )
        res = self.sh.run(cmd, timeout_sec=10, cache_ttl_sec=int(cache_ttl_sec))
        return res.out.strip() == "yes"
