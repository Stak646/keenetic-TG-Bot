
from __future__ import annotations

from typing import Dict, List, Tuple

from .base import ComponentBase
from ..ui import Screen, kb, btn, nav_home, nav_back
from ..utils.i18n import I18N


class SettingsComponent(ComponentBase):
    id = "st"
    emoji = "⚙️"
    title_key = "home.settings"

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        i18n = app.i18n
        if cmd in ("m", ""):
            return self._menu(app, i18n)
        if cmd == "lang":
            rows: List[List[Tuple[str, str]]] = [
                [btn(i18n.t("settings.lang.ru"), "st|lang_set|v=ru"), btn(i18n.t("settings.lang.en"), "st|lang_set|v=en")],
                [nav_back(i18n, "st|m"), nav_home(i18n)],
            ]
            return Screen(text=f"{i18n.t('settings.header')}\n\n{i18n.t('settings.lang.current', lang=i18n.human_lang())}", kb=kb(rows))
        if cmd == "lang_set":
            v = params.get("v", "ru")
            app.set_language(v)
            i18n = app.i18n
            return self._menu(app, i18n)

        if cmd == "notify":
            app.cfg.notify_enabled = not app.cfg.notify_enabled
            app.save_cfg()
            return self._menu(app, app.i18n)

        if cmd == "debug":
            app.set_debug(not app.cfg.debug)
            return self._menu(app, app.i18n)

        return Screen(text=i18n.t("err.not_found"), kb=kb([[nav_home(i18n)]]))

    def _menu(self, app: "App", i18n: I18N) -> Screen:
        notify_label = i18n.t("settings.notify.on") if app.cfg.notify_enabled else i18n.t("settings.notify.off")
        debug_label = i18n.t("btn.debug_on") if app.cfg.debug else i18n.t("btn.debug_off")
        rows = [
            [btn(i18n.t("settings.lang"), "st|lang")],
            [btn(notify_label, "st|notify")],
            [btn(debug_label, "st|debug")],
            [nav_back(i18n, "h|m"), nav_home(i18n)],
        ]
        text = f"{i18n.t('settings.header')}\n\n" + i18n.t("settings.debug.tip")
        return Screen(text=text, kb=kb(rows))
