
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .base import ComponentBase
from ..ui import Screen, kb, btn, pager, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.text import paginate_lines, pre, esc
from ..drivers.awg import AwgDriver, AwgTunnel, AwgApiResult


class AwgComponent(ComponentBase):
    id = "aw"
    emoji = "🧷"
    title_key = "home.awg"

    def __init__(self, drv: AwgDriver):
        self.drv = drv

    def is_available(self) -> bool:
        return self.drv.detect()

    def quick_status(self):
        if not self.drv.detect():
            return None
        # best-effort: if tunnels list works -> running
        ts, err = self.drv.tunnels()
        if err:
            return "api down"
        up = sum(1 for t in ts if t.running)
        return f"{up} up"

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._overview(app, i18n)

        if cmd == "tunnels":
            page = int(params.get("p", "1") or 1)
            return self._tunnels(app, i18n, page)

        if cmd == "tun":
            tid = params.get("id", "")
            return self._tunnel_detail(app, i18n, tid)

        if cmd == "tun_act":
            tid = params.get("id", "")
            act = params.get("a", "")
            return app.run_long_job(
                f"AWG tunnel {act}",
                job=lambda: self.drv.tunnel_action(tid, act),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_toggle":
            tid = params.get("id", "")
            return app.run_long_job(
                "AWG toggle",
                job=lambda: self.drv.tunnel_toggle(tid),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "logs":
            page = int(params.get("p", "1") or 1)
            return self._logs(app, i18n, page=page)

        if cmd == "speed":
            # step 1: pick tunnel
            ts, err = self.drv.tunnels()
            if err:
                return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))
            # store tunnels in session
            app.session_set("awg_tunnels", [t.__dict__ for t in ts])
            rows: List[List[Tuple[str, str]]] = []
            for t in ts[:10]:
                rows.append([btn(f"{'✅' if t.running else '⛔'} {t.name}", f"aw|speed_tun|id={t.id}")])
            rows.append([nav_back(i18n, "aw|m"), nav_home(i18n)])
            text = f"{i18n.t('speed.header')}\n\n{i18n.t('awg.pick_tunnel')}"
            return Screen(text=text, kb=kb(rows))

        if cmd == "speed_tun":
            tid = params.get("id", "")
            # step 2: pick server
            servers = self.drv.speed_servers()
            if not servers.ok:
                return Screen(text=f"{i18n.t('speed.header')}\n\n{esc(servers.err)}", kb=kb([[nav_back(i18n, "aw|speed"), nav_home(i18n)]]))
            lst = servers.data
            if isinstance(lst, dict) and "servers" in lst:
                lst = lst["servers"]
            if not isinstance(lst, list):
                lst = []
            # store selection
            app.session_set("awg_speed_tunnel", tid)
            app.session_set("awg_speed_servers", lst)
            rows: List[List[Tuple[str, str]]] = []
            for idx, s in enumerate(lst[:10]):
                name = str(s.get("name") or s.get("host") or s.get("server") or f"server {idx+1}")
                rows.append([btn(name, f"aw|speed_srv|i={idx}")])
            rows.append([nav_back(i18n, "aw|speed"), nav_home(i18n)])
            return Screen(text=f"{i18n.t('speed.header')}\n\n{i18n.t('awg.pick_server')}", kb=kb(rows))

        if cmd == "speed_srv":
            # step 3: direction
            i = int(params.get("i", "0") or 0)
            rows = [
                [btn("⬇️ Download", f"aw|speed_run|i={i}&d=download"), btn("⬆️ Upload", f"aw|speed_run|i={i}&d=upload")],
                [nav_back(i18n, "aw|speed"), nav_home(i18n)],
            ]
            return Screen(text=f"{i18n.t('speed.header')}\n\nDirection:", kb=kb(rows))

        if cmd == "speed_run":
            i = int(params.get("i", "0") or 0)
            direction = params.get("d", "download")
            tid = app.session_get("awg_speed_tunnel") or ""
            servers = app.session_get("awg_speed_servers") or []
            server = ""
            port = 0
            if isinstance(servers, list) and 0 <= i < len(servers):
                s = servers[i]
                if isinstance(s, dict):
                    server = str(s.get("host") or s.get("server") or s.get("ip") or s.get("name") or "")
                    port = int(s.get("port") or 0)
            if not server:
                return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_back(i18n, "aw|speed"), nav_home(i18n)]]))
            if not port:
                port = 8080
            return app.run_long_job(
                i18n.t("speed.running"),
                job=lambda: self.drv.speed_test(tid, server, port, direction),
                back="aw|m",
            )

        if cmd == "restart":
            # restart service by init script if exists
            return app.run_long_job(
                "AWG restart",
                job=lambda: app.sh.run("sh /opt/etc/init.d/S80awg-manager restart 2>/dev/null || true", timeout_sec=30, cache_ttl_sec=0),
                back="aw|m",
            )

        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _overview(self, app: "App", i18n: I18N) -> Screen:
        if not self.drv.detect():
            return Screen(text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.not_installed')}", kb=kb([[nav_home(i18n)]]))
        ver = self.drv.version()
        ip = self.drv.public_ip()
        tunnels, terr = self.drv.tunnels()
        up = sum(1 for t in tunnels if t.running)
        total = len(tunnels)
        lines = []
        if ver.ok:
            lines.append(f"Version: {ver.data}")
        if ip.ok:
            lines.append(f"Public IP: {ip.data}")
        lines.append(f"Tunnels: {up}/{total} up")
        if terr:
            lines.append(f"tunnels err: {terr}")
        text = f"{i18n.t('awg.header')}\n\n{pre(chr(10).join(lines))}"
        rows = [
            [btn(i18n.t("awg.tunnels"), "aw|tunnels"), btn(i18n.t("awg.logs"), "aw|logs")],
            [btn(i18n.t("awg.speed"), "aw|speed")],
            [btn(i18n.t("btn.restart"), "aw|restart")],
            [nav_back(i18n, "h|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _tunnels(self, app: "App", i18n: I18N, page: int) -> Screen:
        tunnels, err = self.drv.tunnels()
        if err:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))
        per = 8
        pages = max(1, (len(tunnels) + per - 1) // per)
        p = max(1, min(page, pages))
        subset = tunnels[(p-1)*per:(p-1)*per+per]
        rows: List[List[Tuple[str, str]]] = []
        for t in subset:
            label = f"{'✅' if t.running else '⛔'} {'🟢' if t.enabled else '⚪'} {t.name}"
            rows.append([btn(label, f"aw|tun|id={t.id}")])
        if pages > 1:
            rows.append(pager(i18n, base="aw|tunnels|", page=p, pages=pages))
        rows.append([btn(i18n.t("btn.refresh"), f"aw|tunnels|p={p}"), nav_back(i18n, "aw|m")])
        rows.append([nav_home(i18n)])
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.tunnels')}</b> ({len(tunnels)})"
        return Screen(text=text, kb=kb(rows))

    def _tunnel_detail(self, app: "App", i18n: I18N, tid: str) -> Screen:
        tunnels, err = self.drv.tunnels()
        if err:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(err)}", kb=kb([[nav_back(i18n, "aw|tunnels"), nav_home(i18n)]]))
        t = next((x for x in tunnels if x.id == tid), None)
        if not t:
            return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_back(i18n, "aw|tunnels"), nav_home(i18n)]]))
        lines = [
            f"ID: {t.id}",
            f"Name: {t.name}",
            f"Enabled: {t.enabled}",
            f"Running: {t.running}",
        ]
        if t.ip:
            lines.append(f"IP: {t.ip}")
        if t.endpoint:
            lines.append(f"Endpoint: {t.endpoint}")
        text = f"{i18n.t('awg.header')}\n\n<b>{esc(t.name)}</b>\n{pre(chr(10).join(lines))}"
        rows = [
            [btn("▶️ start", f"aw|tun_act|id={t.id}&a=start"), btn("⏹ stop", f"aw|tun_act|id={t.id}&a=stop"), btn("🔁 restart", f"aw|tun_act|id={t.id}&a=restart")],
            [btn("🔀 toggle", f"aw|tun_toggle|id={t.id}"), btn("🚀 speed", f"aw|speed_tun|id={t.id}")],
            [nav_back(i18n, "aw|tunnels"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _logs(self, app: "App", i18n: I18N, page: int) -> Screen:
        res = self.drv.logs(limit=400)
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))
        data = res.data
        if isinstance(data, dict) and "logs" in data:
            text_lines = [str(x) for x in data.get("logs") or []]
        elif isinstance(data, list):
            text_lines = [str(x) for x in data]
        else:
            text_lines = str(data).splitlines()
        pg = paginate_lines(text_lines or ["(empty)"], page=page)
        rows = [
            pager(i18n, base="aw|logs|", page=pg.page, pages=pg.pages),
            [btn(i18n.t("btn.refresh"), f"aw|logs|p={pg.page}"), nav_back(i18n, "aw|m")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.logs')}</b>\n{pre(pg.text)}", kb=kb(rows))
