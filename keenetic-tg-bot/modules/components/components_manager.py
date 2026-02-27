
from __future__ import annotations

from typing import Dict, List, Tuple

from .base import ComponentBase
from ..ui import Screen, kb, btn, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.opkg_repos import detect_arch, ensure_src
from ..utils.text import esc, pre
from ..drivers.opkg import OpkgDriver
from ..drivers.hydraroute import HydraRouteDriver
from ..drivers.magitrickle import MagiTrickleDriver
from ..drivers.nfqws import NfqwsDriver
from ..drivers.awg import AwgDriver


class ComponentsManagerComponent(ComponentBase):
    id = "c"
    emoji = "📦"
    title_key = "home.components"

    def __init__(self, opkg: OpkgDriver, hydra: HydraRouteDriver, magi: MagiTrickleDriver, nfqws: NfqwsDriver, awg: AwgDriver):
        self.opkg = opkg
        self.hydra = hydra
        self.magi = magi
        self.nfqws = nfqws
        self.awg = awg

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._menu(app, i18n)
        if cmd == "hydra":
            return self._hydra_menu(app, i18n)
        if cmd == "magi":
            return self._magi_menu(app, i18n)
        if cmd == "nfqws":
            return self._nfqws_menu(app, i18n)
        if cmd == "awg":
            return self._awg_menu(app, i18n)

        # install/remove actions
        if cmd == "install_hydra":
            return self._install_hydra(app, i18n)
        if cmd == "remove_hydra":
            return app.run_long_job(i18n.t("btn.remove") + " HydraRoute", job=lambda: self.opkg.remove("hrneo hrweb"), back="c|hydra")
        if cmd == "update_hydra_to_neo":
            return self._install_hydra(app, i18n)

        if cmd == "install_magi":
            return self._install_magi(app, i18n)
        if cmd == "remove_magi":
            return app.run_long_job(i18n.t("btn.remove") + " MagiTrickle", job=lambda: self.opkg.remove("magitrickle"), back="c|magi")
        if cmd == "install_nfqws2":
            return self._install_nfqws2(app, i18n)
        if cmd == "remove_nfqws2":
            def job():
                r1 = self.opkg.remove("nfqws2-keenetic")
                if r1.ok:
                    return r1
                return self.opkg.remove("nfqws2")
            return app.run_long_job(i18n.t("btn.remove") + " NFQWS2", job=job, back="c|nfqws")
        if cmd == "install_nfqwsweb":
            return self._install_nfqwsweb(app, i18n)
        if cmd == "remove_nfqwsweb":
            def job():
                r1 = self.opkg.remove("nfqws-keenetic-web")
                if r1.ok:
                    return r1
                return self.opkg.remove("nfqws-web")
            return app.run_long_job(i18n.t("btn.remove") + " NFQWS web", job=job, back="c|nfqws")
        if cmd == "install_awg":
            return self._install_awg(app, i18n)
        if cmd == "remove_awg":
            def job():
                r1 = self.opkg.remove("awg-manager")
                if r1.ok:
                    return r1
                return self.opkg.remove("awgmanager")
            return app.run_long_job(i18n.t("btn.remove") + " AWG Manager", job=job, back="c|awg")

        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _status_line(self, i18n: I18N, name: str, installed: bool, running: bool) -> str:
        inst = i18n.t("comp.status.installed") if installed else i18n.t("comp.status.missing")
        run = i18n.t("comp.status.running") if running else i18n.t("comp.status.stopped")
        if not installed:
            run = i18n.t("comp.status.unknown")
        return f"• {name}: <b>{inst}</b>, <b>{run}</b>"

    def _menu(self, app: "App", i18n: I18N) -> Screen:
        magi_inst = self.magi.is_installed()
        hydra_inst = self.hydra.is_installed()
        hydra_info = self.hydra.overview(app.cfg.hydra_web_port) if hydra_inst else None
        hydra_run = (hydra_info.neo.running if hydra_info and hydra_info.variant == "neo" else False)
        nfqws_inst = self.nfqws.is_installed()
        nfqws_run = self.nfqws.overview(app.cfg.nfqws_web_port).core.running if nfqws_inst else False
        awg_inst = self.awg.detect()
        # "running" means API is reachable (more accurate than "init script exists")
        awg_run = False
        if awg_inst:
            try:
                awg_run = bool(self.awg.version().ok)
            except Exception:
                awg_run = False

        lines = [
            i18n.t("comp.subtitle"),
            "",
            self._status_line(i18n, "MagiTrickle", magi_inst, self.magi.overview().svc.running if magi_inst else False),
            self._status_line(i18n, "HydraRoute", hydra_inst, hydra_run),
            self._status_line(i18n, "NFQWS2", nfqws_inst, nfqws_run),
            self._status_line(i18n, "AWG Manager", awg_inst, awg_run),
        ]
        rows = [
            [btn("🪄 MagiTrickle", "c|magi")],
            [btn("🧬 HydraRoute", "c|hydra")],
            [btn("🧱 NFQWS2", "c|nfqws")],
            [btn("🧷 AWG Manager", "c|awg")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('comp.header')}\n\n" + "\n".join(lines), kb=kb(rows))

    def _hydra_menu(self, app: "App", i18n: I18N) -> Screen:
        if self.magi.is_installed():
            text = f"{i18n.t('hydra.header')}\n\n{i18n.t('hydra.ignored_by_magitrickle')}"
            rows = [[nav_back(i18n, "c|m"), nav_home(i18n)]]
            return Screen(text=text, kb=kb(rows))

        inst = self.hydra.is_installed()
        info = self.hydra.overview(app.cfg.hydra_web_port)
        text = f"{i18n.t('hydra.header')}\n\n"
        if not inst:
            text += i18n.t("hydra.not_installed")
        else:
            if info.update_to_neo:
                text += f"Detected: <b>{esc(info.variant.upper())}</b> (EOL)\n\n"
                text += i18n.t("hydra.update_only")
                if info.web_url:
                    text += f"\n\nWeb UI: {esc(info.web_url)}"
            else:
                text += self._status_line(i18n, "Neo", True, info.neo.running) + "\n"
                text += self._status_line(i18n, "Web", info.web.installed, info.web.running) + "\n"
                text += f"\nWeb UI: {esc(info.web_url or '')}"

        rows = []
        if not inst:
            rows.append([btn(i18n.t("btn.install"), "c|install_hydra")])
        else:
            if info.update_to_neo:
                rows.append([btn(i18n.t("btn.update") + " → Neo", "c|update_hydra_to_neo")])
            else:
                rows.append([btn(i18n.t("btn.restart"), "hy|restart"), btn(i18n.t("btn.restart") + " Web", "hy|restart_web")])
                rows.append([btn(i18n.t("btn.remove"), "c|remove_hydra")])
        rows.append([nav_back(i18n, "c|m"), nav_home(i18n)])
        return Screen(text=text, kb=kb(rows))

    def _magi_menu(self, app: "App", i18n: I18N) -> Screen:
        # Mutual exclusion: if HydraRoute exists, MagiTrickle is ignored.
        if self.hydra.is_installed():
            text = f"{i18n.t('magitrickle.header')}\n\n{i18n.t('magitrickle.ignored_by_hydra')}"
            rows = [[nav_back(i18n, 'c|m'), nav_home(i18n)]]
            return Screen(text=text, kb=kb(rows))

        inst = self.magi.is_installed()
        info = self.magi.overview()
        text = f"{i18n.t('magitrickle.header')}\n\n"
        if not inst:
            text += i18n.t('magitrickle.not_installed')
        else:
            text += self._status_line(i18n, 'Service', True, info.svc.running)

        rows = []
        if not inst:
            rows.append([btn(i18n.t('btn.install'), 'c|install_magi')])
        else:
            rows.append([btn(i18n.t('btn.restart'), 'mt|restart')])
            rows.append([btn(i18n.t('btn.remove'), 'c|remove_magi')])
        rows.append([nav_back(i18n, 'c|m'), nav_home(i18n)])
        return Screen(text=text, kb=kb(rows))

    def _nfqws_menu(self, app: "App", i18n: I18N) -> Screen:
        inst = self.nfqws.is_installed()
        info = self.nfqws.overview(app.cfg.nfqws_web_port)
        text = f"{i18n.t('nfqws.header')}\n\n"
        if not inst:
            text += i18n.t("nfqws.not_installed")
        else:
            text += self._status_line(i18n, "NFQWS2", True, info.core.running) + "\n"
            text += f"• Mode: <b>{esc(info.mode)}</b>\n"
            text += self._status_line(i18n, "Web", info.web.installed, info.web.running) + "\n"
            if info.web_url:
                text += f"\nWeb UI: {esc(info.web_url)}"
        rows: List[List[Tuple[str, str]]] = []
        if not inst:
            rows.append([btn(i18n.t("btn.install") + " NFQWS2", "c|install_nfqws2")])
        else:
            rows.append([btn(i18n.t("btn.restart"), "nq|restart")])
            rows.append([btn(i18n.t("btn.remove"), "c|remove_nfqws2")])
        # web ui package optional
        if inst:
            if info.web.installed:
                rows.append([btn(i18n.t("btn.restart") + " Web", "nq|restart_web"), btn(i18n.t("btn.remove") + " Web", "c|remove_nfqwsweb")])
            else:
                rows.append([btn(i18n.t("btn.install") + " Web", "c|install_nfqwsweb")])

        rows.append([nav_back(i18n, "c|m"), nav_home(i18n)])
        return Screen(text=text, kb=kb(rows))

    def _awg_menu(self, app: "App", i18n: I18N) -> Screen:
        inst = self.awg.detect()
        ver = self.awg.version() if inst else None
        text = f"{i18n.t('awg.header')}\n\n"
        if not inst:
            text += i18n.t("awg.not_installed")
        else:
            if ver and ver.ok:
                text += pre(str(ver.data)) + "\n"
        rows = []
        if not inst:
            rows.append([btn(i18n.t("btn.install"), "c|install_awg")])
        else:
            rows.append([btn(i18n.t("btn.restart"), "aw|restart"), btn(i18n.t("btn.remove"), "c|remove_awg")])
        rows.append([nav_back(i18n, "c|m"), nav_home(i18n)])
        return Screen(text=text, kb=kb(rows))

    def _install_hydra(self, app: "App", i18n: I18N) -> Screen:
        if self.magi.is_installed():
            return Screen(text=i18n.t('hydra.ignored_by_magitrickle'), kb=kb([[nav_back(i18n, 'c|hydra'), nav_home(i18n)]]))
        arch = detect_arch(app.sh)
        if not arch.entware_arch:
            return Screen(text=i18n.t("err.not_supported"), kb=kb([[nav_back(i18n, "c|hydra"), nav_home(i18n)]]))
        # ground-zerro feed
        url = f"https://ground-zerro.github.io/release/keenetic/{arch.entware_arch}"
        ensure_src(app.sh, "ground_zerro", url, "ground-zerro.conf")
        # install packages
        return app.run_long_job("Install HydraRoute", job=lambda: self.opkg.install("hrneo hrweb"), back="c|hydra")

    def _install_nfqws2(self, app: "App", i18n: I18N) -> Screen:
        arch = detect_arch(app.sh)
        if arch.arch not in ("aarch64", "mipsel", "mips"):
            return Screen(text=i18n.t("err.not_supported"), kb=kb([[nav_back(i18n, "c|nfqws"), nav_home(i18n)]]))
        url = f"https://nfqws.github.io/nfqws2-keenetic/{arch.arch}"
        ensure_src(app.sh, "nfqws2_keenetic", url, "nfqws2.conf")
        return app.run_long_job("Install NFQWS2", job=lambda: self.opkg.install("nfqws2-keenetic"), back="c|nfqws")

    def _install_nfqwsweb(self, app: "App", i18n: I18N) -> Screen:
        url = "https://nfqws.github.io/nfqws-keenetic-web/all"
        ensure_src(app.sh, "nfqws_web", url, "nfqws-web.conf")

        def job():
            # try known package names
            r1 = self.opkg.install("nfqws-keenetic-web")
            if r1.ok:
                return r1
            r2 = self.opkg.install("nfqws-web")
            return r2

        return app.run_long_job("Install NFQWS web", job=job, back="c|nfqws")

    def _install_magi(self, app: "App", i18n: I18N) -> Screen:
        if self.hydra.is_installed():
            return Screen(text=i18n.t('magitrickle.ignored_by_hydra'), kb=kb([[nav_back(i18n, 'c|magi'), nav_home(i18n)]]))

        # Upstream provides an add_repo.sh helper.
        def job():
            app.sh.run("opkg update", timeout_sec=180, cache_ttl_sec=0)
            app.sh.run("curl -fsSL http://bin.magitrickle.dev/packages/add_repo.sh | sh", timeout_sec=120, cache_ttl_sec=0)
            app.sh.run("opkg update", timeout_sec=180, cache_ttl_sec=0)
            return self.opkg.install("magitrickle")

        return app.run_long_job("Install MagiTrickle", job=job, back="c|magi")

    def _install_awg(self, app: "App", i18n: I18N) -> Screen:
        arch = detect_arch(app.sh)
        if not arch.hoaxisr_arch:
            return Screen(text=i18n.t("err.not_supported"), kb=kb([[nav_back(i18n, "c|awg"), nav_home(i18n)]]))
        url = f"https://hoaxisr.github.io/entware-repo/{arch.hoaxisr_arch}"
        ensure_src(app.sh, "keenetic_custom", url, "hoaxisr-awg.conf")
        def job():
            r1 = self.opkg.install("awg-manager")
            if r1.ok:
                return r1
            return self.opkg.install("awgmanager")
        return app.run_long_job("Install AWG Manager", job=job, back="c|awg")
