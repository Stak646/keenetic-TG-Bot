
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .base import DriverBase
from ..utils.shell import ShellResult


@dataclass(frozen=True)
class OpkgResult:
    ok: bool
    rc: int
    out: str
    err: str
    ms: int


class OpkgDriver(DriverBase):
    def _run(self, cmd: str, timeout_sec: int = 120) -> OpkgResult:
        res: ShellResult = self.sh.run(cmd, timeout_sec=timeout_sec, cache_ttl_sec=0)
        ok = (res.rc == 0)
        return OpkgResult(ok=ok, rc=res.rc, out=res.out, err=res.err, ms=res.ms)

    def update(self) -> OpkgResult:
        res = self._run("opkg update", timeout_sec=180)
        if res.ok:
            return res
        # BusyBox wget without SSL may fail on https feeds: "not an http or ftp url: https://..."
        msg = (res.out + "\n" + res.err)
        if "not an http or ftp url: https://" in msg or "wget returned 1" in msg:
            # Try to install HTTPS-capable wget and retry
            self._run("opkg remove wget-nossl", timeout_sec=120)
            self._run("opkg install wget-ssl ca-certificates", timeout_sec=600)
            res2 = self._run("opkg update", timeout_sec=180)
            return res2
        return res

    def upgrade(self) -> OpkgResult:
        return self._run("opkg upgrade", timeout_sec=600)

    def install(self, pkg: str) -> OpkgResult:
        return self._run(f"opkg install {pkg}", timeout_sec=600)

    def remove(self, pkg: str) -> OpkgResult:
        return self._run(f"opkg remove {pkg}", timeout_sec=300)

    def info(self, pkg: str) -> OpkgResult:
        return self._run(f"opkg info {pkg}", timeout_sec=60)

    def list_installed(self) -> List[str]:
        res = self.sh.run("opkg list-installed", timeout_sec=60, cache_ttl_sec=5)
        if res.rc != 0:
            return []
        lines = [ln.strip() for ln in res.out.splitlines() if ln.strip()]
        return lines

    def search(self, query: str) -> List[str]:
        q = query.strip()
        if not q:
            return []
        res = self.sh.run(f"opkg list | grep -i {q!r}", timeout_sec=30, cache_ttl_sec=0)
        if res.rc != 0 and not res.out:
            return []
        return [ln.strip() for ln in res.out.splitlines() if ln.strip()]

    def pkg_installed(self, pkg: str) -> bool:
        res = self.sh.run(f"opkg status {pkg} 2>/dev/null | grep -q '^Status: install ok installed' && echo yes || echo no", timeout_sec=10, cache_ttl_sec=3)
        return res.out.strip() == "yes"

    def pkg_version(self, pkg: str) -> Optional[str]:
        res = self.sh.run(f"opkg status {pkg} 2>/dev/null | awk -F': ' '/^Version: /{{print $2; exit}}'", timeout_sec=10, cache_ttl_sec=5)
        v = res.out.strip()
        return v or None

    def pkg_available_version(self, pkg: str) -> Optional[str]:
        res = self.sh.run(f"opkg info {pkg} 2>/dev/null | awk -F': ' '/^Version: /{{print $2; exit}}'", timeout_sec=10, cache_ttl_sec=0)
        v = res.out.strip()
        return v or None

    def list_upgradable(self) -> List[str]:
        res = self.sh.run("opkg list-upgradable 2>/dev/null | awk '{print $1}'", timeout_sec=30, cache_ttl_sec=0)
        if res.rc != 0:
            return []
        return [x.strip() for x in res.out.splitlines() if x.strip()]

    def pkg_upgradable(self, pkg: str) -> bool:
        upg = self.list_upgradable()
        return pkg in set(upg)
