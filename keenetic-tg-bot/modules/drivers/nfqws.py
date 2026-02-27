
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import DriverBase, ServiceStatus
from .service import InitServiceDriver
from ..utils.net import guess_router_ipv4


@dataclass(frozen=True)
class NfqwsInfo:
    core: ServiceStatus
    web: ServiceStatus
    mode: str
    web_url: Optional[str]


class NfqwsDriver(DriverBase):
    def __init__(self, sh):
        super().__init__(sh)
        self.core_svc = InitServiceDriver(sh, script_name_patterns=[r"nfqws2", r"nfqws"], pkg_names=["nfqws2"])
        self.web_svc = InitServiceDriver(sh, script_name_patterns=[r"nfqws.*web", r"nfqws-keenetic-web"], pkg_names=["nfqws-keenetic-web", "nfqws-web"])
        # mode detection is best-effort
    def is_installed(self) -> bool:
        return self.sh.run("opkg status nfqws2 >/dev/null 2>&1 && echo yes || echo no", timeout_sec=5, cache_ttl_sec=10).out.strip() == "yes" or self.core_svc.status().installed

    def detect_mode(self) -> str:
        # Try config file patterns
        candidates = [
            "/opt/etc/nfqws2/nfqws2.conf",
            "/opt/etc/nfqws2.conf",
            "/opt/etc/nfqws.conf",
        ]
        for p in candidates:
            cmd = "[ -f '%s' ] && awk -F'=' '/^mode[ 	]*=/ {print $2; exit}' '%s' || true" % (p, p)
            res = self.sh.run(cmd, timeout_sec=5, cache_ttl_sec=10)
            v = res.out.strip()
            if v:
                return v
        # Try command
        res = self.sh.run("nfqws2 --help 2>/dev/null | head -n 1 || true", timeout_sec=5, cache_ttl_sec=10)
        if res.out:
            return "auto"
        return "unknown"

    def overview(self, default_port: int = 80) -> NfqwsInfo:
        core = self.core_svc.status()
        web = self.web_svc.status()
        mode = self.detect_mode()
        ip = guess_router_ipv4(self.sh) or "192.168.0.1"
        url = f"http://{ip}:{default_port}"
        return NfqwsInfo(core=core, web=web, mode=mode, web_url=url)

    def start(self) -> ServiceStatus:
        return self.core_svc.start()

    def stop(self) -> ServiceStatus:
        return self.core_svc.stop()

    def restart(self) -> ServiceStatus:
        return self.core_svc.restart()

    def start_web(self) -> ServiceStatus:
        return self.web_svc.start()

    def stop_web(self) -> ServiceStatus:
        return self.web_svc.stop()

    def restart_web(self) -> ServiceStatus:
        return self.web_svc.restart()
