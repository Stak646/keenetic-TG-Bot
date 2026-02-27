
from __future__ import annotations

from typing import Dict, List, Optional

from .base import ComponentBase
from ..ui import Screen, kb, btn, pager, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.text import paginate_lines, pre, esc
from ..drivers.router import RouterDriver, DhcpClient


class RouterComponent(ComponentBase):
    id = "r"
    emoji = "🛜"
    title_key = "home.router"

    def __init__(self, drv: RouterDriver):
        self.drv = drv

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n: I18N = app.i18n
        if cmd in ("m", ""):
            return self._menu(i18n)
        if cmd == "info":
            return self._info(i18n)
        if cmd == "routes":
            return self._routes(i18n, af="4", page=int(params.get("p", "1") or 1))
        if cmd == "routes6":
            return self._routes(i18n, af="6", page=int(params.get("p", "1") or 1))
        if cmd == "addr":
            return self._addr(i18n, page=int(params.get("p", "1") or 1))
        if cmd == "ipt":
            return self._iptables(i18n, af="4", page=int(params.get("p", "1") or 1))
        if cmd == "ipt6":
            return self._iptables(i18n, af="6", page=int(params.get("p", "1") or 1))
        if cmd == "clients":
            cat = params.get("c", "all")
            return self._clients_menu(i18n, app, cat=cat, page=int(params.get("p", "1") or 1))
        if cmd == "cli":
            mac = params.get("m", "").lower()
            return self._client_detail(i18n, app, mac)
        if cmd == "reboot_confirm":
            return self._reboot_confirm(i18n)
        if cmd == "reboot_do":
            ok = self.drv.reboot()
            text = i18n.t("router.reboot.sent") if ok else i18n.t("err.try_again")
            return Screen(text=f"{i18n.t('router.header')}\n\n{text}", kb=kb([[nav_home(i18n)]]))
        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _menu(self, i18n: I18N) -> Screen:
        rows = [
            [btn(i18n.t("router.info"), "r|info")],
            [btn(i18n.t("router.routes"), "r|routes"), btn("IPv6", "r|routes6")],
            [btn(i18n.t("router.addr"), "r|addr")],
            [btn(i18n.t("router.iptables"), "r|ipt"), btn("IPv6", "r|ipt6")],
            [btn(i18n.t("router.clients"), "r|clients")],
            [btn(i18n.t("router.reboot"), "r|reboot_confirm")],
            [nav_home(i18n)],
        ]
        text = f"{i18n.t('router.header')}\n\n{i18n.t('home.subtitle')}"
        return Screen(text=text, kb=kb(rows))

    def _info(self, i18n: I18N) -> Screen:
        info = self.drv.get_system_info()
        rows = [
            [btn(i18n.t("btn.refresh"), "r|info"), nav_back(i18n, "r|m")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('router.header')}\n\n{pre(info)}", kb=kb(rows))

    def _routes(self, i18n: I18N, af: str, page: int) -> Screen:
        v4, v6 = self.drv.ip_route()
        lines = v4 if af == "4" else v6
        pg = paginate_lines(lines or ["(empty)"], page=page)
        head = "IPv4" if af == "4" else "IPv6"
        base = "r|routes|" if af == "4" else "r|routes6|"
        rows = [
            pager(i18n, base=base, page=pg.page, pages=pg.pages),
            [btn(i18n.t("btn.refresh"), f"{base}p={pg.page}"), nav_back(i18n, "r|m")],
            [nav_home(i18n)],
        ]
        text = f"{i18n.t('router.header')}\n\n<b>{head} {i18n.t('router.routes')}</b>\n{pre(pg.text)}"
        return Screen(text=text, kb=kb(rows))

    def _addr(self, i18n: I18N, page: int) -> Screen:
        lines = self.drv.ip_addr()
        pg = paginate_lines(lines or ["(empty)"], page=page)
        base = "r|addr|"
        rows = [
            pager(i18n, base=base, page=pg.page, pages=pg.pages),
            [btn(i18n.t("btn.refresh"), f"{base}p={pg.page}"), nav_back(i18n, "r|m")],
            [nav_home(i18n)],
        ]
        text = f"{i18n.t('router.header')}\n\n<b>{i18n.t('router.addr')}</b>\n{pre(pg.text)}"
        return Screen(text=text, kb=kb(rows))

    def _iptables(self, i18n: I18N, af: str, page: int) -> Screen:
        v4, v6 = self.drv.iptables()
        lines = v4 if af == "4" else v6
        pg = paginate_lines(lines or ["(empty)"], page=page)
        head = "iptables" if af == "4" else "ip6tables"
        base = "r|ipt|" if af == "4" else "r|ipt6|"
        rows = [
            pager(i18n, base=base, page=pg.page, pages=pg.pages),
            [btn(i18n.t("btn.refresh"), f"{base}p={pg.page}"), nav_back(i18n, "r|m")],
            [nav_home(i18n)],
        ]
        text = f"{i18n.t('router.header')}\n\n<b>{head}</b>\n{pre(pg.text)}"
        return Screen(text=text, kb=kb(rows))

    def _clients_menu(self, i18n: I18N, app: "App", cat: str, page: int) -> Screen:
        clients = self.drv.dhcp_clients()
        wifi_macs = set(self.drv.wifi_station_macs())
        # categorize if wifi list available
        if wifi_macs:
            wifi = [c for c in clients if c.mac in wifi_macs]
            lan = [c for c in clients if c.mac not in wifi_macs]
        else:
            wifi = []
            lan = clients

        if cat == "wifi" and wifi_macs:
            view = wifi
        elif cat == "lan" and wifi_macs:
            view = lan
        else:
            view = clients
            cat = "all"

        # Build list lines and buttons
        # Pagination by clients count rather than text pages
        per_page = 8
        total_pages = max(1, (len(view) + per_page - 1) // per_page)
        p = max(1, min(page, total_pages))
        start = (p - 1) * per_page
        subset = view[start:start + per_page]

        rows: List[List[tuple[str, str]]] = []
        # Category row
        cat_row = [
            btn(i18n.t("router.clients.all"), "r|clients|c=all&p=1"),
        ]
        if wifi_macs:
            cat_row.append(btn(i18n.t("router.clients.lan"), "r|clients|c=lan&p=1"))
            cat_row.append(btn(i18n.t("router.clients.wifi"), "r|clients|c=wifi&p=1"))
        rows.append(cat_row)

        for c in subset:
            label = f"{c.ip} • {c.hostname or c.mac}"
            rows.append([btn(label, f"r|cli|m={c.mac}")])

        # Pager
        if total_pages > 1:
            base = f"r|clients|c={cat}&"
            rows.append(pager(i18n, base=base, page=p, pages=total_pages))
        rows.append([btn(i18n.t("btn.refresh"), f"r|clients|c={cat}&p={p}"), nav_back(i18n, "r|m")])
        rows.append([nav_home(i18n)])

        note = ""
        if not clients:
            note = "\n\n" + ("(не найден файл leases)" if i18n.lang == "ru" else "(leases file not found)")
        if cat == "wifi" and not wifi_macs:
            note = "\n\n" + ("Wi‑Fi классификация недоступна (нет iw)." if i18n.lang == "ru" else "Wi‑Fi classification unavailable (missing iw).")
        text = f"{i18n.t('router.header')}\n\n<b>{i18n.t('router.clients')}</b>\n" \
               f"• {len(clients)} total" + note
        return Screen(text=text, kb=kb(rows))

    def _client_detail(self, i18n: I18N, app: "App", mac: str) -> Screen:
        clients = self.drv.dhcp_clients()
        c = next((x for x in clients if x.mac.lower() == mac.lower()), None)
        if not c:
            return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_back(i18n, "r|clients"), nav_home(i18n)]]))
        lines = [
            f"IP: {c.ip}",
            f"MAC: {c.mac}",
            f"Host: {c.hostname}",
        ]
        if c.expires_at:
            lines.append(f"Expires: {c.expires_at}")
        if c.source:
            lines.append(f"Source: {c.source}")
        detail = pre("\n".join(lines))
        text = f"{i18n.t('router.header')}\n\n<b>{esc(c.ip)}</b>\n{detail}"
        rows = [
            [nav_back(i18n, "r|clients"), nav_home(i18n)],
        ]
        return Screen(text=text, kb=kb(rows))

    def _reboot_confirm(self, i18n: I18N) -> Screen:
        rows = [
            [btn(i18n.t("btn.yes"), "r|reboot_do"), btn(i18n.t("btn.no"), "r|m")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('router.header')}\n\n{esc(i18n.t('router.reboot.confirm'))}", kb=kb(rows))
