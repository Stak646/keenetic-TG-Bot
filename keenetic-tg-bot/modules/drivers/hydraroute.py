from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .base import DriverBase, ServiceStatus
from .service import InitServiceDriver
from ..utils.net import guess_router_ipv4


@dataclass(frozen=True)
class HydraInfo:
    """HydraRoute state.

    variant:
      - neo     : hrneo (+ optional hrweb)
      - classic : hydraroute (EOL)
      - relic   : legacy script-based install (EOL)
      - none
    """

    variant: str
    neo: ServiceStatus
    web: ServiceStatus
    classic: ServiceStatus
    relic: ServiceStatus
    web_url: Optional[str]
    update_to_neo: bool


class HydraRouteDriver(DriverBase):
    def __init__(self, sh):
        super().__init__(sh)
        self.neo_svc = InitServiceDriver(sh, script_name_patterns=[r"hrneo"], pkg_names=["hrneo"])
        self.web_svc = InitServiceDriver(sh, script_name_patterns=[r"hrweb"], pkg_names=["hrweb"])
        # Classic package name per upstream: hydraroute (EOL)
        self.classic_svc = InitServiceDriver(sh, script_name_patterns=[r"hydraroute"], pkg_names=["hydraroute"])

    # --- detection helpers

    def _neo_installed(self) -> bool:
        if self.sh.run("opkg status hrneo >/dev/null 2>&1 && echo yes || echo no", timeout_sec=5, cache_ttl_sec=10).out.strip() == "yes":
            return True
        return self.neo_svc.status().installed

    def _classic_installed(self) -> bool:
        if self.sh.run("opkg status hydraroute >/dev/null 2>&1 && echo yes || echo no", timeout_sec=5, cache_ttl_sec=10).out.strip() == "yes":
            return True
        return self.classic_svc.status().installed

    def _relic_installed(self) -> bool:
        # Relic doesn't always ship an opkg package; detect by characteristic files.
        # Upstream Relic docs mention /opt/etc/AdGuardHome/ipset.conf
        if os.path.isfile("/opt/etc/AdGuardHome/ipset.conf"):
            return True
        # Also accept a legacy init script name if present
        res = self.sh.run("ls /opt/etc/init.d 2>/dev/null | grep -Eqi 'hydraroute.*relic|relic.*hydraroute' && echo yes || echo no", timeout_sec=5, cache_ttl_sec=30)
        return res.out.strip() == "yes"

    def variant(self) -> str:
        if self._neo_installed():
            return "neo"
        if self._classic_installed():
            return "classic"
        if self._relic_installed():
            return "relic"
        return "none"

    def is_installed(self) -> bool:
        return self.variant() != "none"

    def overview(self, default_port: int = 2000) -> HydraInfo:
        var = self.variant()
        neo = self.neo_svc.status() if var == "neo" else ServiceStatus(installed=False, running=False, version=None, detail="")
        web = self.web_svc.status() if var == "neo" else ServiceStatus(installed=False, running=False, version=None, detail="")
        classic = self.classic_svc.status() if var == "classic" else ServiceStatus(installed=False, running=False, version=None, detail="")
        relic = ServiceStatus(installed=(var == "relic"), running=False, version=None, detail="")

        ip = guess_router_ipv4(self.sh) or "192.168.0.1"
        # Web UI is typical for Neo/Classic, but Relic may not have it.
        url = None
        if var in ("neo", "classic"):
            url = f"http://{ip}:{int(default_port)}"
        update_to_neo = var in ("classic", "relic")
        return HydraInfo(variant=var, neo=neo, web=web, classic=classic, relic=relic, web_url=url, update_to_neo=update_to_neo)

    # --- controls (Neo only)

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
