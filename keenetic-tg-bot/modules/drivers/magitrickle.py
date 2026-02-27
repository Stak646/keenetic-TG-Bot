from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import DriverBase, ServiceStatus
from .service import InitServiceDriver


@dataclass(frozen=True)
class MagiInfo:
    svc: ServiceStatus
    web_url: Optional[str]


class MagiTrickleDriver(DriverBase):
    def __init__(self, sh):
        super().__init__(sh)
        self.svc = InitServiceDriver(sh, script_name_patterns=[r"magitrickle"], pkg_names=["magitrickle"])

    def is_installed(self) -> bool:
        ok = self.sh.run("opkg status magitrickle >/dev/null 2>&1 && echo yes || echo no", timeout_sec=5, cache_ttl_sec=10).out.strip() == "yes"
        return ok or self.svc.status().installed

    def overview(self, default_port: int = 0) -> MagiInfo:
        # MagiTrickle doesn't have a stable upstream Web UI on Keenetic by default.
        return MagiInfo(svc=self.svc.status(), web_url=None)

    def start(self) -> ServiceStatus:
        return self.svc.start()

    def stop(self) -> ServiceStatus:
        return self.svc.stop()

    def restart(self) -> ServiceStatus:
        return self.svc.restart()
