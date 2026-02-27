# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ..constants import *
from ..utils import *
from ..shell import Shell

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
