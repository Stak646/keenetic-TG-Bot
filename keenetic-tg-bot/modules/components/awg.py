from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .base import ComponentBase
from ..drivers.awg import AwgApiResult, AwgDriver
from ..ui import Screen, btn, kb, nav_back, nav_home, pager
from ..utils.i18n import I18N
from ..utils.text import esc, pre, paginate_lines


def _fmt_bool(v: Any) -> str:
    return "✅" if bool(v) else "❌"


def _fmt_ts(s: str) -> str:
    if not s:
        return "-"
    try:
        # 2026-02-27T21:43:11Z
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(s)


def _mask_mac(mac: str) -> str:
    if not mac or ":" not in mac:
        return mac
    parts = mac.split(":")
    if len(parts) != 6:
        return mac
    return ":".join(parts[:2] + ["**", "**"] + parts[4:])


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
        ts, err = self.drv.tunnels()
        if err:
            return "api down"
        up = sum(1 for t in ts if t.running)
        return f"{up} up"

    # ---------------- main router

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n

        if cmd in ("m", ""):
            return self._overview(app, i18n)

        # --- tunnels
        if cmd == "tunnels":
            page = int(params.get("p", "1") or 1)
            return self._tunnels(app, i18n, page)

        if cmd == "tun":
            tid = params.get("id", "")
            return self._tunnel(app, i18n, tid)

        if cmd == "tun_act":
            tid = params.get("id", "")
            act = params.get("a", "")
            return app.run_long_job(
                f"AWG: {act}",
                job=lambda: self.drv.tunnel_action(tid, act),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_def":
            tid = params.get("id", "")
            return app.run_long_job(
                "AWG: toggle default route",
                job=lambda: self.drv.tunnel_toggle_default_route(tid),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_en":
            tid = params.get("id", "")
            val = params.get("v", "")
            enabled = val == "1"
            return app.run_long_job(
                "AWG: set enabled",
                job=lambda: self.drv.tunnel_update(tid, {"enabled": enabled}),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_rename":
            tid = params.get("id", "")
            app.session_set("awg_rename_tid", tid)
            app.set_pending_input(app.last_chat_id, "awg_rename")
            return Screen(
                text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.rename_prompt')}\n\n<b>{esc(tid)}</b>",
                kb=kb([[nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)]]),
            )

        if cmd == "tun_rename_do":
            tid = str(app.session_get("awg_rename_tid") or "")
            name = (params.get("text") or "").strip()[:64]
            if not tid or not name:
                return Screen(text=i18n.t("err.bad_input"), kb=kb([[nav_back(i18n, "aw|tunnels"), nav_home(i18n)]]))
            return app.run_long_job(
                "AWG: rename",
                job=lambda: self.drv.tunnel_update(tid, {"name": name}),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_wan":
            tid = params.get("id", "")
            return self._tun_pick_wan(app, i18n, tid)

        if cmd == "tun_wan_set":
            tid = params.get("id", "")
            name = params.get("n", "")  # empty means auto
            m = app.session_get("awg_wan_map", {})
            label = ""
            if isinstance(m, dict) and name in m:
                label = str(m.get(name) or "")
            patch: Dict[str, Any] = {"ispInterface": name, "ispInterfaceLabel": label}
            return app.run_long_job(
                "AWG: set WAN",
                job=lambda: self.drv.tunnel_update(tid, patch),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_ip":
            tid = params.get("id", "")
            return app.run_long_job(
                "AWG: test IP",
                job=lambda: self.drv.test_ip(tid),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_conn":
            tid = params.get("id", "")
            return app.run_long_job(
                "AWG: connectivity",
                job=lambda: self.drv.test_connectivity(tid),
                back=f"aw|tun|id={tid}",
            )

        if cmd == "tun_traffic":
            tid = params.get("id", "")
            period = params.get("p", "24h")
            return self._traffic(app, i18n, tid, period)

        if cmd == "tun_adv":
            tid = params.get("id", "")
            return self._tunnel_advanced(app, i18n, tid)

        # --- routing & policies
        if cmd == "routing":
            return self._routing(app, i18n)

        if cmd == "policies":
            return self._policies(app, i18n)

        if cmd == "pol_new":
            return self._policy_pick_client(app, i18n)

        if cmd == "pol_new_client":
            ip = params.get("ip", "")
            mac = params.get("mac", "")
            app.session_set("awg_pol_client_ip", ip)
            app.session_set("awg_pol_client_mac", mac)
            return self._policy_pick_tunnel(app, i18n)

        if cmd == "pol_new_tun":
            tid = params.get("id", "")
            app.session_set("awg_pol_tunnel_id", tid)
            app.set_pending_input(app.last_chat_id, "awg_policy_name")
            return Screen(
                text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.policy_name_prompt')}",
                kb=kb([[nav_back(i18n, "aw|pol_new"), nav_home(i18n)]]),
            )

        if cmd == "pol_new_do":
            name = (params.get("text") or "").strip()[:64]
            ip = str(app.session_get("awg_pol_client_ip") or "")
            mac = str(app.session_get("awg_pol_client_mac") or "")
            tid = str(app.session_get("awg_pol_tunnel_id") or "")
            if not ip or not tid:
                return Screen(text=i18n.t("err.bad_input"), kb=kb([[nav_back(i18n, "aw|policies"), nav_home(i18n)]]))
            payload = {
                "name": name or f"{ip} → {tid}",
                "clientIp": ip,
                "clientMac": mac,
                "tunnelId": tid,
            }
            return app.run_long_job(
                "AWG: create policy",
                job=lambda: self.drv.policy_create(payload),
                back="aw|policies",
            )

        if cmd == "pol_del":
            pid = params.get("id", "")
            return self._confirm(
                app,
                i18n,
                title=i18n.t("awg.confirm.title"),
                text=i18n.t("awg.confirm.delete_policy"),
                yes=f"aw|pol_del_do|id={pid}",
                no="aw|policies",
            )

        if cmd == "pol_del_do":
            pid = params.get("id", "")
            return app.run_long_job(
                "AWG: delete policy",
                job=lambda: self.drv.policy_delete(pid),
                back="aw|policies",
            )


        if cmd == "pol_view":
            pid = params.get("id", "")
            return self._policy_view(app, i18n, pid)

        if cmd == "pol_ren":
            pid = params.get("id", "")
            app.session_set("awg_pol_rename_id", pid)
            app.set_pending_input(app.last_chat_id, "awg_policy_rename")
            return Screen(
                text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.policy_name_prompt')}\n\n<b>{esc(pid)}</b>",
                kb=kb([[nav_back(i18n, f"aw|pol_view|id={pid}"), nav_home(i18n)]]),
            )

        if cmd == "pol_ren_do":
            pid = str(app.session_get("awg_pol_rename_id") or "")
            name = (params.get("text") or "").strip()[:64]
            if not pid or not name:
                return Screen(text=i18n.t("err.bad_input"), kb=kb([[nav_back(i18n, "aw|policies"), nav_home(i18n)]]))

            def job():
                pol = self._get_policy_by_id(pid)
                if not pol:
                    return AwgApiResult(ok=False, status=0, data=None, err="policy not found")
                pol = dict(pol)
                pol["name"] = name
                return self.drv.policy_update(pol)

            return app.run_long_job(
                "AWG: update policy",
                job=job,
                back=f"aw|pol_view|id={pid}",
            )

        # --- monitoring
        if cmd == "mon":
            return self._monitoring(app, i18n)

        if cmd == "mon_toggle":
            v = params.get("v", "0")
            enabled = v == "1"
            return app.run_long_job(
                "AWG: pingcheck",
                job=lambda: self.drv.settings_update({"pingCheck": {"enabled": enabled}}),
                back="aw|mon",
            )

        if cmd == "mon_check":
            return app.run_long_job(
                "AWG: pingcheck now",
                job=lambda: self.drv.pingcheck_check_now(),
                back="aw|mon",
            )

        if cmd == "mon_logs":
            page = int(params.get("p", "1") or 1)
            return self._mon_logs(app, i18n, page)

        if cmd == "mon_logs_clear":
            return app.run_long_job(
                "AWG: clear pingcheck logs",
                job=lambda: self.drv.pingcheck_logs_clear(),
                back="aw|mon",
            )

        # --- logs
        if cmd == "logs":
            page = int(params.get("p", "1") or 1)
            level = params.get("lvl", "")
            category = params.get("cat", "")
            return self._logs(app, i18n, page=page, level=level, category=category)

        if cmd == "logs_clear":
            return app.run_long_job("AWG: clear logs", job=lambda: self.drv.logs_clear(), back="aw|logs")

        # --- diagnostics
        if cmd == "diag":
            return self._diagnostics(app, i18n)

        if cmd == "diag_run":
            mode = params.get("m", "quick")
            # quick/full in UI may restart tunnels; keep it here but warn in text
            return app.run_long_job(
                f"AWG: diagnostics ({mode})",
                job=lambda: self.drv.diagnostics_run(mode=mode, restart=(mode == "full")),
                back="aw|diag",
            )

        if cmd == "diag_report":
            chat_id = int(app.last_chat_id)

            def job():
                ok, filename, data, ctype = self.drv.diagnostics_result()
                if not ok:
                    raise RuntimeError(filename)
                # send document
                app.bot.send_document(chat_id, (filename, data, ctype))
                return AwgApiResult(ok=True, status=200, data=f"sent: {filename}")

            return app.run_long_job("AWG: diagnostics report", job=job, back="aw|diag")

        # --- settings
        if cmd == "settings":
            return self._settings(app, i18n)

        if cmd == "settings_toggle":
            key = params.get("k", "")
            v = params.get("v", "0")
            enabled = v == "1"
            patch: Dict[str, Any] = {}
            if key == "logging":
                patch = {"logging": {"enabled": enabled}}
            elif key == "updates":
                patch = {"updates": {"checkEnabled": enabled}}
            elif key == "auth":
                # advanced
                patch = {"authEnabled": enabled}
            else:
                return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_back(i18n, "aw|settings"), nav_home(i18n)]]))
            return app.run_long_job("AWG: settings", job=lambda: self.drv.settings_update(patch), back="aw|settings")

        # --- system
        if cmd == "system":
            return self._system(app, i18n)

        if cmd == "hotspot":
            page = int(params.get("p", "1") or 1)
            return self._hotspot(app, i18n, page)

        if cmd == "update_check":
            force = params.get("f", "0") == "1"
            return app.run_long_job("AWG: update check", job=lambda: self.drv.system_update_check(force=force), back="aw|system")

        # --- speed test
        if cmd == "speed":
            return self._speed_pick_tunnel(app, i18n)

        if cmd == "speed_tun":
            tid = params.get("id", "")
            return self._speed_pick_server(app, i18n, tid)

        if cmd == "speed_srv":
            tid = params.get("id", "")
            idx = int(params.get("i", "0") or 0)
            return self._speed_pick_dir(app, i18n, tid, idx)

        if cmd == "speed_run":
            tid = params.get("id", "")
            idx = int(params.get("i", "0") or 0)
            direction = params.get("d", "download")
            servers = app.session_get("awg_speed_servers", [])
            host = ""
            port = 0
            label = ""
            if isinstance(servers, list) and 0 <= idx < len(servers):
                s = servers[idx]
                if isinstance(s, dict):
                    host = str(s.get("host") or s.get("server") or "")
                    port = int(s.get("port") or 0)
                    label = str(s.get("label") or host)
            if not host:
                return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_back(i18n, "aw|speed"), nav_home(i18n)]]))

            return app.run_long_job(
                f"AWG: speed {direction} ({label})",
                job=lambda: self.drv.speed_test(tid, host, port or 5201, direction),
                back=f"aw|tun|id={tid}",
            )

        # --- restart service
        if cmd == "restart":
            return app.run_long_job(
                "AWG: restart service",
                job=lambda: app.sh.run(
                    "sh $(ls /opt/etc/init.d/S??awg-manager 2>/dev/null | head -n1) restart 2>/dev/null || true",
                    timeout_sec=30,
                    cache_ttl_sec=0,
                ),
                back="aw|m",
            )

        # --- advanced
        if cmd == "adv":
            return self._advanced(app, i18n)

        if cmd == "adv_raw":
            tid = params.get("id", "")
            return self._tunnel_raw(app, i18n, tid)

        if cmd == "adv_del":
            tid = params.get("id", "")
            return self._confirm(
                app,
                i18n,
                title=i18n.t("awg.confirm.title"),
                text=i18n.t("awg.confirm.delete_tunnel").format(id=esc(tid)),
                yes=f"aw|adv_del_do|id={tid}",
                no=f"aw|tun|id={tid}",
            )

        if cmd == "adv_del_do":
            tid = params.get("id", "")
            return app.run_long_job(
                "AWG: delete tunnel",
                job=lambda: self.drv.tunnel_delete(tid),
                back="aw|tunnels",
            )

        if cmd == "adv_import":
            app.set_pending_input(app.last_chat_id, "awg_import")
            return Screen(
                text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.import_prompt')}",
                kb=kb([[nav_back(i18n, "aw|adv"), nav_home(i18n)]]),
            )

        if cmd == "adv_import_do":
            content = (params.get("text") or "").strip()
            if not content:
                return Screen(text=i18n.t("err.bad_input"), kb=kb([[nav_back(i18n, "aw|adv"), nav_home(i18n)]]))
            return app.run_long_job(
                "AWG: import config",
                job=lambda: self.drv.import_conf(content, name="telegram-import"),
                back="aw|tunnels",
            )

        if cmd == "adv_update_apply":
            return self._confirm(
                app,
                i18n,
                title=i18n.t("awg.confirm.title"),
                text=i18n.t("awg.confirm.apply_update"),
                yes="aw|adv_update_apply_do",
                no="aw|system",
            )

        if cmd == "adv_update_apply_do":
            return app.run_long_job("AWG: apply update", job=lambda: self.drv.system_update_apply(), back="aw|system")

        if cmd == "adv_kmod":
            return self._kmod(app, i18n)

        if cmd == "adv_kmod_dl":
            return app.run_long_job("AWG: kmod download", job=lambda: self.drv.kmod_download(), back="aw|adv_kmod")

        if cmd == "adv_kmod_swap":
            ver = params.get("v", "")
            return self._confirm(
                app,
                i18n,
                title=i18n.t("awg.confirm.title"),
                text=i18n.t("awg.confirm.kmod_swap").format(v=esc(ver)),
                yes=f"aw|adv_kmod_swap_do|v={ver}",
                no="aw|adv_kmod",
            )

        if cmd == "adv_kmod_swap_do":
            ver = params.get("v", "")
            return app.run_long_job("AWG: kmod swap", job=lambda: self.drv.kmod_swap(ver), back="aw|adv_kmod")

        if cmd == "adv_backend":
            return self._backend(app, i18n)

        if cmd == "adv_backend_do":
            mode = params.get("m", "")
            return self._confirm(
                app,
                i18n,
                title=i18n.t("awg.confirm.title"),
                text=i18n.t("awg.confirm.backend").format(m=esc(mode)),
                yes=f"aw|adv_backend_apply|m={mode}",
                no="aw|adv_backend",
            )

        if cmd == "adv_backend_apply":
            mode = params.get("m", "")
            return app.run_long_job("AWG: change backend", job=lambda: self.drv.system_change_backend(mode), back="aw|adv")

        if cmd == "adv_auth":
            return self._confirm(
                app,
                i18n,
                title=i18n.t("awg.confirm.title"),
                text=i18n.t("awg.confirm.auth_toggle"),
                yes="aw|adv_auth_do",
                no="aw|adv",
            )

        if cmd == "adv_auth_do":
            # toggle current
            s = self.drv.settings_get()
            if not s.ok or not isinstance(s.data, dict):
                return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(s.err)}", kb=kb([[nav_back(i18n, "aw|adv"), nav_home(i18n)]]))
            cur = bool(s.data.get("authEnabled"))
            return app.run_long_job("AWG: auth toggle", job=lambda: self.drv.settings_update({"authEnabled": (not cur)}), back="aw|adv")

        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    # ---------------- screens

    def _overview(self, app: "App", i18n: I18N) -> Screen:
        if not self.drv.detect():
            return Screen(text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.not_installed')}", kb=kb([[nav_home(i18n)]]))

        ver = self.drv.version()
        boot = self.drv.boot_status()
        tunnels, terr = self.drv.tunnels(raw=True)
        up = 0
        if isinstance(tunnels, list):
            up = sum(1 for t in tunnels if isinstance(t, dict) and str(t.get("status")) == "running")
        total = len(tunnels) if isinstance(tunnels, list) else 0

        lines: List[str] = []
        if ver.ok:
            lines.append(f"version: {ver.data}")
        if boot.ok and isinstance(boot.data, dict):
            lines.append(f"boot: {boot.data.get('phase')} (init={boot.data.get('initializing')})")
        lines.append(f"tunnels: {up}/{total} running")
        if terr:
            lines.append(f"tunnels err: {terr}")

        text = f"{i18n.t('awg.header')}\n\n{pre(chr(10).join(lines))}"

        rows = [
            [btn(i18n.t("awg.tunnels"), "aw|tunnels"), btn(i18n.t("awg.routing"), "aw|routing")],
            [btn(i18n.t("awg.monitoring"), "aw|mon"), btn(i18n.t("awg.logs"), "aw|logs")],
            [btn(i18n.t("awg.diagnostics"), "aw|diag"), btn(i18n.t("awg.settings"), "aw|settings")],
            [btn(i18n.t("awg.system"), "aw|system"), btn(i18n.t("awg.speed"), "aw|speed")],
            [btn(i18n.t("awg.advanced"), "aw|adv"), btn(i18n.t("btn.restart"), "aw|restart")],
            [nav_back(i18n, "h|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _tunnels(self, app: "App", i18n: I18N, page: int) -> Screen:
        tunnels, err = self.drv.tunnels(raw=True)
        if err:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))
        if not isinstance(tunnels, list):
            tunnels = []

        per = 8
        pages = max(1, (len(tunnels) + per - 1) // per)
        p = max(1, min(page, pages))
        subset = tunnels[(p - 1) * per : (p - 1) * per + per]

        rows: List[List[Tuple[str, str]]] = []
        for t in subset:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or "")
            name = str(t.get("name") or tid)
            running = str(t.get("status")) == "running"
            enabled = bool(t.get("enabled"))
            label = f"{'✅' if running else '⛔'} {'🟢' if enabled else '⚪'} {name}"
            rows.append([btn(label, f"aw|tun|id={tid}")])

        if pages > 1:
            rows.append(pager(i18n, base="aw|tunnels|", page=p, pages=pages))

        rows.append([btn(i18n.t("btn.refresh"), f"aw|tunnels|p={p}"), nav_back(i18n, "aw|m")])
        rows.append([nav_home(i18n)])

        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.tunnels')}</b> ({len(tunnels)})"
        return Screen(text=text, kb=kb(rows))

    def _tunnel(self, app: "App", i18n: I18N, tid: str) -> Screen:
        res = self.drv.tunnel_get(tid)
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|tunnels"), nav_home(i18n)]]))

        data = res.data if isinstance(res.data, dict) else {}
        safe = self.drv.sanitize_tunnel(data, include_secrets=False)

        # build detail text
        name = str(data.get("name") or tid)
        enabled = bool(data.get("enabled"))
        default = bool(data.get("defaultRoute"))
        iface = str(data.get("interfaceName") or "")
        endpoint = str((data.get("peer") or {}).get("endpoint") or data.get("endpoint") or "")
        addr = str((data.get("interface") or {}).get("address") or data.get("address") or "")
        isp = str(data.get("ispInterface") or data.get("resolvedIspInterface") or "")
        isp_lbl = str(data.get("ispInterfaceLabel") or data.get("resolvedIspInterfaceLabel") or "")

        state_info = data.get("stateInfo") if isinstance(data.get("stateInfo"), dict) else {}
        hs = str(state_info.get("lastHandshake") or "")
        rx = state_info.get("rxBytes")
        tx = state_info.get("txBytes")
        backend = str(state_info.get("backendType") or data.get("backendType") or "")

        lines = [
            f"id: {tid}",
            f"enabled: {enabled}",
            f"defaultRoute: {default}",
            f"iface: {iface}",
            f"address: {addr}",
            f"endpoint: {endpoint}",
            f"wan: {isp} ({isp_lbl})" if isp or isp_lbl else "wan: auto",
        ]
        if hs:
            lines.append(f"lastHandshake: {hs}")
        if rx is not None and tx is not None:
            lines.append(f"rx/tx: {rx}/{tx}")
        if backend:
            lines.append(f"backend: {backend}")

        text = f"{i18n.t('awg.header')}\n\n<b>{esc(name)}</b>\n{pre(chr(10).join(lines))}"

        rows: List[List[Tuple[str, str]]] = [
            [btn(i18n.t("btn.start"), f"aw|tun_act|id={tid}&a=start"), btn(i18n.t("btn.stop"), f"aw|tun_act|id={tid}&a=stop"), btn(i18n.t("btn.restart"), f"aw|tun_act|id={tid}&a=restart")],
            [btn(i18n.t("awg.toggle_default"), f"aw|tun_def|id={tid}"), btn(i18n.t("awg.set_wan"), f"aw|tun_wan|id={tid}")],
            [btn(i18n.t("awg.test_ip"), f"aw|tun_ip|id={tid}"), btn(i18n.t("awg.test_conn"), f"aw|tun_conn|id={tid}")],
            [btn(i18n.t("awg.traffic"), f"aw|tun_traffic|id={tid}&p=24h"), btn(i18n.t("awg.rename"), f"aw|tun_rename|id={tid}")],
            [btn(i18n.t("awg.enable_on" if not enabled else "awg.enable_off"), f"aw|tun_en|id={tid}&v={'1' if not enabled else '0'}")],
            [btn(i18n.t("awg.speed"), f"aw|speed_tun|id={tid}")],
            [btn(i18n.t("awg.tunnel_advanced"), f"aw|tun_adv|id={tid}"), btn(i18n.t("awg.advanced"), "aw|adv")],
            [nav_back(i18n, "aw|tunnels"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _tunnel_advanced(self, app: "App", i18n: I18N, tid: str) -> Screen:
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.tunnel_advanced')}</b>\n{i18n.t('awg.advanced_tip')}"
        rows = [
            [btn(i18n.t("awg.adv_raw"), f"aw|adv_raw|id={tid}")],
            [btn(i18n.t("btn.remove"), f"aw|adv_del|id={tid}")],
            [nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _tun_pick_wan(self, app: "App", i18n: I18N, tid: str) -> Screen:
        res = self.drv.wan_interfaces()
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)]]))
        items = res.data if isinstance(res.data, list) else []

        # store mapping for later (callback must stay short)
        wan_map = {}
        for it in items:
            if isinstance(it, dict):
                n = str(it.get("name") or "")
                wan_map[n] = str(it.get("label") or n)
        app.session_set("awg_wan_map", wan_map)

        rows: List[List[Tuple[str, str]]] = []
        # auto option
        rows.append([btn(i18n.t("awg.wan_auto"), f"aw|tun_wan_set|id={tid}&n=")])
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "")
            label = str(it.get("label") or name)
            state = str(it.get("state") or "")
            rows.append([btn(f"{label} ({state})"[:60], f"aw|tun_wan_set|id={tid}&n={name}")])

        rows.append([nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)])
        return Screen(text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.pick_wan')}", kb=kb(rows))

    def _traffic(self, app: "App", i18n: I18N, tid: str, period: str) -> Screen:
        res = self.drv.traffic_history(tid, period)
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)]]))
        pts = res.data if isinstance(res.data, list) else []
        # show last 20 points
        lines: List[str] = []
        for p in pts[-20:]:
            if not isinstance(p, dict):
                continue
            t = int(p.get("t") or 0)
            rx = p.get("rx")
            tx = p.get("tx")
            lines.append(f"{t}: rx={rx} tx={tx}")
        if not lines:
            lines = ["(empty)"]
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.traffic')}</b> ({esc(period)})\n{pre(chr(10).join(lines))}"
        rows = [
            [btn("24h", f"aw|tun_traffic|id={tid}&p=24h"), btn("1h", f"aw|tun_traffic|id={tid}&p=1h"), btn("7d", f"aw|tun_traffic|id={tid}&p=7d")],
            [nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _routing(self, app: "App", i18n: I18N) -> Screen:
        tunnels, err = self.drv.tunnels(raw=True)
        if err:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))
        if not isinstance(tunnels, list):
            tunnels = []

        lines: List[str] = []
        for t in tunnels:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name") or t.get("id"))
            wan = str(t.get("resolvedIspInterfaceLabel") or t.get("resolvedIspInterface") or "auto")
            lines.append(f"{name}: {wan}")

        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.routing')}</b>\n{pre(chr(10).join(lines) or '(empty)')}"
        rows = [
            [btn(i18n.t("awg.wan_status"), "aw|system"), btn(i18n.t("awg.policies"), "aw|policies")],
            [nav_back(i18n, "aw|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _policies(self, app: "App", i18n: I18N) -> Screen:
        res = self.drv.policies_list()
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|routing"), nav_home(i18n)]]))
        items = res.data if isinstance(res.data, list) else []

        rows: List[List[Tuple[str, str]]] = []
        if not items:
            rows.append([btn(i18n.t("awg.policy_add"), "aw|pol_new")])
        else:
            for it in items[:12]:
                if not isinstance(it, dict):
                    continue
                pid = str(it.get("id") or it.get("name") or "")
                name = str(it.get("name") or pid)
                client = str(it.get("clientIp") or it.get("client") or "")
                tunnel = str(it.get("tunnelId") or it.get("tunnel") or "")
                rows.append([btn(f"{name} ({client} → {tunnel})", f"aw|pol_view|id={pid}")])
                rows.append([btn(i18n.t("btn.remove"), f"aw|pol_del|id={pid}")])
            rows.append([btn(i18n.t("awg.policy_add"), "aw|pol_new")])

        rows.append([nav_back(i18n, "aw|routing"), nav_home(i18n)])
        return Screen(text=f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.policies')}</b>", kb=kb(rows))


    def _get_policy_by_id(self, policy_id: str) -> Dict[str, Any] | None:
        res = self.drv.policies_list()
        if not res.ok or not isinstance(res.data, list):
            return None
        for it in res.data:
            if isinstance(it, dict) and str(it.get("id") or it.get("name") or "") == policy_id:
                return it
        return None

    def _policy_view(self, app: "App", i18n: I18N, pid: str) -> Screen:
        pol = self._get_policy_by_id(pid)
        if not pol:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{i18n.t('err.not_found')}", kb=kb([[nav_back(i18n, "aw|policies"), nav_home(i18n)]]))

        name = str(pol.get("name") or pid)
        client = str(pol.get("clientIp") or pol.get("client") or "")
        mac = str(pol.get("clientMac") or "")
        tunnel = str(pol.get("tunnelId") or pol.get("tunnel") or "")

        lines = [
            f"id: {pid}",
            f"name: {name}",
            f"client: {client}",
            f"mac: {_mask_mac(mac)}" if mac else "mac: -",
            f"tunnel: {tunnel}",
        ]
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.policies')}</b>\n{pre(chr(10).join(lines))}"

        rows = [
            [btn(i18n.t("awg.rename"), f"aw|pol_ren|id={pid}"), btn(i18n.t("btn.remove"), f"aw|pol_del|id={pid}")],
            [nav_back(i18n, "aw|policies"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _policy_pick_client(self, app: "App", i18n: I18N) -> Screen:
        res = self.drv.hotspot()
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|policies"), nav_home(i18n)]]))
        items = res.data if isinstance(res.data, list) else []

        rows: List[List[Tuple[str, str]]] = []
        for it in items[:12]:
            if not isinstance(it, dict):
                continue
            ip = str(it.get("ip") or "")
            mac = str(it.get("mac") or "")
            host = str(it.get("hostname") or "")
            online = bool(it.get("online"))
            label = f"{'🟢' if online else '⚪'} {ip} {host}".strip()
            rows.append([btn(label[:60], f"aw|pol_new_client|ip={ip}&mac={mac}")])

        rows.append([nav_back(i18n, "aw|policies"), nav_home(i18n)])
        return Screen(text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.pick_client')}", kb=kb(rows))

    def _policy_pick_tunnel(self, app: "App", i18n: I18N) -> Screen:
        tunnels, err = self.drv.tunnels()
        if err:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(err)}", kb=kb([[nav_back(i18n, "aw|pol_new"), nav_home(i18n)]]))
        rows: List[List[Tuple[str, str]]] = []
        for t in tunnels:
            rows.append([btn(f"{'✅' if t.running else '⛔'} {t.name}", f"aw|pol_new_tun|id={t.id}")])
        rows.append([nav_back(i18n, "aw|pol_new"), nav_home(i18n)])
        return Screen(text=f"{i18n.t('awg.header')}\n\n{i18n.t('awg.pick_tunnel')}", kb=kb(rows))

    def _monitoring(self, app: "App", i18n: I18N) -> Screen:
        s = self.drv.settings_get()
        st = self.drv.pingcheck_status()
        enabled = False
        if s.ok and isinstance(s.data, dict):
            enabled = bool(((s.data.get("pingCheck") or {}) if isinstance(s.data.get("pingCheck"), dict) else {}).get("enabled"))
        lines = [f"enabled: {enabled}"]
        if st.ok:
            lines.append(f"status: ok")
        else:
            lines.append(f"status: {st.err}")

        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.monitoring')}</b>\n{pre(chr(10).join(lines))}"
        rows = [
            [btn(i18n.t("awg.enable_on" if not enabled else "awg.enable_off"), f"aw|mon_toggle|v={'1' if not enabled else '0'}"), btn(i18n.t("awg.check_now"), "aw|mon_check")],
            [btn(i18n.t("awg.mon_logs"), "aw|mon_logs"), btn(i18n.t("btn.clear"), "aw|mon_logs_clear")],
            [nav_back(i18n, "aw|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _mon_logs(self, app: "App", i18n: I18N, page: int) -> Screen:
        res = self.drv.pingcheck_logs()
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|mon"), nav_home(i18n)]]))
        items = res.data if isinstance(res.data, list) else []
        lines = [json.dumps(x, ensure_ascii=False) for x in items]
        pg = paginate_lines(lines or ["(empty)"], page=page)
        rows = [
            pager(i18n, base="aw|mon_logs|", page=pg.page, pages=pg.pages),
            [nav_back(i18n, "aw|mon"), nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.mon_logs')}</b>\n{pre(pg.text)}", kb=kb(rows))

    def _logs(self, app: "App", i18n: I18N, page: int, level: str, category: str) -> Screen:
        res = self.drv.logs_filtered(level=level, category=category, limit=400)
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))
        data = res.data
        logs = []
        if isinstance(data, dict) and "logs" in data:
            logs = data.get("logs") or []
        elif isinstance(data, list):
            logs = data

        lines = [json.dumps(x, ensure_ascii=False) for x in logs]
        pg = paginate_lines(lines or ["(empty)"], page=page)

        rows = [
            [btn("all", "aw|logs"), btn("error", "aw|logs|lvl=error"), btn("info", "aw|logs|lvl=info")],
            pager(i18n, base=f"aw|logs|lvl={level}&cat={category}&", page=pg.page, pages=pg.pages),
            [btn(i18n.t("btn.clear"), "aw|logs_clear"), nav_back(i18n, "aw|m")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.logs')}</b>\n{pre(pg.text)}", kb=kb(rows))

    def _diagnostics(self, app: "App", i18n: I18N) -> Screen:
        st = self.drv.diagnostics_status()
        lines: List[str] = []
        if st.ok and isinstance(st.data, dict):
            lines.append(f"status: {st.data.get('status')}")
            if st.data.get("progress"):
                lines.append(f"progress: {st.data.get('progress')}")
        else:
            lines.append(f"status: {st.err}")

        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.diagnostics')}</b>\n{pre(chr(10).join(lines))}"
        rows = [
            [btn(i18n.t("awg.diag_quick"), "aw|diag_run|m=quick"), btn(i18n.t("awg.diag_full"), "aw|diag_run|m=full")],
            [btn(i18n.t("awg.diag_report"), "aw|diag_report")],
            [nav_back(i18n, "aw|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _settings(self, app: "App", i18n: I18N) -> Screen:
        res = self.drv.settings_get()
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))
        s = res.data if isinstance(res.data, dict) else {}

        auth = bool(s.get("authEnabled"))
        logging = bool(((s.get("logging") or {}) if isinstance(s.get("logging"), dict) else {}).get("enabled"))
        updates = bool(((s.get("updates") or {}) if isinstance(s.get("updates"), dict) else {}).get("checkEnabled"))
        ping = bool(((s.get("pingCheck") or {}) if isinstance(s.get("pingCheck"), dict) else {}).get("enabled"))

        lines = [
            f"authEnabled: {auth}",
            f"logging: {logging}",
            f"updates: {updates}",
            f"pingCheck: {ping}",
            f"backendMode: {s.get('backendMode')}",
            f"bootDelaySeconds: {s.get('bootDelaySeconds')}",
        ]

        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.settings')}</b>\n{pre(chr(10).join(lines))}"

        rows = [
            [btn(f"logging: {_fmt_bool(logging)}", f"aw|settings_toggle|k=logging&v={'0' if logging else '1'}"), btn(f"updates: {_fmt_bool(updates)}", f"aw|settings_toggle|k=updates&v={'0' if updates else '1'}")],
            [btn(i18n.t("awg.monitoring"), "aw|mon")],
            [btn(i18n.t("awg.advanced"), "aw|adv")],
            [nav_back(i18n, "aw|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _system(self, app: "App", i18n: I18N) -> Screen:
        info = self.drv.system_info()
        wan = self.drv.wan_status()
        lines: List[str] = []
        if info.ok and isinstance(info.data, dict):
            d = info.data
            lines.extend(
                [
                    f"version: {d.get('version')}",
                    f"keeneticOS: {d.get('keeneticOS')}",
                    f"backend: {d.get('activeBackend')}",
                    f"kmod: exists={d.get('kernelModuleExists')} loaded={d.get('kernelModuleLoaded')} model={d.get('kernelModuleModel')} ver={d.get('kernelModuleVersion')}",
                ]
            )
        if wan.ok and isinstance(wan.data, dict):
            lines.append(f"anyWANUp: {wan.data.get('anyWANUp')}")

        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.system')}</b>\n{pre(chr(10).join(lines))}"

        rows = [
            [btn(i18n.t("awg.update_check"), "aw|update_check"), btn(i18n.t("awg.update_check_force"), "aw|update_check|f=1")],
            [btn(i18n.t("awg.kmod"), "aw|adv_kmod"), btn(i18n.t("awg.hotspot"), "aw|hotspot")],
            [btn(i18n.t("awg.advanced"), "aw|adv")],
            [nav_back(i18n, "aw|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _hotspot(self, app: "App", i18n: I18N, page: int) -> Screen:
        res = self.drv.hotspot()
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|system"), nav_home(i18n)]]))
        items = res.data if isinstance(res.data, list) else []
        lines: List[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            ip = str(it.get("ip") or "")
            mac = _mask_mac(str(it.get("mac") or ""))
            host = str(it.get("hostname") or "")
            online = bool(it.get("online"))
            lines.append(f"{'🟢' if online else '⚪'} {ip} {mac} {host}")
        pg = paginate_lines(lines or ["(empty)"], page=page)
        rows = [
            pager(i18n, base="aw|hotspot|", page=pg.page, pages=pg.pages),
            [nav_back(i18n, "aw|system"), nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.hotspot')}</b>\n{pre(pg.text)}", kb=kb(rows))

    def _speed_pick_tunnel(self, app: "App", i18n: I18N) -> Screen:
        ts, err = self.drv.tunnels()
        if err:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(err)}", kb=kb([[nav_back(i18n, "aw|m"), nav_home(i18n)]]))

        rows: List[List[Tuple[str, str]]] = []
        for t in ts[:12]:
            rows.append([btn(f"{'✅' if t.running else '⛔'} {t.name}", f"aw|speed_tun|id={t.id}")])

        rows.append([nav_back(i18n, "aw|m"), nav_home(i18n)])
        return Screen(text=f"{i18n.t('speed.header')}\n\n{i18n.t('awg.pick_tunnel')}", kb=kb(rows))

    def _speed_pick_server(self, app: "App", i18n: I18N, tid: str) -> Screen:
        res = self.drv.speed_servers()
        if not res.ok:
            return Screen(text=f"{i18n.t('speed.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|speed"), nav_home(i18n)]]))
        d = res.data
        servers = []
        if isinstance(d, dict) and "servers" in d:
            servers = d.get("servers") or []
        elif isinstance(d, list):
            servers = d
        app.session_set("awg_speed_servers", servers)

        rows: List[List[Tuple[str, str]]] = []
        for i, s in enumerate(servers[:12]):
            if not isinstance(s, dict):
                continue
            label = str(s.get("label") or s.get("host") or f"server {i}")
            rows.append([btn(label[:60], f"aw|speed_srv|id={tid}&i={i}")])

        rows.append([nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)])
        return Screen(text=f"{i18n.t('speed.header')}\n\n{i18n.t('awg.pick_server')}", kb=kb(rows))

    def _speed_pick_dir(self, app: "App", i18n: I18N, tid: str, idx: int) -> Screen:
        rows = [
            [btn("⬇️ download", f"aw|speed_run|id={tid}&i={idx}&d=download"), btn("⬆️ upload", f"aw|speed_run|id={tid}&i={idx}&d=upload")],
            [nav_back(i18n, f"aw|speed_tun|id={tid}"), nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('speed.header')}\n\n{i18n.t('awg.pick_direction')}", kb=kb(rows))

    def _advanced(self, app: "App", i18n: I18N) -> Screen:
        # advanced menu: dangerous operations
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.advanced')}</b>\n{i18n.t('awg.advanced_tip')}"
        rows = [
            [btn(i18n.t("awg.adv_import"), "aw|adv_import"), btn(i18n.t("awg.kmod"), "aw|adv_kmod")],
            [btn(i18n.t("awg.adv_backend"), "aw|adv_backend"), btn(i18n.t("awg.adv_auth"), "aw|adv_auth")],
            [btn(i18n.t("awg.adv_apply_update"), "aw|adv_update_apply")],
            [nav_back(i18n, "aw|m"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _tunnel_raw(self, app: "App", i18n: I18N, tid: str) -> Screen:
        res = self.drv.tunnel_get(tid)
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)]]))
        data = res.data if isinstance(res.data, dict) else {}
        cfg = str(data.get("configPreview") or "")
        if not cfg:
            cfg = json.dumps(data, ensure_ascii=False, indent=2)
        # WARNING: includes secrets
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.raw_warning')}</b>\n{pre(cfg[:3500])}"
        rows = [
            [btn(i18n.t("btn.more"), "noop")],
            [btn(i18n.t("btn.remove"), f"aw|adv_del|id={tid}")],
            [nav_back(i18n, f"aw|tun|id={tid}"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _kmod(self, app: "App", i18n: I18N) -> Screen:
        res = self.drv.kmod_versions()
        if not res.ok:
            return Screen(text=f"{i18n.t('awg.header')}\n\n{esc(res.err)}", kb=kb([[nav_back(i18n, "aw|adv"), nav_home(i18n)]]))
        d = res.data if isinstance(res.data, dict) else {}
        cur = str(d.get("current") or "")
        rec = str(d.get("recommended") or "")
        vers = d.get("versions") if isinstance(d.get("versions"), list) else []

        lines = [f"current: {cur}", f"recommended: {rec}", f"versions: {vers}"]
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.kmod')}</b>\n{pre(chr(10).join(lines))}"

        rows: List[List[Tuple[str, str]]] = []
        rows.append([btn(i18n.t("awg.kmod_download"), "aw|adv_kmod_dl")])
        for v in vers:
            rows.append([btn(f"swap → {v}", f"aw|adv_kmod_swap|v={v}")])
        rows.append([nav_back(i18n, "aw|adv"), nav_home(i18n)])
        return Screen(text=text, kb=kb(rows))

    def _backend(self, app: "App", i18n: I18N) -> Screen:
        text = f"{i18n.t('awg.header')}\n\n<b>{i18n.t('awg.adv_backend')}</b>\n{i18n.t('awg.backend_tip')}"
        rows = [
            [btn("auto", "aw|adv_backend_do|m=auto"), btn("kernel", "aw|adv_backend_do|m=kernel"), btn("userspace", "aw|adv_backend_do|m=userspace")],
            [nav_back(i18n, "aw|adv"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _confirm(self, app: "App", i18n: I18N, title: str, text: str, yes: str, no: str) -> Screen:
        msg = f"⚠️ <b>{esc(title)}</b>\n\n{esc(text)}"
        rows = [[btn(i18n.t("btn.yes"), yes), btn(i18n.t("btn.no"), no)], [nav_home(i18n)]]
        return Screen(text=msg, kb=kb(rows))
