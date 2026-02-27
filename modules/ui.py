# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass

from typing import List, Tuple, Optional

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from .utils import escape_html

# -----------------------------
# Меню / UI
# -----------------------------
def kb_row(*btns: Tuple[str, str]) -> List[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=t, callback_data=d) for t, d in btns]


def kb_home_back(home: str = "m:main", back: str = "m:main") -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🏠 Home", callback_data=home),
        InlineKeyboardButton("⬅️ Back", callback_data=back),
    )
    return kb


def kb_main(snapshot: Dict[str, str], caps: Dict[str, bool]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()

    # Router всегда доступен
    kb.row(
        InlineKeyboardButton(f"🧠 Роутер {snapshot.get('router', '')}", callback_data="m:router"),
    )

    # HydraRoute
    if caps.get("hydra"):
        kb.row(
            InlineKeyboardButton(f"🧬 HydraRoute {snapshot.get('hydra', '')}", callback_data="m:hydra"),
        )
    else:
        kb.row(
            InlineKeyboardButton("🧬 HydraRoute ➕ (не установлен)", callback_data="m:install"),
        )

    # NFQWS2
    if caps.get("nfqws2"):
        kb.row(
            InlineKeyboardButton(f"🧷 NFQWS2 {snapshot.get('nfqws', '')}", callback_data="m:nfqws"),
        )
    else:
        kb.row(
            InlineKeyboardButton("🧷 NFQWS2 ➕ (не установлен)", callback_data="m:install"),
        )

    # AWG
    if caps.get("awg"):
        kb.row(
            InlineKeyboardButton(f"🧿 AWG {snapshot.get('awg', '')}", callback_data="m:awg"),
        )
    else:
        kb.row(
            InlineKeyboardButton("🧿 AWG ➕ (не установлен)", callback_data="m:install"),
        )

    kb.row(
        InlineKeyboardButton("📦 OPKG", callback_data="m:opkg"),
        InlineKeyboardButton("📝 Логи", callback_data="m:logs"),
    )

    kb.row(
        InlineKeyboardButton("🛠 Диагностика", callback_data="m:diag"),
        InlineKeyboardButton("💾 Storage", callback_data="m:storage"),
    )

    # Установка/сервис (если что-то отсутствует)
    if (not caps.get("hydra")) or (not caps.get("nfqws2")) or (not caps.get("awg")) or (not caps.get("cron")):
        kb.row(InlineKeyboardButton("🧩 Установка/Сервис", callback_data="m:install"))

    kb.row(InlineKeyboardButton("⚙️ Настройки", callback_data="m:settings"))

    return kb



def kb_diag() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📡 Telegram (api.telegram.org)", callback_data="diag:tg"),
        InlineKeyboardButton("🧾 DNS", callback_data="diag:dns"),
    )
    kb.row(
        InlineKeyboardButton("🌐 Network quick", callback_data="diag:net"),
        InlineKeyboardButton("🐢 Slow cmds", callback_data="diag:slow"),
    )
    kb.row(
        InlineKeyboardButton("🧹 Очистить лог бота", callback_data="diag:clearlog?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="m:main"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_storage() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📊 Status", callback_data="storage:status"),
        InlineKeyboardButton("📁 Top dirs", callback_data="storage:top"),
    )
    kb.row(
        InlineKeyboardButton("🧹 Cleanup", callback_data="storage:cleanup?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="m:main"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_router() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="router:status"),
        InlineKeyboardButton("🌐 Интернет тест", callback_data="router:net"),
    )
    kb.row(
        InlineKeyboardButton("🌐 Network", callback_data="router:netmenu"),
        InlineKeyboardButton("👥 DHCP", callback_data="router:dhcpmenu"),
    )
    kb.row(
        InlineKeyboardButton("🧱 Firewall", callback_data="router:fwmenu"),
        InlineKeyboardButton("📤 Export config", callback_data="router:exportcfg"),
    )
    kb.row(
        InlineKeyboardButton("🔄 Reboot", callback_data="router:reboot?confirm=1"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb

def kb_router_net() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📡 ip addr", callback_data="router:ipaddr"),
        InlineKeyboardButton("🧭 ip route", callback_data="router:iproute"),
    )
    kb.row(
        InlineKeyboardButton("🌐 Интернет тест", callback_data="router:net"),
    )
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="m:router"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_router_fw() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("mangle summary", callback_data="router:fw:sum:mangle"),
        InlineKeyboardButton("mangle raw", callback_data="router:fw:raw:mangle"),
    )
    kb.row(
        InlineKeyboardButton("filter summary", callback_data="router:fw:sum:filter"),
        InlineKeyboardButton("filter raw", callback_data="router:fw:raw:filter"),
    )
    kb.row(
        InlineKeyboardButton("nat summary", callback_data="router:fw:sum:nat"),
        InlineKeyboardButton("nat raw", callback_data="router:fw:raw:nat"),
    )
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="m:router"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_router_dhcp_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("LAN", callback_data="router:dhcp:list:lan:0"),
        InlineKeyboardButton("WiFi", callback_data="router:dhcp:list:wifi:0"),
    )
    kb.row(
        InlineKeyboardButton("All (raw)", callback_data="router:dhcp"),
    )
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="m:router"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_router_dhcp_list(items: List[Dict[str, str]], kind: str, page: int, per_page: int = 10) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    total = len(items)
    if total == 0:
        kb.row(InlineKeyboardButton("⬅️ Back", callback_data="router:dhcpmenu"))
        kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
        return kb
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    end = min(total, start + per_page)
    for i in range(start, end):
        it = items[i]
        ip = it.get("ip","")
        name = it.get("name","") or it.get("mac","")
        label = f"{ip} · {name}" if ip else name
        kb.row(InlineKeyboardButton(label[:60], callback_data=f"router:dhcp:detail:{kind}:{i}:{page}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"router:dhcp:list:{kind}:{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"router:dhcp:list:{kind}:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.row(
        InlineKeyboardButton("⬅️ Back", callback_data="router:dhcpmenu"),
        InlineKeyboardButton("🏠 Home", callback_data="m:main"),
    )
    return kb


def kb_router_dhcp_detail(kind: str, page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("⬅️ Back", callback_data=f"router:dhcp:list:{kind}:{page}"))
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb




def kb_hydra(variant: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="hydra:status"),
        InlineKeyboardButton("🛠 Диагностика", callback_data="hydra:diag"),
    )
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data="hydra:start"),
        InlineKeyboardButton("⏹ Stop", callback_data="hydra:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data="hydra:restart"),
    )
    if variant == "neo":
        kb.row(
            InlineKeyboardButton("🌐 HRweb (2000)", callback_data="hydra:hrweb"),
        )
        kb.row(
            InlineKeyboardButton("📄 domain.conf", callback_data="hydra:file:domain.conf"),
            InlineKeyboardButton("📄 ip.list", callback_data="hydra:file:ip.list"),
        )
        kb.row(
            InlineKeyboardButton("⚙️ hrneo.conf", callback_data="hydra:file:hrneo.conf"),
        )
        kb.row(
            InlineKeyboardButton("📚 Правила", callback_data="hydra:rules"),
            InlineKeyboardButton("🔎 Поиск домена", callback_data="hydra:search_domain"),
        )
        kb.row(
            InlineKeyboardButton("🧩 Дубликаты", callback_data="hydra:dupes"),
            InlineKeyboardButton("⬆️ Импорт domain.conf", callback_data="hydra:import:domain.conf"),
        )
        kb.row(
            InlineKeyboardButton("➕ Add domain", callback_data="hydra:add_domain"),
            InlineKeyboardButton("➖ Remove domain", callback_data="hydra:rm_domain"),
        )
    kb.row(
        InlineKeyboardButton("⬆️ Обновить (opkg)", callback_data="hydra:update?confirm=1"),
        InlineKeyboardButton("🗑 Удалить", callback_data="hydra:remove?confirm=1"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_nfqws() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="nfqws:status"),
        InlineKeyboardButton("🛠 Диагностика", callback_data="nfqws:diag"),
    )
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data="nfqws:start"),
        InlineKeyboardButton("⏹ Stop", callback_data="nfqws:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data="nfqws:restart"),
        InlineKeyboardButton("♻️ Reload", callback_data="nfqws:reload"),
    )
    kb.row(
        InlineKeyboardButton("🌐 WebUI", callback_data="nfqws:web"),
        InlineKeyboardButton("📄 nfqws2.conf", callback_data="nfqws:file:nfqws2.conf"),
    )
    kb.row(
        InlineKeyboardButton("📚 Lists stats", callback_data="nfqws:lists"),
        InlineKeyboardButton("📄 user.list", callback_data="nfqws:filelist:user.list"),
        InlineKeyboardButton("📄 exclude.list", callback_data="nfqws:filelist:exclude.list"),
    )
    kb.row(
        InlineKeyboardButton("📄 auto.list", callback_data="nfqws:filelist:auto.list"),
        InlineKeyboardButton("⬆️ Импорт списка", callback_data="nfqws:import:list?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("➕ + user.list", callback_data="nfqws:add:user.list"),
        InlineKeyboardButton("🚫 + exclude.list", callback_data="nfqws:add:exclude.list"),
    )
    kb.row(
        InlineKeyboardButton("🧹 Clear auto.list", callback_data="nfqws:clear:auto.list?confirm=1"),
        InlineKeyboardButton("📜 Tail log", callback_data="nfqws:log"),
    )
    kb.row(
        InlineKeyboardButton("⬆️ Обновить (opkg)", callback_data="nfqws:update?confirm=1"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_awg() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧾 Статус", callback_data="awg:status"),
        InlineKeyboardButton("💓 Health", callback_data="awg:health"),
    )
    kb.row(
        InlineKeyboardButton("🧭 Туннели", callback_data="awg:api:tunnels"),
        InlineKeyboardButton("📊 Status all", callback_data="awg:api:statusall"),
    )
    kb.row(
        InlineKeyboardButton("🧾 API logs", callback_data="awg:api:logs"),
        InlineKeyboardButton("ℹ️ System/WAN", callback_data="awg:api:systeminfo"),
    )
    kb.row(
        InlineKeyboardButton("🧪 Diag run", callback_data="awg:api:diagr"),
        InlineKeyboardButton("🧪 Diag status", callback_data="awg:api:diags"),
    )
    kb.row(
        InlineKeyboardButton("⬆️ Update check", callback_data="awg:api:updatecheck"),
        InlineKeyboardButton("⬆️ Apply update", callback_data="awg:api:updateapply?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data="awg:start"),
        InlineKeyboardButton("⏹ Stop", callback_data="awg:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data="awg:restart"),
    )
    kb.row(
        InlineKeyboardButton("🌐 WebUI", callback_data="awg:web"),
        InlineKeyboardButton("🧵 wg show", callback_data="awg:wg"),
    )
    kb.row(InlineKeyboardButton("⬅️ Back", callback_data="m:main"))
    return kb

def kb_awg_tunnel(idx: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("▶️ Start", callback_data=f"awg:tunnelact:{idx}:start"),
        InlineKeyboardButton("⏹ Stop", callback_data=f"awg:tunnelact:{idx}:stop"),
        InlineKeyboardButton("🔄 Restart", callback_data=f"awg:tunnelact:{idx}:restart"),
    )
    kb.row(
        InlineKeyboardButton("✅ Enable/Disable", callback_data=f"awg:tunnelact:{idx}:toggle"),
        InlineKeyboardButton("🧭 Default route", callback_data=f"awg:tunnelact:{idx}:default"),
    )
    kb.row(
        InlineKeyboardButton("📋 Details", callback_data=f"awg:tunnel:{idx}"),
        InlineKeyboardButton("⬅️ Back", callback_data="awg:api:tunnels"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_opkg() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🔄 opkg update", callback_data="opkg:update"),
        InlineKeyboardButton("⬆️ list-upgradable", callback_data="opkg:upg"),
    )
    kb.row(
        InlineKeyboardButton("📦 версии пакетов", callback_data="opkg:versions"),
        InlineKeyboardButton("⬆️ upgrade TARGET", callback_data="opkg:upgrade?confirm=1"),
    )
    kb.row(
        InlineKeyboardButton("📃 list-installed (target)", callback_data="opkg:installed"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_logs() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📜 bot log", callback_data="logs:bot"),
        InlineKeyboardButton("📜 nfqws2.log", callback_data="logs:nfqws"),
    )
    kb.row(
        InlineKeyboardButton("📜 hrneo.log", callback_data="logs:hrneo"),
        InlineKeyboardButton("📜 dmesg", callback_data="logs:dmesg"),
    )
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_install(caps: Dict[str, bool]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    # Предлагаем то, чего нет
    if not caps.get("hydra"):
        kb.row(InlineKeyboardButton("➕ Установить HydraRoute Neo", callback_data="install:hydra?confirm=1"))
    if not caps.get("nfqws2"):
        kb.row(InlineKeyboardButton("➕ Установить NFQWS2", callback_data="install:nfqws2?confirm=1"))
    if caps.get("nfqws2") and (not caps.get("nfqws_web")):
        kb.row(InlineKeyboardButton("➕ Установить NFQWS web", callback_data="install:nfqwsweb?confirm=1"))
    if not caps.get("awg"):
        kb.row(InlineKeyboardButton("➕ Установить AWG Manager", callback_data="install:awg?confirm=1"))
    if not caps.get("cron"):
        kb.row(InlineKeyboardButton("➕ Установить cron", callback_data="install:cron?confirm=1"))

    kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))
    return kb


def kb_confirm(action_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Подтвердить", callback_data=action_cb),
        InlineKeyboardButton("❌ Отмена", callback_data=back_cb),
    )
    return kb


def kb_notice_actions(primary_cb: str = "m:main", restart_cb: str | None = None, logs_cb: str | None = None) -> InlineKeyboardMarkup:
    """Inline-кнопки для уведомлений: Меню / Restart / Логи."""
    kb = InlineKeyboardMarkup()
    row = [InlineKeyboardButton("🏠 Меню", callback_data=primary_cb)]
    if restart_cb:
        row.append(InlineKeyboardButton("🔄 Restart", callback_data=restart_cb))
    if logs_cb:
        row.append(InlineKeyboardButton("📝 Логи", callback_data=logs_cb))
    kb.row(*row)
    return kb


# -----------------------------
# Pending interactions
# -----------------------------
@dataclass
class Pending:
    kind: str
    data: Dict[str, Any]
    expires_at: float


class PendingStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[Tuple[int, int], Pending] = {}

    def set(self, chat_id: int, user_id: int, kind: str, data: Dict[str, Any], ttl_sec: int = 300) -> None:
        with self._lock:
            self._pending[(chat_id, user_id)] = Pending(kind=kind, data=data, expires_at=time.time() + ttl_sec)

    def pop(self, chat_id: int, user_id: int) -> Optional[Pending]:
        with self._lock:
            p = self._pending.pop((chat_id, user_id), None)
        if p and p.expires_at < time.time():
            return None
        return p

    def peek(self, chat_id: int, user_id: int) -> Optional[Pending]:
        with self._lock:
            p = self._pending.get((chat_id, user_id))
        if p and p.expires_at < time.time():
            return None
        return p


# -----------------------------
# Мониторинг / уведомления
# -----------------------------

