
from __future__ import annotations

from typing import Dict, List

from .base import ComponentBase
from ..ui import Screen, kb, btn, pager, nav_home, nav_back
from ..utils.i18n import I18N
from ..utils.text import paginate_lines, pre
from ..drivers.opkg import OpkgDriver


class OpkgComponent(ComponentBase):
    id = "o"
    emoji = "🧩"
    title_key = "home.opkg"

    def __init__(self, drv: OpkgDriver):
        self.drv = drv

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._menu(i18n)
        if cmd == "list":
            page = int(params.get("p", "1") or 1)
            return self._list_installed(i18n, page=page)
        if cmd == "update":
            return app.run_long_job(
                title=i18n.t("opkg.update_lists"),
                job=lambda: self.drv.update(),
                back="o|m",
            )
        if cmd == "upgrade":
            return app.run_long_job(
                title=i18n.t("opkg.upgrade_all"),
                job=lambda: self.drv.upgrade(),
                back="o|m",
            )
        if cmd == "search":
            # set pending state for this chat
            app.set_pending_input(app.last_chat_id, "opkg_search")
            return Screen(
                text=f"{i18n.t('opkg.header')}\n\n{i18n.t('opkg.enter_query')}",
                kb=kb([[nav_back(i18n, "o|m"), nav_home(i18n)]]),
            )
        if cmd == "search_do":
            q = params.get("q", "")
            return self._search_results(i18n, q=q)
        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _menu(self, i18n: I18N) -> Screen:
        rows = [
            [btn(i18n.t("opkg.update_lists"), "o|update")],
            [btn(i18n.t("opkg.upgrade_all"), "o|upgrade")],
            [btn(i18n.t("opkg.installed"), "o|list")],
            [btn(i18n.t("opkg.search"), "o|search")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('opkg.header')}\n\n{i18n.t('home.subtitle')}", kb=kb(rows))

    def _list_installed(self, i18n: I18N, page: int) -> Screen:
        lines = self.drv.list_installed()
        pg = paginate_lines(lines or ["(empty)"], page=page)
        base = "o|list|"
        rows = [
            pager(i18n, base=base, page=pg.page, pages=pg.pages),
            [btn(i18n.t("btn.refresh"), f"{base}p={pg.page}"), nav_back(i18n, "o|m")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('opkg.header')}\n\n{pre(pg.text)}", kb=kb(rows))

    def _search_results(self, i18n: I18N, q: str) -> Screen:
        lines = self.drv.search(q)
        pg = paginate_lines(lines or ["(no results)"], page=1)
        rows = [
            [btn(i18n.t("opkg.search"), "o|search"), nav_back(i18n, "o|m")],
            [nav_home(i18n)],
        ]
        return Screen(text=f"{i18n.t('opkg.header')}\n\n<b>Search:</b> {q}\n{pre(pg.text)}", kb=kb(rows))
