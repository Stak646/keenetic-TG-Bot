
from __future__ import annotations

from typing import Dict, List

from .base import ComponentBase
from ..ui import Screen, kb, btn, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.text import esc, pre
from ..drivers.hydraroute import HydraRouteDriver


class HydraComponent(ComponentBase):
    id = "hy"
    emoji = "🧬"
    title_key = "home.hydra"

    def __init__(self, drv: HydraRouteDriver):
        self.drv = drv

    def is_available(self) -> bool:
        return self.drv.is_installed()

    def quick_status(self):
        if not self.drv.is_installed():
            return None
        st = self.drv.overview().neo.running
        return "running" if st else "stopped"

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._overview(app, i18n)
        if cmd == "restart":
            return app.run_long_job("HydraRoute Neo restart", job=lambda: self.drv.restart_neo(), back="hy|m")
        if cmd == "restart_web":
            return app.run_long_job("HydraRoute Web restart", job=lambda: self.drv.restart_web(), back="hy|m")
        if cmd == "start":
            return app.run_long_job("HydraRoute Neo start", job=lambda: self.drv.start_neo(), back="hy|m")
        if cmd == "stop":
            return app.run_long_job("HydraRoute Neo stop", job=lambda: self.drv.stop_neo(), back="hy|m")
        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _overview(self, app: "App", i18n: I18N) -> Screen:
        if not self.drv.is_installed():
            return Screen(text=f"{i18n.t('hydra.header')}\n\n{i18n.t('hydra.not_installed')}", kb=kb([[nav_home(i18n)]]))
        info = self.drv.overview(app.cfg.hydra_web_port)
        lines = [
            f"Neo: {'✅' if info.neo.running else '⛔'}",
            f"Web: {'✅' if info.web.running else ('➖' if not info.web.installed else '⛔')}",
        ]
        if info.web_url:
            lines.append(f"Web UI: {info.web_url}")
        text = f"{i18n.t('hydra.header')}\n\n{pre(chr(10).join(lines))}"
        rows = [
            [btn(i18n.t("btn.start"), "hy|start"), btn(i18n.t("btn.stop"), "hy|stop"), btn(i18n.t("btn.restart"), "hy|restart")],
            [btn(i18n.t("btn.restart") + " Web", "hy|restart_web")],
            [nav_back(i18n, "h|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))
