
from __future__ import annotations

from typing import Dict, List, Tuple

from .base import ComponentBase
from ..ui import Screen, kb, btn, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.text import esc, pre
from ..drivers.speedtest import SpeedTestDriver, DEFAULT_HTTP_SERVERS
from ..drivers.opkg import OpkgDriver
from ..drivers.awg import AwgDriver


class SpeedComponent(ComponentBase):
    id = "sp"
    emoji = "🚀"
    title_key = "home.speed"

    def __init__(self, drv: SpeedTestDriver, opkg: OpkgDriver, awg: AwgDriver):
        self.drv = drv
        self.opkg = opkg
        self.awg = awg

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._menu(app, i18n)
        if cmd == "http":
            # list servers
            rows: List[List[Tuple[str, str]]] = []
            for idx, (name, url) in enumerate(DEFAULT_HTTP_SERVERS):
                rows.append([btn(name, f"sp|http_run|i={idx}")])
            rows.append([nav_back(i18n, "h|m"), nav_home(i18n)])
            return Screen(text=f"{i18n.t('speed.header')}\n\n{i18n.t('speed.generic')}", kb=kb(rows))
        if cmd == "http_run":
            i = int(params.get("i", "0") or 0)
            if not (0 <= i < len(DEFAULT_HTTP_SERVERS)):
                return Screen(text=i18n.t("err.bad_input"), kb=kb([[nav_back(i18n, "sp|http"), nav_home(i18n)]]))
            name, url = DEFAULT_HTTP_SERVERS[i]
            return app.run_long_job(
                i18n.t("speed.running"),
                job=lambda: self.drv.http_download(url),
                back="sp|m",
                title_prefix=f"HTTP: {name}",
            )
        if cmd == "stgo":
            if not self.drv.has_speedtest_go():
                return Screen(text=i18n.t("speed.not_available"), kb=kb([[btn(i18n.t("speed.install_speedtest_go"), "sp|stgo_install")],[nav_back(i18n, "sp|m"), nav_home(i18n)]]))
            return app.run_long_job(
                i18n.t("speed.running"),
                job=lambda: self.drv.run_speedtest_go(),
                back="sp|m",
                title_prefix="speedtest-go",
            )
        if cmd == "stgo_install":
            return app.run_long_job("Install speedtest-go", job=lambda: self.opkg.install("speedtest-go"), back="sp|m")
        if cmd == "awg":
            return Screen(text=i18n.t("speed.running"), kb=kb([[btn("Open AWG speed", "aw|speed")],[nav_back(i18n,"sp|m"),nav_home(i18n)]]))
        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _menu(self, app: "App", i18n: I18N) -> Screen:
        rows: List[List[Tuple[str, str]]] = [
            [btn(i18n.t("speed.generic"), "sp|http")],
            [btn("speedtest-go", "sp|stgo")],
        ]
        if self.awg.detect():
            rows.append([btn(i18n.t("speed.awg"), "aw|speed")])
        rows.append([nav_back(i18n, "h|m"), nav_home(i18n)])
        return Screen(text=f"{i18n.t('speed.header')}\n\n{i18n.t('home.subtitle')}", kb=kb(rows))
