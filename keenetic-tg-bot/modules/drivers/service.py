
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from .base import DriverBase, ServiceStatus


class InitServiceDriver(DriverBase):
    """
    Generic wrapper around /opt/etc/init.d scripts.
    """
    def __init__(self, sh, script_name_patterns: List[str], pkg_names: List[str] = None):
        super().__init__(sh)
        self.script_name_patterns = script_name_patterns
        self.pkg_names = pkg_names or []

    def _find_script(self) -> Optional[str]:
        init_dir = "/opt/etc/init.d"
        if not os.path.isdir(init_dir):
            return None
        names = []
        try:
            names = os.listdir(init_dir)
        except Exception:
            return None
        for pat in self.script_name_patterns:
            # Some packages use mixed-case names depending on build scripts.
            rx = re.compile(pat, flags=re.IGNORECASE)
            for n in sorted(names):
                if rx.search(n):
                    return os.path.join(init_dir, n)
        return None

    def _run(self, action: str) -> ServiceStatus:
        script = self._find_script()
        installed = script is not None
        version = None
        if self.pkg_names:
            for pkg in self.pkg_names:
                v = self.sh.run(f"opkg status {pkg} 2>/dev/null | awk -F': ' '/^Version: /{{print $2; exit}}'", timeout_sec=10, cache_ttl_sec=10).out.strip()
                if v:
                    version = v
                    break
        if not script:
            return ServiceStatus(installed=False, running=False, version=version, detail="init script not found")

        res = self.sh.run(f"sh {script} {action} 2>/dev/null || true", timeout_sec=30, cache_ttl_sec=0)
        # We determine running via pidof if possible
        running = False
        # Try to guess binary from script name
        base = os.path.basename(script)
        guess = re.sub(r"^S\d+", "", base)
        if guess:
            pid = self.sh.run(f"pidof {guess} 2>/dev/null || true", timeout_sec=5, cache_ttl_sec=0).out.strip()
            running = bool(pid)
        return ServiceStatus(installed=True, running=running, version=version, detail=(res.out or res.err or "").strip())

    def status(self) -> ServiceStatus:
        script = self._find_script()
        installed = script is not None
        if not installed:
            return ServiceStatus(installed=False, running=False, version=None, detail="init script not found")
        # Try script status
        res = self.sh.run(f"sh {script} status 2>/dev/null || true", timeout_sec=10, cache_ttl_sec=0)
        out = (res.out or res.err).strip()
        running = "running" in out.lower() or "alive" in out.lower()
        return ServiceStatus(installed=True, running=running, version=None, detail=out)

    def start(self) -> ServiceStatus:
        return self._run("start")

    def stop(self) -> ServiceStatus:
        return self._run("stop")

    def restart(self) -> ServiceStatus:
        return self._run("restart")
