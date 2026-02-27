from __future__ import annotations

from typing import Dict

from .base import ComponentBase
from ..ui import Screen, kb, btn, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.text import pre
from ..drivers.magitrickle import MagiTrickleDriver
from ..drivers.hydraroute import HydraRouteDriver


class MagiTrickleComponent(ComponentBase):
    id = "mt"
    emoji = "🪄"
    title_key = "home.magitrickle"

    def __init__(self, drv: MagiTrickleDriver, hydra: HydraRouteDriver):
        self.drv = drv
        self.hydra = hydra

    def is_available(self) -> bool:
        # Mutual exclusion: if HydraRoute (any variant) is installed, MagiTrickle is ignored.
        return self.drv.is_installed() and not self.hydra.is_installed()

    def quick_status(self):
        if not self.is_available():
            return None
        st = self.drv.overview().svc.running
        return "running" if st else "stopped"

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._overview(app, i18n)
        if cmd == "restart":
            return app.run_long_job("MagiTrickle restart", job=lambda: self.drv.restart(), back="mt|m")
        if cmd == "start":
            return app.run_long_job("MagiTrickle start", job=lambda: self.drv.start(), back="mt|m")
        if cmd == "stop":
            return app.run_long_job("MagiTrickle stop", job=lambda: self.drv.stop(), back="mt|m")
        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _overview(self, app: "App", i18n: I18N) -> Screen:
        # If HydraRoute is present, we explicitly ignore MagiTrickle.
        if self.hydra.is_installed():
            return Screen(
                text=f"{i18n.t('magitrickle.header')}\n\n{i18n.t('magitrickle.ignored_by_hydra')}",
                kb=kb([[nav_home(i18n)]]),
            )
        if not self.drv.is_installed():
            return Screen(text=f"{i18n.t('magitrickle.header')}\n\n{i18n.t('magitrickle.not_installed')}", kb=kb([[nav_home(i18n)]]))

        info = self.drv.overview()
        lines = [f"Service: {'✅' if info.svc.running else '⛔'}"]
        text = f"{i18n.t('magitrickle.header')}\n\n{pre(chr(10).join(lines))}"
        rows = [
            [btn(i18n.t('btn.start'), 'mt|start'), btn(i18n.t('btn.stop'), 'mt|stop'), btn(i18n.t('btn.restart'), 'mt|restart')],
            [nav_back(i18n, 'h|m'), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))
