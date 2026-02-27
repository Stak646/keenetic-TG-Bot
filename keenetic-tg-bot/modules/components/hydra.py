
from __future__ import annotations

from typing import Dict, List

from .base import ComponentBase
from ..ui import Screen, kb, btn, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.text import esc, pre
from ..drivers.hydraroute import HydraRouteDriver
from ..drivers.magitrickle import MagiTrickleDriver
from ..utils.opkg_repos import detect_arch, ensure_src


class HydraComponent(ComponentBase):
    id = "hy"
    emoji = "🧬"
    title_key = "home.hydra"

    def __init__(self, drv: HydraRouteDriver, magi: MagiTrickleDriver):
        self.drv = drv
        self.magi = magi

    def is_available(self) -> bool:
        # Mutual exclusion: if MagiTrickle is installed, HydraRoute is ignored.
        return self.drv.is_installed() and not self.magi.is_installed()

    def quick_status(self):
        if not self.is_available():
            return None
        info = self.drv.overview()
        if info.variant == "neo":
            return "running" if info.neo.running else "stopped"
        # Classic/Relic are considered outdated
        return "stopped"

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._overview(app, i18n)
        if cmd == "update_to_neo":
            return app.run_long_job("HydraRoute update to Neo", job=lambda: self._update_to_neo(app), back="hy|m")
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
        if self.magi.is_installed():
            return Screen(text=f"{i18n.t('hydra.header')}\n\n{i18n.t('hydra.ignored_by_magitrickle')}", kb=kb([[nav_home(i18n)]]))
        if not self.drv.is_installed():
            return Screen(text=f"{i18n.t('hydra.header')}\n\n{i18n.t('hydra.not_installed')}", kb=kb([[nav_home(i18n)]]))
        info = self.drv.overview(app.cfg.hydra_web_port)

        if info.update_to_neo:
            # Classic/Relic: show ONLY update button as requested
            lines = [f"Detected: {info.variant.upper()} (EOL)", "Action: update to Neo"]
            if info.web_url:
                lines.append(f"Web UI: {info.web_url}")
            text = f"{i18n.t('hydra.header')}\n\n{pre(chr(10).join(lines))}"
            rows = [
                [btn(i18n.t('btn.update') + ' → Neo', 'hy|update_to_neo')],
                [nav_back(i18n, 'h|m'), nav_home(i18n)],
            ]
            return Screen(text=text, kb=kb(rows))

        # Neo
        lines = [
            f"Neo: {'✅' if info.neo.running else '⛔'}",
            f"Web: {'✅' if info.web.running else ('➖' if not info.web.installed else '⛔')}",
        ]
        if info.web_url:
            lines.append(f"Web UI: {info.web_url}")
        text = f"{i18n.t('hydra.header')}\n\n{pre(chr(10).join(lines))}"
        rows = [
            [btn(i18n.t('btn.start'), 'hy|start'), btn(i18n.t('btn.stop'), 'hy|stop'), btn(i18n.t('btn.restart'), 'hy|restart')],
            [btn(i18n.t('btn.restart') + ' Web', 'hy|restart_web')],
            [nav_back(i18n, 'h|m'), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _update_to_neo(self, app: "App"):
        arch = detect_arch(app.sh)
        if not arch.entware_arch:
            return app.sh.run("echo 'Not supported on this architecture' >&2; exit 1", timeout_sec=5, cache_ttl_sec=0)
        url = f"https://ground-zerro.github.io/release/keenetic/{arch.entware_arch}"
        ensure_src(app.sh, "ground_zerro", url, "ground-zerro.conf")
        app.sh.run("opkg update", timeout_sec=180, cache_ttl_sec=0)
        # Install Neo (and Web UI). This is the only supported install target.
        return app.sh.run("opkg install hrneo hrweb", timeout_sec=600, cache_ttl_sec=0)
