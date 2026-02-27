
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # Generic
        "app.title": "Keenetic TG Bot",
        "btn.home": "🏠 Home",
        "btn.back": "⬅️ Back",
        "btn.refresh": "🔄 Refresh",
        "btn.close": "✖️ Close",
        "btn.more": "➡️ More",
        "btn.prev": "⬅️ Prev",
        "btn.next": "➡️ Next",
        "btn.yes": "✅ Yes",
        "btn.no": "❌ No",
        "btn.install": "📦 Install",
        "btn.remove": "🗑 Remove",
        "btn.update": "⬆️ Update",
        "btn.start": "▶️ Start",
        "btn.stop": "⏹ Stop",
        "btn.restart": "🔁 Restart",
        "btn.details": "ℹ️ Details",
        "btn.raw": "🧾 Raw",
        "btn.logs": "🧾 Logs",
        "btn.clear": "🧹 Clear",
        "btn.settings": "⚙️ Settings",
        "btn.debug_on": "🐛 Debug: ON",
        "btn.debug_off": "🐛 Debug: OFF",

        # Home
        "home.header": "🏠 <b>Home</b>",
        "home.subtitle": "Choose a section:",
        "home.router": "🛜 Router",
        "home.components": "📦 Components",
        "home.opkg": "🧩 OPKG",
        "home.hydra": "🧬 HydraRoute",
        "home.nfqws": "🧱 NFQWS2",
        "home.awg": "🧷 AWG Manager",
        "home.speed": "🚀 Speed test",
        "home.settings": "⚙️ Settings",

        # Settings
        "settings.header": "⚙️ <b>Settings</b>",
        "settings.lang": "🌐 Language",
        "settings.notify": "🔔 Notifications",
        "settings.debug": "🐛 Debug",
        "settings.lang.current": "Current: {lang}",
        "settings.lang.ru": "Русский",
        "settings.lang.en": "English",
        "settings.notify.on": "Notifications: ON",
        "settings.notify.off": "Notifications: OFF",
        "settings.debug.tip": "Debug logs increase disk usage.",

        # Router
        "router.header": "🛜 <b>Router</b>",
        "router.info": "📋 System info",
        "router.routes": "🧭 Routes",
        "router.addr": "📡 IP addresses",
        "router.iptables": "🧱 Firewall (iptables)",
        "router.clients": "👥 DHCP clients",
        "router.reboot": "♻️ Reboot router",
        "router.reboot.confirm": "Are you sure you want to reboot the router?",
        "router.reboot.sent": "✅ Reboot command sent.",
        "router.clients.all": "All clients",
        "router.clients.lan": "LAN",
        "router.clients.wifi": "Wi‑Fi",

        # OPKG
        "opkg.header": "🧩 <b>OPKG</b>",
        "opkg.update_lists": "🔄 opkg update",
        "opkg.upgrade_all": "⬆️ opkg upgrade",
        "opkg.installed": "📦 Installed packages",
        "opkg.search": "🔎 Search package",
        "opkg.enter_query": "Send me a package name to search.",
        "opkg.done": "✅ Done.",
        "opkg.fail": "❌ OPKG error: {err}",

        # Components manager
        "comp.header": "📦 <b>Components</b>",
        "comp.subtitle": "Install / update / remove packages and services.",
        "comp.status.installed": "installed",
        "comp.status.missing": "missing",
        "comp.status.running": "running",
        "comp.status.stopped": "stopped",
        "comp.status.unknown": "unknown",

        # HydraRoute
        "hydra.header": "🧬 <b>HydraRoute</b>",
        "hydra.overview": "Overview",
        "hydra.webui": "Web UI",
        "hydra.diag": "Diagnostics",
        "hydra.not_installed": "HydraRoute is not installed.",

        # NFQWS2
        "nfqws.header": "🧱 <b>NFQWS2</b>",
        "nfqws.overview": "Overview",
        "nfqws.webui": "Web UI",
        "nfqws.not_installed": "NFQWS2 is not installed.",

        # AWG
        "awg.header": "🧷 <b>AWG Manager</b>",
        "awg.overview": "Overview",
        "awg.tunnels": "Tunnels",
        "awg.logs": "Logs",
        "awg.system": "System",
        "awg.speed": "Speed test",
        "awg.not_installed": "AWG Manager is not installed or API is unreachable.",
        "awg.pick_tunnel": "Pick a tunnel:",
        "awg.pick_server": "Pick a server:",
        "awg.action_done": "✅ Done.",

        # Speedtest
        "speed.header": "🚀 <b>Speed test</b>",
        "speed.generic": "🌍 Generic HTTP test",
        "speed.awg": "🧷 AWG speed test",
        "speed.install_speedtest_go": "📦 Install speedtest-go",
        "speed.not_available": "Speed test is not available on this device yet.",
        "speed.running": "⏳ Running speed test…",

        # Errors
        "err.no_access": "⛔ Access denied.",
        "err.try_again": "⚠️ Something went wrong. Try again.",
        "err.timeout": "⚠️ Timeout. Try again later.",
        "err.not_supported": "⚠️ Not supported on this firmware.",
        "err.not_found": "⚠️ Not found.",
        "err.bad_input": "⚠️ Bad input.",
        "err.net": "🌐 Network error: {err}",
    },
    "ru": {
        # Generic
        "app.title": "Keenetic TG Bot",
        "btn.home": "🏠 Домой",
        "btn.back": "⬅️ Назад",
        "btn.refresh": "🔄 Обновить",
        "btn.close": "✖️ Закрыть",
        "btn.more": "➡️ Подробнее",
        "btn.prev": "⬅️ Назад",
        "btn.next": "➡️ Далее",
        "btn.yes": "✅ Да",
        "btn.no": "❌ Нет",
        "btn.install": "📦 Установить",
        "btn.remove": "🗑 Удалить",
        "btn.update": "⬆️ Обновить",
        "btn.start": "▶️ Запуск",
        "btn.stop": "⏹ Стоп",
        "btn.restart": "🔁 Рестарт",
        "btn.details": "ℹ️ Детали",
        "btn.raw": "🧾 RAW",
        "btn.logs": "🧾 Логи",
        "btn.clear": "🧹 Очистить",
        "btn.settings": "⚙️ Настройки",
        "btn.debug_on": "🐛 Debug: ВКЛ",
        "btn.debug_off": "🐛 Debug: ВЫКЛ",

        # Home
        "home.header": "🏠 <b>Главное меню</b>",
        "home.subtitle": "Выберите раздел:",
        "home.router": "🛜 Роутер",
        "home.components": "📦 Компоненты",
        "home.opkg": "🧩 OPKG",
        "home.hydra": "🧬 HydraRoute",
        "home.nfqws": "🧱 NFQWS2",
        "home.awg": "🧷 AWG Manager",
        "home.speed": "🚀 Speed test",
        "home.settings": "⚙️ Настройки",

        # Settings
        "settings.header": "⚙️ <b>Настройки</b>",
        "settings.lang": "🌐 Язык",
        "settings.notify": "🔔 Уведомления",
        "settings.debug": "🐛 Debug",
        "settings.lang.current": "Текущий: {lang}",
        "settings.lang.ru": "Русский",
        "settings.lang.en": "English",
        "settings.notify.on": "Уведомления: ВКЛ",
        "settings.notify.off": "Уведомления: ВЫКЛ",
        "settings.debug.tip": "Debug увеличивает размер логов.",

        # Router
        "router.header": "🛜 <b>Роутер</b>",
        "router.info": "📋 Информация",
        "router.routes": "🧭 Маршруты",
        "router.addr": "📡 IP адреса",
        "router.iptables": "🧱 Фаервол (iptables)",
        "router.clients": "👥 DHCP клиенты",
        "router.reboot": "♻️ Перезагрузка роутера",
        "router.reboot.confirm": "Точно перезагрузить роутер?",
        "router.reboot.sent": "✅ Команда на перезагрузку отправлена.",
        "router.clients.all": "Все",
        "router.clients.lan": "LAN",
        "router.clients.wifi": "Wi‑Fi",

        # OPKG
        "opkg.header": "🧩 <b>OPKG</b>",
        "opkg.update_lists": "🔄 opkg update",
        "opkg.upgrade_all": "⬆️ opkg upgrade",
        "opkg.installed": "📦 Установленные пакеты",
        "opkg.search": "🔎 Поиск пакета",
        "opkg.enter_query": "Напишите название пакета для поиска.",
        "opkg.done": "✅ Готово.",
        "opkg.fail": "❌ Ошибка OPKG: {err}",

        # Components manager
        "comp.header": "📦 <b>Компоненты</b>",
        "comp.subtitle": "Установка / обновление / удаление пакетов и сервисов.",
        "comp.status.installed": "установлено",
        "comp.status.missing": "нет",
        "comp.status.running": "работает",
        "comp.status.stopped": "остановлено",
        "comp.status.unknown": "неизвестно",

        # HydraRoute
        "hydra.header": "🧬 <b>HydraRoute</b>",
        "hydra.overview": "Главная",
        "hydra.webui": "Web UI",
        "hydra.diag": "Диагностика",
        "hydra.not_installed": "HydraRoute не установлен.",

        # NFQWS2
        "nfqws.header": "🧱 <b>NFQWS2</b>",
        "nfqws.overview": "Главная",
        "nfqws.webui": "Web UI",
        "nfqws.not_installed": "NFQWS2 не установлен.",

        # AWG
        "awg.header": "🧷 <b>AWG Manager</b>",
        "awg.overview": "Главная",
        "awg.tunnels": "Туннели",
        "awg.logs": "Логи",
        "awg.system": "Система",
        "awg.speed": "Speed test",
        "awg.not_installed": "AWG Manager не установлен или API недоступно.",
        "awg.pick_tunnel": "Выберите туннель:",
        "awg.pick_server": "Выберите сервер:",
        "awg.action_done": "✅ Готово.",

        # Speedtest
        "speed.header": "🚀 <b>Speed test</b>",
        "speed.generic": "🌍 HTTP тест",
        "speed.awg": "🧷 AWG speed test",
        "speed.install_speedtest_go": "📦 Установить speedtest-go",
        "speed.not_available": "Speed test пока недоступен на этом устройстве.",
        "speed.running": "⏳ Запускаю speed test…",

        # Errors
        "err.no_access": "⛔ Доступ запрещён.",
        "err.try_again": "⚠️ Ошибка. Попробуйте ещё раз.",
        "err.timeout": "⚠️ Таймаут. Попробуйте позже.",
        "err.not_supported": "⚠️ Не поддерживается на этой прошивке.",
        "err.not_found": "⚠️ Не найдено.",
        "err.bad_input": "⚠️ Некорректный ввод.",
        "err.net": "🌐 Ошибка сети: {err}",
    },
}


@dataclass(frozen=True)
class I18N:
    lang: str = "ru"

    def t(self, key: str, **kwargs: Any) -> str:
        d = _TRANSLATIONS.get(self.lang) or _TRANSLATIONS["ru"]
        template = d.get(key) or _TRANSLATIONS["en"].get(key) or key
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def human_lang(self) -> str:
        return "Русский" if self.lang == "ru" else "English"
