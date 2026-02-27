
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import DriverBase, ServiceStatus
from .service import InitServiceDriver
from ..utils.net import guess_router_ipv4


@dataclass(frozen=True)
class HydraInfo:
    neo: ServiceStatus
    web: ServiceStatus
    web_url: Optional[str]


class HydraRouteDriver(DriverBase):
    def __init__(self, sh):
        super().__init__(sh)
        self.neo_svc = InitServiceDriver(sh, script_name_patterns=[r"hrneo", r"hydra.*neo", r"hydra.*route", r"hydra"], pkg_names=["hrneo", "hydraroute", "hydra-route", "hydra-route-neo"])
        self.web_svc = InitServiceDriver(sh, script_name_patterns=[r"hrweb", r"hydra.*web", r"hr.*web"], pkg_names=["hrweb", "hydraweb", "hydra-route-web"])

    def is_installed(self) -> bool:
        # installed if any known package is present OR init script exists
        cmd = """(for p in hrneo hydraroute hydra-route hydra-route-neo; do opkg status $p >/dev/null 2>&1 && exit 0; done; exit 1)"""
        if self.sh.run(cmd + " && echo yes || echo no", timeout_sec=5, cache_ttl_sec=10).out.strip() == "yes":
            return True
        return self.neo_svc.status().installed or self.web_svc.status().installed

    def overview(self, default_port: int = 2000) -> HydraInfo:
        neo = self.neo_svc.status()
        web = self.web_svc.status()
        ip = guess_router_ipv4(self.sh) or "192.168.0.1"
        url = f"http://{ip}:{default_port}"
        return HydraInfo(neo=neo, web=web, web_url=url)

    def start_neo(self) -> ServiceStatus:
        return self.neo_svc.start()

    def stop_neo(self) -> ServiceStatus:
        return self.neo_svc.stop()

    def restart_neo(self) -> ServiceStatus:
        return self.neo_svc.restart()

    def start_web(self) -> ServiceStatus:
        return self.web_svc.start()

    def stop_web(self) -> ServiceStatus:
        return self.web_svc.stop()

    def restart_web(self) -> ServiceStatus:
        return self.web_svc.restart()
