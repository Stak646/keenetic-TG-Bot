# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import urllib.request
import urllib.parse
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Any

import atexit
import telebot
import logging
from telebot import apihelper

# Telegram API tuning (router networks can be flaky)
apihelper.CONNECT_TIMEOUT = 10
apihelper.READ_TIMEOUT = 90
apihelper.SESSION_TIME_TO_LIVE = 5 * 60

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
    InputFile,
)

from .constants import *
from .utils import *
from .config import BotConfig, load_config_or_exit
from .shell import Shell
from .drivers import RouterDriver, HydraRouteDriver, NfqwsDriver, AwgDriver
from .ui import *
from .monitor import Monitor
from .storage import opt_status as storage_status, opt_top as storage_top, cleanup as storage_cleanup

class App:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.bot = telebot.TeleBot(cfg.bot_token, parse_mode="HTML", threaded=True)
        self.sh = Shell(timeout_sec=cfg.command_timeout_sec, debug_enabled=cfg.debug_enabled)
        self.sh.debug = cfg.debug_enabled
        self.sh.debug_output_max = cfg.debug_log_output_max
        self._cache: Dict[str, Tuple[float, Any]] = {}

        self.router = RouterDriver(self.sh)
        self.opkg = OpkgDriver(self.sh)
        self.hydra = HydraRouteDriver(self.sh, self.opkg, self.router)
        self.nfqws = NfqwsDriver(self.sh, self.opkg, self.router)
        self.awg = AwgDriver(self.sh, self.opkg, self.router)

        self._cache = {}
        self._cache_lock = threading.Lock()
        self.pending = PendingStore()
        self.awg_tunnel_cache: Dict[Tuple[int, int], Dict[str, Any]] = {}

        self.monitor: Optional[Monitor] = None
        if cfg.monitor_enabled:
            self.monitor = Monitor(self.bot, cfg, self.sh, self.router, self.opkg, self.hydra, self.nfqws, self.awg)

        self._register_handlers()

    # ---- ACL ----
    def is_admin(self, user_id: int) -> bool:
        return user_id in set(self.cfg.admins)

    def is_chat_allowed(self, chat_id: int, user_id: int) -> bool:
        if not self.is_admin(user_id):
            return False
        if not self.cfg.allow_chats:
            # разрешаем личку админам
            return chat_id == user_id
        return chat_id in set(self.cfg.allow_chats) or chat_id == user_id

    def _deny(self, chat_id: int) -> None:
        try:
            self.bot.send_message(chat_id, "⛔ Доступ запрещён.")
        except Exception:
            pass


    def _cached(self, key: str, ttl_sec: int, fn):
        now = time.time()
        with self._cache_lock:
            v = self._cache.get(key)
            if v and (now - v["ts"]) < ttl_sec:
                return v["val"]
        val = fn()
        with self._cache_lock:
            self._cache[key] = {"ts": now, "val": val}
        return val

    # ---- UI helpers ----
    def snapshot(self) -> Dict[str, str]:
        # короткий статус для главного меню
        snap = {}

        # router internet
        ok_net, _ = self._cached('snap:net', 10, lambda: self.router.internet_check())
        snap["router"] = "✅" if ok_net else "⚠️"

        # hydra
        if self.hydra.is_neo_available() or self.hydra.is_classic_available():
            up = False
            if self.hydra.is_neo_available():
                rc, _ = self.hydra.neo_cmd("status")
                up = (rc == 0)
            else:
                rc, _ = self.hydra.classic_cmd("status")
                up = (rc == 0)
            snap["hydra"] = "✅" if up else "⛔"
        else:
            snap["hydra"] = "➖"

        # nfqws
        if self.nfqws.installed():
            rc, _ = self.nfqws.init_action("status")
            snap["nfqws"] = "✅" if rc == 0 else "⛔"
        else:
            snap["nfqws"] = "➖"

        # awg
        if self.awg.installed():
            rc, _ = self.awg.init_action("status")
            snap["awg"] = "✅" if rc == 0 else "⛔"
        else:
            snap["awg"] = "➖"

        return snap


    def capabilities(self) -> Dict[str, bool]:
        """
        Определяем, что реально установлено/доступно на роутере.
        Используется для меню (скрывать/помечать отсутствующие модули).
        """
        caps: Dict[str, bool] = {}
        caps["opkg"] = which("opkg") is not None
        caps["ndmc"] = which("ndmc") is not None
        caps["iptables"] = which("iptables") is not None
        caps["ipset"] = which("ipset") is not None

        # Hydra variants
        caps["hydra_neo"] = self.hydra.is_neo_available()
        caps["hydra_classic"] = self.hydra.is_classic_available()
        caps["hydra"] = caps["hydra_neo"] or caps["hydra_classic"]

        vers = self._cached('snap:vers', 60, lambda: self.opkg.target_versions()) if caps["opkg"] else {}

        # HRweb: пакет или типичные файлы
        caps["hrweb"] = ("hrweb" in vers) or Path("/opt/share/hrweb").exists() or Path("/opt/etc/init.d/S50hrweb").exists()

        # NFQWS2 + web
        caps["nfqws2"] = self.nfqws.installed()
        caps["nfqws_web"] = ("nfqws-keenetic-web" in vers) or NFQWS_WEB_CONF.exists() or Path("/opt/share/nfqws-web").exists()

        # AWG manager
        caps["awg"] = self.awg.installed()

        # Cron (для автообновлений/планировщика)
        caps["cron"] = Path("/opt/etc/init.d/S10cron").exists()

        return caps


    def _awg_cache_set(self, chat_id: int, user_id: int, tunnels: List[dict], ttl_sec: int = 300) -> None:
        self.awg_tunnel_cache[(chat_id, user_id)] = {"expires": time.time() + ttl_sec, "tunnels": tunnels}

    def _awg_cache_get(self, chat_id: int, user_id: int) -> Optional[List[dict]]:
        v = self.awg_tunnel_cache.get((chat_id, user_id))
        if not v:
            return None
        if v.get("expires", 0) < time.time():
            self.awg_tunnel_cache.pop((chat_id, user_id), None)
            return None
        return v.get("tunnels")

    def send_or_edit(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        message_id: Optional[int] = None,
        disable_preview: bool = True,
    ) -> None:
        # Telegram limit 4096 for text; if too long - send as file
        if len(text) > 3900:
            # send as document
            tmp = Path("/tmp/tg-bot-output.txt")
            tmp.write_text(re.sub(r"<[^>]+>", "", text), encoding="utf-8", errors="replace")
            self.bot.send_document(chat_id, InputFile(str(tmp)), caption="Вывод слишком длинный, отправляю файлом.")
            return

        if message_id:
            try:
                self.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_preview,
                )
                return
            except Exception as e:
                # message is not modified / etc.
                log_line(f"edit_message_text error: {e}")

        self.bot.send_message(chat_id, text, reply_markup=reply_markup, disable_web_page_preview=disable_preview)

    # ---- Handlers ----
    def _register_handlers(self) -> None:
        @self.bot.message_handler(commands=["start", "menu"])
        def _start(m: Message) -> None:
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)
            text = self.render_main()
            self.send_or_edit(m.chat.id, text, reply_markup=kb_main(self.snapshot(), self.capabilities()))

        @self.bot.message_handler(commands=["diag"])
        def _cmd_diag(m: Message) -> None:
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)
            self.bot.send_message(m.chat.id, "🛠 <b>Диагностика</b>", reply_markup=kb_diag(), parse_mode="HTML")

        @self.bot.message_handler(commands=["diag_tg"])
        def _cmd_diag_tg(m: Message) -> None:
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)
            from modules.diag import telegram_connectivity
            self.bot.send_message(m.chat.id, "⏳ Проверяю Telegram…")
            out = telegram_connectivity(self.sh)
            self.bot.send_message(m.chat.id, f"📡 <b>Telegram connectivity</b>\n{fmt_code(out)}", parse_mode="HTML")



        @self.bot.message_handler(commands=["debug_on"])
        def _debug_on(m: Message) -> None:
            if m.from_user.id not in self.cfg.admins:
                return
            self.cfg.debug_enabled = True
            self.sh.debug = True
            self.sh.debug_output_max = self.cfg.debug_log_output_max
            self.bot.send_message(m.chat.id, "🐞 Debug: <b>ON</b>")

        @self.bot.message_handler(commands=["debug_off"])
        def _debug_off(m: Message) -> None:
            if m.from_user.id not in self.cfg.admins:
                return
            self.cfg.debug_enabled = False
            self.sh.debug = False
            self.bot.send_message(m.chat.id, "🐞 Debug: <b>OFF</b>")

        @self.bot.message_handler(commands=["help"])
        def _help(m: Message) -> None:
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)
            help_text = (
                "Команды:\n"
                "/menu — открыть меню\n"
                "/start — то же\n\n"
                "Все действия доступны через кнопки."
            )
            self.bot.send_message(m.chat.id, escape_html(help_text))

        @self.bot.callback_query_handler(func=lambda c: True)
        def _cb(cq: CallbackQuery) -> None:
            try:
                if not self.is_chat_allowed(cq.message.chat.id, cq.from_user.id):
                    return self._deny(cq.message.chat.id)

                data = cq.data or ""
                log_line(f"callback {cq.from_user.id}: {data}")

                # ack
                try:
                    self.bot.answer_callback_query(cq.id)
                except Exception:
                    pass

                self.handle_callback(cq)
            except Exception as e:
                log_line(f"callback error: {e}")
                try:
                    self.bot.send_message(cq.message.chat.id, f"⚠️ Ошибка: <code>{escape_html(str(e))}</code>")
                except Exception:
                    pass

        @self.bot.message_handler(content_types=["text", "document"])
        def _any(m: Message) -> None:
            # если ждём ввод — обрабатываем
            if not self.is_chat_allowed(m.chat.id, m.from_user.id):
                return self._deny(m.chat.id)

            p = self.pending.peek(m.chat.id, m.from_user.id)
            if not p:
                return  # игнорируем произвольные сообщения
            self.pending.pop(m.chat.id, m.from_user.id)

            try:
                if p.kind == "hydra_add_domain_text" and m.content_type == "text":
                    target = p.data["target"]
                    domains = re.split(r"[,\s]+", m.text.strip())
                    ok, msg = self.hydra.add_domain(domains, target)
                    self.bot.send_message(m.chat.id, ("✅ " if ok else "⚠️ ") + escape_html(msg))
                elif p.kind == "hydra_rm_domain_text" and m.content_type == "text":
                    domain = m.text.strip()
                    ok, msg = self.hydra.remove_domain(domain)
                    self.bot.send_message(m.chat.id, ("✅ " if ok else "⚠️ ") + escape_html(msg))

                elif p.kind == "hydra_search_domain_text" and m.content_type == "text":
                    q = m.text.strip()
                    res = self.hydra.find_domain(q)
                    self.bot.send_message(m.chat.id, "<b>Поиск domain.conf</b>\n<pre><code>" + escape_html(res) + "</code></pre>")
                elif p.kind == "hydra_import_domain_conf" and m.content_type == "document":
                    dest = HR_DOMAIN_CONF
                    self._handle_document_upload(m, dest)
                    if self.hydra.is_neo_available():
                        self.hydra.neo_cmd("restart")
                    self.bot.send_message(m.chat.id, "✅ domain.conf импортирован (с бэкапом). Neo перезапущен.")
                elif p.kind == "nfqws_import_list" and m.content_type == "document":
                    list_name = p.data.get("list_name", "user.list")
                    dest = NFQWS_LISTS_DIR / list_name
                    self._handle_document_upload(m, dest)
                    self.nfqws.init_action("reload")
                    self.bot.send_message(m.chat.id, f"✅ Импортирован список: <code>{escape_html(list_name)}</code> (с бэкапом). Выполнен reload.")
                elif p.kind == "nfqws_add_list_text" and m.content_type == "text":
                    list_name = p.data["list_name"]
                    domains = re.split(r"[,\s]+", m.text.strip())
                    ok, msg = self.nfqws.add_to_list(list_name, domains)
                    self.bot.send_message(m.chat.id, ("✅ " if ok else "⚠️ ") + escape_html(msg))
                elif p.kind == "file_upload" and m.content_type == "document":
                    dest = Path(p.data["dest"])
                    kind = p.data.get("kind", "file")
                    self._handle_document_upload(m, dest)
                    self.bot.send_message(m.chat.id, f"✅ Загружено: <code>{escape_html(str(dest))}</code>\nПерезапустите сервис при необходимости.")
                else:
                    self.bot.send_message(m.chat.id, "⚠️ Неожиданный тип ввода. Попробуйте ещё раз.")
            except Exception as e:
                log_line(f"pending handler error: {e}")
                self.bot.send_message(m.chat.id, f"⚠️ Ошибка: <code>{escape_html(str(e))}</code>")

    def _handle_document_upload(self, m: Message, dest: Path) -> None:
        # download from telegram
        file_id = m.document.file_id
        file_info = self.bot.get_file(file_id)
        data = self.bot.download_file(file_info.file_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # backup
        self.sh.backup_file(dest)
        with open(dest, "wb") as f:
            f.write(data)

    # ---- Rendering ----
    def render_main(self) -> str:
        vers = self._cached('snap:vers', 60, lambda: self.opkg.target_versions())
        v_lines = []
        for p in TARGET_PKGS:
            if p in vers:
                v_lines.append(f"{p}={vers[p]}")
        versions = " | ".join(v_lines) if v_lines else "—"

        caps = self.capabilities()
        mods = []
        mods.append("Router ✅")
        mods.append("HydraRoute ✅" if caps.get("hydra") else "HydraRoute ➖")
        mods.append("NFQWS2 ✅" if caps.get("nfqws2") else "NFQWS2 ➖")
        mods.append("NFQWS web ✅" if caps.get("nfqws_web") else "NFQWS web ➖")
        mods.append("AWG ✅" if caps.get("awg") else "AWG ➖")
        mods.append("cron ✅" if caps.get("cron") else "cron ➖")

        text = "\n".join([
            "🧰 <b>Keenetic Router Bot</b>",
            f"📍 IP: <code>{self.router.lan_ip()}</code>",
            f"⏱ Uptime: <code>{self.router.uptime()}</code>",
            f"🧩 Модули: <code>{escape_html(' | '.join(mods))}</code>",
            f"📦 Target packages: <code>{escape_html(versions)}</code>",
            "",
            "Выберите раздел:",
        ])
        return text


    # ---- Callback dispatcher ----
    def handle_callback(self, cq: CallbackQuery) -> None:
        try:
            self.bot.answer_callback_query(cq.id)
        except Exception:
            pass

        chat_id = cq.message.chat.id
        msg_id = cq.message.message_id
        data = cq.data or ""

        # Menus
        if data.startswith("m:"):
            m = data.split(":", 1)[1]
            if m == "main":
                self.send_or_edit(chat_id, self.render_main(), reply_markup=kb_main(self.snapshot(), self.capabilities()), message_id=msg_id)
                return
            if m == "router":
                self.send_or_edit(chat_id, "🧠 <b>Router</b>", reply_markup=kb_router(), message_id=msg_id)
                return
            if m == "hydra":
                variant = self.hydra.installed_variant()
                self.send_or_edit(chat_id, self.hydra.status_text(), reply_markup=kb_hydra(variant), message_id=msg_id)
                return
            if m == "nfqws":
                self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
                return
            if m == "awg":
                self.send_or_edit(chat_id, self.awg.status_text(), reply_markup=kb_awg(), message_id=msg_id)
                return
            if m == "opkg":
                self.send_or_edit(chat_id, "📦 <b>OPKG</b>", reply_markup=kb_opkg(), message_id=msg_id)
                return
            if m == "logs":
                self.send_or_edit(chat_id, "📝 <b>Логи</b>", reply_markup=kb_logs(), message_id=msg_id)
                return
            if m == "diag":
                self.send_or_edit(chat_id, "🛠 <b>Диагностика</b>", reply_markup=kb_diag(), message_id=msg_id)
                return
            if m == "storage":
                self.send_or_edit(chat_id, "💾 <b>Storage</b>", reply_markup=kb_storage(), message_id=msg_id)
                return

            if m == "install":
                caps = self.capabilities()
                txt = (
                    "🧩 <b>Установка/Сервис</b>\n"
                    "Здесь отображаются только отсутствующие компоненты.\n\n"
                    "⚠️ Установка меняет систему (opkg/скрипты)."
                )
                self.send_or_edit(chat_id, txt, reply_markup=kb_install(caps), message_id=msg_id)
                return
            if m == "settings":
                txt = (
                    "⚙️ <b>Настройки</b>\n"
                    f"CONFIG: <code>{escape_html(os.getenv('BOT_CONFIG', DEFAULT_CONFIG_PATH))}</code>\n"
                    f"ADMINS: <code>{', '.join(map(str, self.cfg.admins))}</code>\n"
                    f"MONITOR: <code>{'on' if self.cfg.monitor_enabled else 'off'}</code>\n"
                )
                self.send_or_edit(chat_id, txt, reply_markup=kb_home_back(), message_id=msg_id)
                return

        # Diagnostics actions
        if data.startswith("diag:"):
            self._handle_diag_cb(chat_id, msg_id, data)
            return

        # Storage actions
        if data.startswith("storage:"):
            self._handle_storage_cb(chat_id, msg_id, data)
            return

        # Router actions
        if data.startswith("router:"):
            self._handle_router_cb(chat_id, msg_id, data)
            return

        # Hydra
        if data.startswith("hydra:"):
            self._handle_hydra_cb(chat_id, msg_id, data, cq.from_user.id)
            return

        # nfqws
        if data.startswith("nfqws:"):
            self._handle_nfqws_cb(chat_id, msg_id, data, cq.from_user.id)
            return

        # awg
        if data.startswith("awg:"):
            self._handle_awg_cb(chat_id, msg_id, data, cq.from_user.id)
            return

        # opkg
        if data.startswith("opkg:"):
            self._handle_opkg_cb(chat_id, msg_id, data)
            return

        # logs
        if data.startswith("logs:"):
            self._handle_logs_cb(chat_id, msg_id, data)
            return

        # install
        if data.startswith("install:"):
            self._handle_install_cb(chat_id, msg_id, data)
            return

        self.send_or_edit(chat_id, "Неизвестная команда.", reply_markup=kb_main(self.snapshot(), self.capabilities()), message_id=msg_id)

    def _handle_install_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        """
        Install missing components from within the bot.
        Requires opkg + corresponding repositories already configured.
        """
        caps = self.capabilities()

        m = re.match(r"^install:([a-z0-9_]+)(\?.*)?$", data)
        if not m:
            self.send_or_edit(chat_id, "Неизвестная команда установки.", reply_markup=kb_install(caps), message_id=msg_id)
            return
        kind = m.group(1)

        if data.endswith("?confirm=1"):
            self.send_or_edit(
                chat_id,
                f"Установить <b>{escape_html(kind)}</b>? Подтвердить?",
                reply_markup=kb_confirm(f"install:{kind}!do", "m:install"),
                message_id=msg_id,
            )
            return

        if not data.endswith("!do"):
            self.send_or_edit(chat_id, "Установка компонентов", reply_markup=kb_install(caps), message_id=msg_id)
            return

        if not caps.get("opkg"):
            self.send_or_edit(chat_id, "❌ opkg не найден (Entware не установлен).", reply_markup=kb_install(caps), message_id=msg_id)
            return

        pkgs: List[str] = []
        label = kind
        if kind == "hydra":
            pkgs = ["hrneo", "hrweb", "hydraroute"]
            label = "HydraRoute Neo"
        elif kind == "nfqws2":
            pkgs = ["nfqws2-keenetic"]
            label = "NFQWS2"
        elif kind == "nfqwsweb":
            pkgs = ["nfqws-keenetic-web"]
            label = "NFQWS web"
        elif kind == "awg":
            pkgs = ["awg-manager"]
            label = "AWG Manager"
        elif kind == "cron":
            pkgs = ["cron"]
            label = "cron"
        else:
            self.send_or_edit(chat_id, "Неизвестный компонент.", reply_markup=kb_install(caps), message_id=msg_id)
            return

        # already installed?
        caps2 = self.capabilities()
        if kind == "hydra" and caps2.get("hydra"):
            self.send_or_edit(chat_id, "✅ Уже установлен.", reply_markup=kb_install(caps2), message_id=msg_id)
            return
        if kind == "nfqws2" and caps2.get("nfqws2"):
            self.send_or_edit(chat_id, "✅ Уже установлен.", reply_markup=kb_install(caps2), message_id=msg_id)
            return
        if kind == "nfqwsweb" and caps2.get("nfqws_web"):
            self.send_or_edit(chat_id, "✅ Уже установлен.", reply_markup=kb_install(caps2), message_id=msg_id)
            return
        if kind == "awg" and caps2.get("awg"):
            self.send_or_edit(chat_id, "✅ Уже установлен.", reply_markup=kb_install(caps2), message_id=msg_id)
            return
        if kind == "cron" and caps2.get("cron"):
            self.send_or_edit(chat_id, "✅ Уже установлен.", reply_markup=kb_install(caps2), message_id=msg_id)
            return

        self.send_or_edit(chat_id, f"⏳ Устанавливаю <b>{escape_html(label)}</b>…", reply_markup=kb_install(caps2), message_id=msg_id)

        rc1, out1 = self.sh.run(["opkg", "update"], timeout_sec=120)
        rc2, out2 = self.sh.run(["opkg", "install"] + pkgs, timeout_sec=300)

        try:
            self._cache.clear()
        except Exception:
            pass

        caps3 = self.capabilities()
        if rc2 == 0:
            self.send_or_edit(chat_id, f"✅ Установлено: <b>{escape_html(label)}</b>", reply_markup=kb_install(caps3), message_id=msg_id)
        else:
            details = (out1 or "") + "\n" + (out2 or "")
            self.send_or_edit(chat_id, f"❌ Ошибка установки <b>{escape_html(label)}</b>\n{fmt_code(details)}", reply_markup=kb_install(caps3), message_id=msg_id)
        return


    def _handle_diag_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        # lazy import: keep core fast; only load when needed
        from modules.diag import telegram_connectivity, dns_diagnostics, net_quick

        if data == "diag:tg":
            self.send_or_edit(chat_id, "⏳ Проверяю Telegram…", reply_markup=kb_diag(), message_id=msg_id)
            out = telegram_connectivity(self.sh)
            self.send_or_edit(chat_id, f"📡 <b>Telegram connectivity</b>\n{fmt_code(out)}", reply_markup=kb_diag(), message_id=msg_id)
            return

        if data == "diag:dns":
            self.send_or_edit(chat_id, "⏳ Проверяю DNS…", reply_markup=kb_diag(), message_id=msg_id)
            out = dns_diagnostics(self.sh)
            self.send_or_edit(chat_id, f"🧾 <b>DNS diagnostics</b>\n{fmt_code(out)}", reply_markup=kb_diag(), message_id=msg_id)
            return

        if data == "diag:net":
            self.send_or_edit(chat_id, "⏳ Собираю сеть…", reply_markup=kb_diag(), message_id=msg_id)
            out = net_quick(self.sh)
            self.send_or_edit(chat_id, f"🌐 <b>Network quick</b>\n{fmt_code(out)}", reply_markup=kb_diag(), message_id=msg_id)
            return

        if data == "diag:slow":
            self.send_or_edit(chat_id, "⏳ Считаю slow cmds…", reply_markup=kb_diag(), message_id=msg_id)
            out = self.sh.profiler.format_top(12)
            self.send_or_edit(chat_id, f"🐢 <b>Slow commands</b>\n{fmt_code(out)}", reply_markup=kb_diag(), message_id=msg_id)
            return

        if data.startswith("diag:clearlog?confirm=1"):
            self.send_or_edit(chat_id, "🧹 Очистить лог бота?", reply_markup=kb_confirm("diag:clearlog!do", "m:diag"), message_id=msg_id)
            return

        if data == "diag:clearlog!do":
            try:
                Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
                with open(LOG_PATH, "w", encoding="utf-8") as f:
                    f.write("")
                self.send_or_edit(chat_id, "✅ Лог очищен: <code>/opt/var/log/keenetic-tg-bot.log</code>", reply_markup=kb_diag(), message_id=msg_id)
            except Exception as e:
                self.send_or_edit(chat_id, f"⚠️ Не удалось очистить лог: <code>{escape_html(str(e))}</code>", reply_markup=kb_diag(), message_id=msg_id)
            return

        self.send_or_edit(chat_id, "Неизвестная команда.", reply_markup=kb_diag(), message_id=msg_id)
        return



    def _handle_storage_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        if data == "storage:status":
            self.send_or_edit(chat_id, "⏳ Собираю /opt…", reply_markup=kb_storage(), message_id=msg_id)
            out = storage_status(self.sh)
            self.send_or_edit(chat_id, f"💾 <b>/opt status</b>\n{fmt_code(out)}", reply_markup=kb_storage(), message_id=msg_id)
            return

        if data == "storage:top":
            self.send_or_edit(chat_id, "⏳ Считаю top dirs…", reply_markup=kb_storage(), message_id=msg_id)
            out = storage_top(self.sh)
            self.send_or_edit(chat_id, f"📁 <b>/opt top dirs</b>\n{fmt_code(out)}", reply_markup=kb_storage(), message_id=msg_id)
            return

        if data.startswith("storage:cleanup?confirm=1"):
            self.send_or_edit(chat_id, "🧹 Cleanup /opt (логи/кэш). Подтвердить?", reply_markup=kb_confirm("storage:cleanup!do", "m:storage"), message_id=msg_id)
            return

        if data == "storage:cleanup!do":
            self.send_or_edit(chat_id, "⏳ Выполняю cleanup…", reply_markup=kb_storage(), message_id=msg_id)
            out = storage_cleanup(self.sh)
            self.send_or_edit(chat_id, f"✅ <b>Cleanup done</b>\n{fmt_code(out)}", reply_markup=kb_storage(), message_id=msg_id)
            return

        self.send_or_edit(chat_id, "Неизвестная команда.", reply_markup=kb_storage(), message_id=msg_id)
        return

    def _handle_router_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        if data == "router:status":
            self.send_or_edit(chat_id, self.router.basic_status_text(), reply_markup=kb_router(), message_id=msg_id)
            return
        if data == "router:net":
            ok, txt = self.router.internet_check()
            self.send_or_edit(
                chat_id,
                f"🌐 <b>Интернет тест</b>\n{'✅ OK' if ok else '⚠️ проблемы'}\n<code>{escape_html(txt)}</code>",
                reply_markup=kb_router(),
                message_id=msg_id,
            )
            return

        if data == "router:netmenu":
            self.send_or_edit(chat_id, "🌐 <b>Router / Network</b>", reply_markup=kb_router_net(), message_id=msg_id)
            return
        if data == "router:fwmenu":
            self.send_or_edit(chat_id, "🧱 <b>Router / Firewall</b>", reply_markup=kb_router_fw(), message_id=msg_id)
            return
        if data == "router:dhcpmenu":
            self.send_or_edit(chat_id, "👥 <b>DHCP clients</b>", reply_markup=kb_router_dhcp_menu(), message_id=msg_id)
            return

        
        if data.startswith("router:dhcp:list:"):
            # router:dhcp:list:<kind>:<page>
            _, _, _, kind, page_s = (data.split(":", 4) + ["lan", "0"])[0:5]
            try:
                page = int(page_s)
            except Exception:
                page = 0
            # fetch/parse
            all_items = self._cached("router:dhcp:parsed", 15, lambda: self.router.get_dhcp_clients())
            lan, wifi = self.router.split_clients_lan_wifi(all_items) if hasattr(self.router, "split_clients_lan_wifi") else (all_items, [])
            items = lan if kind == "lan" else wifi if kind == "wifi" else all_items
            self.send_or_edit(chat_id, "⏳ Загружаю…", reply_markup=kb_router_dhcp_menu(), message_id=msg_id)
            kb = kb_router_dhcp_list(items, kind=kind, page=page, per_page=10)
            title = "LAN" if kind == "lan" else "WiFi" if kind == "wifi" else "All"
            self.send_or_edit(chat_id, f"👥 <b>DHCP clients: {title}</b>", reply_markup=kb, message_id=msg_id)
            return

        if data.startswith("router:dhcp:detail:"):
            # router:dhcp:detail:<kind>:<idx>:<page>
            parts = data.split(":")
            kind = parts[3] if len(parts) > 3 else "lan"
            idx = int(parts[4]) if len(parts) > 4 else 0
            page = int(parts[5]) if len(parts) > 5 else 0
            all_items = self._cached("router:dhcp:parsed", 15, lambda: self.router.get_dhcp_clients())
            lan, wifi = self.router.split_clients_lan_wifi(all_items) if hasattr(self.router, "split_clients_lan_wifi") else (all_items, [])
            items = lan if kind == "lan" else wifi if kind == "wifi" else all_items
            if idx < 0 or idx >= len(items):
                self.send_or_edit(chat_id, "Клиент не найден.", reply_markup=kb_router_dhcp_menu(), message_id=msg_id)
                return
            it = items[idx]
            ip = it.get("ip","")
            mac = it.get("mac","")
            name = it.get("name","")
            iface = it.get("iface","")
            raw = it.get("raw","")
            # extra: ip neigh
            neigh = ""
            if ip:
                _, neigh = self.sh.run(["ip", "neigh", "show", ip], timeout_sec=5)
            txt = "\n".join([
                "👤 <b>DHCP client</b>",
                f"IP: <code>{escape_html(ip)}</code>",
                f"MAC: <code>{escape_html(mac)}</code>",
                f"Name: <code>{escape_html(name)}</code>" if name else "Name: —",
                f"Iface: <code>{escape_html(iface)}</code>" if iface else "Iface: —",
                "",
                "<b>Raw:</b>",
                fmt_code(raw),
                "",
                "<b>ip neigh:</b>",
                fmt_code(neigh or "—"),
            ])
            kb = kb_router_dhcp_detail(kind=kind, page=page)
            self.send_or_edit(chat_id, txt, reply_markup=kb, message_id=msg_id)
            return

        if data == "router:dhcp":
            self.send_or_edit(chat_id, "⏳ Загружаю DHCP…", reply_markup=kb_router(), message_id=msg_id)
            txt = self._cached("router:dhcp", 10, lambda: self.router.show_dhcp_clients(limit=250)[0:8000])
            self.send_or_edit(chat_id, f"👥 <b>DHCP bindings</b>\n{fmt_code(txt)}", reply_markup=kb_router(), message_id=msg_id)
            return
        if data == "router:exportcfg":
            ok, msg, p = self.router.export_running_config()
            if ok and p:
                try:
                    self.bot.send_document(chat_id, InputFile(str(p)), caption=msg)
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ Не удалось отправить файл: <code>{escape_html(str(e))}</code>")
            else:
                self.bot.send_message(chat_id, f"⚠️ {escape_html(msg)}")
            return
        if data == "router:ipaddr":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router(), message_id=msg_id)
            out = self._cached("router:ipaddr", 10, lambda: self.sh.run(["ip", "-br", "addr"], timeout_sec=10)[1])
            self.send_or_edit(chat_id, f"📡 <b>ip addr (brief)</b>\n{fmt_code(out)}", reply_markup=kb_router(), message_id=msg_id)

            return
        if data == "router:iproute":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router(), message_id=msg_id)
            out = self._cached("router:iproute", 10, lambda: self.sh.run(["ip", "-4", "route"], timeout_sec=10)[1])
            self.send_or_edit(chat_id, f"🧭 <b>ip route -4</b>\n{fmt_code(fmt_ip_route(out))}", reply_markup=kb_router(), message_id=msg_id)

            return
        if data.startswith("router:fw:"):
            # router:fw:sum:<table> or router:fw:raw:<table>
            parts = data.split(":")
            if len(parts) >= 4:
                action = parts[2]
                table = parts[3]
                if not which("iptables"):
                    self.send_or_edit(chat_id, "iptables не найден.", reply_markup=kb_router_fw(), message_id=msg_id)
                    return
                self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router_fw(), message_id=msg_id)
                out = self._cached(f"router:iptables:{table}", 20, lambda: self.sh.run(["iptables", "-t", table, "-S"], timeout_sec=15)[1])
                if action == "sum":
                    self.send_or_edit(chat_id, f"🧱 <b>iptables {table} summary</b>\n{fmt_code(summarize_iptables(out))}", reply_markup=kb_router_fw(), message_id=msg_id)
                else:
                    self.send_or_edit(chat_id, f"🧱 <b>iptables -t {table} -S</b>\n{fmt_code(out)}", reply_markup=kb_router_fw(), message_id=msg_id)
                return
            self.send_or_edit(chat_id, "Неизвестная команда.", reply_markup=kb_router_fw(), message_id=msg_id)
            return

        if data == "router:iptables_sum":
            if which("iptables"):
                out = self._cached("router:iptables:mangle", 30, lambda: self.sh.run(["iptables", "-t", "mangle", "-S"], timeout_sec=15)[1])
                rc = 0
                self.send_or_edit(chat_id, f"🧱 <b>iptables mangle summary</b>\n{fmt_code(summarize_iptables(out))}", reply_markup=kb_router(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, "iptables не найден.", reply_markup=kb_router(), message_id=msg_id)
            return
        if data == "router:iptables_raw":
            self.send_or_edit(chat_id, "⏳ Выполняю…", reply_markup=kb_router(), message_id=msg_id)
            if which("iptables"):
                out = self._cached("router:iptables:mangle", 30, lambda: self.sh.run(["iptables", "-t", "mangle", "-S"], timeout_sec=15)[1])
                self.send_or_edit(chat_id, f"🧱 <b>iptables -t mangle -S</b>\n{fmt_code(out)}", reply_markup=kb_router(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, "iptables не найден.", reply_markup=kb_router(), message_id=msg_id)
            return

        if data.startswith("router:reboot?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🔄 <b>Reboot</b>\nТочно перезагрузить роутер?",
                reply_markup=kb_confirm("router:reboot!do", "m:router"),
                message_id=msg_id,
            )
            return
        if data == "router:reboot!do":
            self.send_or_edit(chat_id, "Перезагружаю… (соединение может пропасть)", reply_markup=kb_home_back(), message_id=msg_id)
            rc, out = self.router.reboot()
            # скорее всего, не успеем отправить результат
            return

    def _handle_hydra_cb(self, chat_id: int, msg_id: int, data: str, user_id: int) -> None:
        variant = self.hydra.installed_variant()

        # confirmations
        if data.startswith("hydra:update?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Обновление HydraRoute</b>\nВыполнить: <code>opkg update && opkg upgrade hrneo hrweb hydraroute</code> ?",
                reply_markup=kb_confirm("hydra:update!do", "m:hydra"),
                message_id=msg_id,
            )
            return
        if data == "hydra:update!do":
            self.send_or_edit(chat_id, "📦 Выполняю обновление…", reply_markup=kb_home_back(back="m:hydra"), message_id=msg_id)
            rc1, out1 = self.opkg.update()
            rc2, out2 = self.opkg.upgrade([p for p in ["hrneo", "hrweb", "hydraroute"] if p])
            txt = f"<b>opkg update</b> rc={rc1}\n<code>{escape_html(out1[:1500])}</code>\n\n<b>opkg upgrade</b> rc={rc2}\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(variant), message_id=msg_id)
            return

        if data.startswith("hydra:remove?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🗑 <b>Удаление HydraRoute</b>\nУдалить пакеты (opkg remove) и остановить сервис?",
                reply_markup=kb_confirm("hydra:remove!do", "m:hydra"),
                message_id=msg_id,
            )
            return
        if data == "hydra:remove!do":
            # остановим и удалим
            if variant == "neo":
                self.hydra.neo_cmd("stop")
                rc, out = self.opkg.remove("hrneo")
                rc2, out2 = self.opkg.remove("hrweb")
            elif variant == "classic":
                self.hydra.classic_cmd("stop")
                rc, out = self.opkg.remove("hydraroute")
                rc2, out2 = 0, ""
            else:
                rc, out, rc2, out2 = 1, "не установлен", 0, ""
            txt = f"opkg remove rc={rc}\n<code>{escape_html(out[:1500])}</code>\n\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(self.hydra.installed_variant()), message_id=msg_id)
            return

        if data == "hydra:status":
            self.send_or_edit(chat_id, self.hydra.status_text(), reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:diag":
            ipset_txt = self.hydra.diag_ipset()
            ipt_txt = self.hydra.diag_iptables()
            txt = f"🛠 <b>HydraRoute diag</b>\n\n<code>{escape_html(ipset_txt[:1200])}</code>\n\n<code>{escape_html(ipt_txt[:2000])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:start":
            if variant == "neo":
                rc, out = self.hydra.neo_cmd("start")
            elif variant == "classic":
                rc, out = self.hydra.classic_cmd("start")
            else:
                rc, out = 127, "не установлен"
            self.send_or_edit(chat_id, f"▶️ start rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:stop":
            if variant == "neo":
                rc, out = self.hydra.neo_cmd("stop")
            elif variant == "classic":
                rc, out = self.hydra.classic_cmd("stop")
            else:
                rc, out = 127, "не установлен"
            self.send_or_edit(chat_id, f"⏹ stop rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:restart":
            if variant == "neo":
                rc, out = self.hydra.neo_cmd("restart")
            elif variant == "classic":
                rc, out = self.hydra.classic_cmd("restart")
            else:
                rc, out = 127, "не установлен"
            self.send_or_edit(chat_id, f"🔄 restart rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:hrweb":
            url = f"http://{self.router.lan_ip()}:2000"
            self.send_or_edit(chat_id, f"🌐 HRweb: <code>{url}</code>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data.startswith("hydra:file:"):
            kind = data.split(":", 2)[2]
            ok, msg, p = self.hydra.file_get(kind)
            if ok and p:
                # отправим как документ
                try:
                    self.bot.send_document(chat_id, InputFile(str(p)), caption=f"{kind}")
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ Не удалось отправить: <code>{escape_html(str(e))}</code>")
                self.send_or_edit(chat_id, self.hydra.status_text(), reply_markup=kb_hydra(variant), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"⚠️ {escape_html(msg)}", reply_markup=kb_hydra(variant), message_id=msg_id)
            return

        if data == "hydra:rules":
            res = self.hydra.domain_summary()
            self.send_or_edit(chat_id, f"📚 <b>HydraRoute правила</b>\n<pre><code>{escape_html(res)}</code></pre>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:dupes":
            res = self.hydra.duplicates()
            self.send_or_edit(chat_id, f"🧩 <b>Дубликаты доменов</b>\n<pre><code>{escape_html(res)}</code></pre>", reply_markup=kb_hydra(variant), message_id=msg_id)
            return
        if data == "hydra:search_domain":
            self.pending.set(chat_id, user_id, "hydra_search_domain_text", {}, ttl_sec=300)
            self.bot.send_message(chat_id, "Введите домен/подстроку для поиска в <code>domain.conf</code> (например: <code>telegram</code>).")
            return
        if data == "hydra:import:domain.conf":
            self.pending.set(chat_id, user_id, "hydra_import_domain_conf", {}, ttl_sec=300)
            self.bot.send_message(chat_id, "Отправьте файлом новый <code>domain.conf</code>. Я заменю текущий (с бэкапом) и перезапущу Neo.")
            return

        if data == "hydra:add_domain":
            # просим текст
            self.pending.set(chat_id, user_id, "hydra_add_domain_text", {"target": "HydraRoute"}, ttl_sec=300)
            self.bot.send_message(chat_id, "Введите домены через пробел/запятую (или geosite:TAG). Будет добавлено в <code>domain.conf</code> для цели <code>HydraRoute</code>.")
            return
        if data == "hydra:rm_domain":
            self.pending.set(chat_id, user_id, "hydra_rm_domain_text", {}, ttl_sec=300)
            self.bot.send_message(chat_id, "Введите домен для удаления из <code>domain.conf</code> (например: <code>youtube.com</code>).")
            return

    def _handle_nfqws_cb(self, chat_id: int, msg_id: int, data: str, user_id: int) -> None:
        # confirmations
        if data.startswith("nfqws:update?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Обновление NFQWS2</b>\nВыполнить: <code>opkg update && opkg upgrade nfqws2-keenetic nfqws-keenetic-web</code> ?",
                reply_markup=kb_confirm("nfqws:update!do", "m:nfqws"),
                message_id=msg_id,
            )
            return
        if data == "nfqws:update!do":
            self.send_or_edit(chat_id, "📦 Выполняю обновление…", reply_markup=kb_home_back(back="m:nfqws"), message_id=msg_id)
            rc1, out1 = self.opkg.update()
            rc2, out2 = self.opkg.upgrade(["nfqws2-keenetic", "nfqws-keenetic-web"])
            txt = f"<b>opkg update</b> rc={rc1}\n<code>{escape_html(out1[:1500])}</code>\n\n<b>opkg upgrade</b> rc={rc2}\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_nfqws(), message_id=msg_id)
            return

        if data.startswith("nfqws:clear:auto.list?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🧹 <b>Очистка auto.list</b>\nТочно очистить <code>auto.list</code>?",
                reply_markup=kb_confirm("nfqws:clear:auto.list!do", "m:nfqws"),
                message_id=msg_id,
            )
            return
        if data == "nfqws:clear:auto.list!do":
            ok, msg = self.nfqws.clear_list("auto.list")
            self.send_or_edit(chat_id, ("✅ " if ok else "⚠️ ") + escape_html(msg), reply_markup=kb_nfqws(), message_id=msg_id)
            return


        if data.startswith("nfqws:filelist:"):
            name = data.split(":", 2)[2]
            target = NFQWS_LISTS_DIR / name
            if target.exists():
                try:
                    self.bot.send_document(chat_id, InputFile(str(target)), caption=name)
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ {escape_html(str(e))}")
            else:
                self.bot.send_message(chat_id, f"Файл не найден: <code>{escape_html(str(target))}</code>")
            self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
            return

        if data == "nfqws:import:list?confirm=1":
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Импорт списка</b>\n"
                "Я попрошу прислать файл и заменю <code>user.list</code> (с бэкапом), затем сделаю <code>reload</code>.",
                reply_markup=kb_confirm("nfqws:import:list!do", "m:nfqws"),
                message_id=msg_id,
            )
            return
        if data == "nfqws:import:list!do":
            self.pending.set(chat_id, user_id, "nfqws_import_list", {"list_name": "user.list"}, ttl_sec=300)
            self.bot.send_message(chat_id, "Пришлите файлом новый <code>user.list</code> (я заменю текущий, сделаю бэкап и reload).")
            return

        if data == "nfqws:status":
            self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:diag":
            diag = self.nfqws.diag_iptables_queue()
            hook = "✅" if NFQWS_NETFILTER_HOOK.exists() else "⚠️ нет hook /opt/etc/ndm/netfilter.d/100-nfqws2.sh"
            txt = f"🛠 <b>NFQWS2 diag</b>\n{hook}\n\n<code>{escape_html(diag[:3500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data in ("nfqws:start", "nfqws:stop", "nfqws:restart", "nfqws:reload"):
            action = data.split(":", 1)[1]
            rc, out = self.nfqws.init_action(action)
            self.send_or_edit(chat_id, f"{action} rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:web":
            caps = self.capabilities()
            if not caps.get("nfqws_web"):
                self.send_or_edit(chat_id, "🌐 WebUI: ➖ (nfqws-keenetic-web не установлен)", reply_markup=kb_nfqws(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"🌐 WebUI: <code>{self.nfqws.web_url()}</code>", reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:file:nfqws2.conf":
            if NFQWS_CONF.exists():
                try:
                    self.bot.send_document(chat_id, InputFile(str(NFQWS_CONF)), caption="nfqws2.conf")
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ {escape_html(str(e))}")
            else:
                self.bot.send_message(chat_id, "nfqws2.conf не найден.")
            self.send_or_edit(chat_id, self.nfqws.status_text(), reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data == "nfqws:lists":
            self.send_or_edit(chat_id, f"📚 <b>Lists</b>\n<code>{escape_html(self.nfqws.lists_stats())}</code>", reply_markup=kb_nfqws(), message_id=msg_id)
            return
        if data.startswith("nfqws:add:"):
            list_name = data.split(":", 2)[2]
            self.pending.set(chat_id, user_id, "nfqws_add_list_text", {"list_name": list_name}, ttl_sec=300)
            self.bot.send_message(chat_id, f"Введите домены для добавления в <code>{escape_html(list_name)}</code> (через пробел/запятую).")
            return
        if data == "nfqws:log":
            ok, txt = self.sh.read_file(NFQWS_LOG, max_bytes=30_000)
            if not ok:
                self.send_or_edit(chat_id, f"⚠️ {escape_html(txt)}", reply_markup=kb_nfqws(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"📜 <b>nfqws2.log</b>\n<code>{escape_html(txt[-3500:])}</code>", reply_markup=kb_nfqws(), message_id=msg_id)
            return

    def _handle_awg_cb(self, chat_id: int, msg_id: int, data: str, user_id: int) -> None:
        if data.startswith("awg:update?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Обновление AWG Manager</b>\nВыполнить: <code>opkg update && opkg upgrade awg-manager</code> ?",
                reply_markup=kb_confirm("awg:update!do", "m:awg"),
                message_id=msg_id,
            )
            return
        if data == "awg:update!do":
            self.send_or_edit(chat_id, "📦 Выполняю обновление…", reply_markup=kb_home_back(back="m:awg"), message_id=msg_id)
            rc1, out1 = self.opkg.update()
            rc2, out2 = self.opkg.upgrade(["awg-manager"])
            txt = f"<b>opkg update</b> rc={rc1}\n<code>{escape_html(out1[:1500])}</code>\n\n<b>opkg upgrade</b> rc={rc2}\n<code>{escape_html(out2[:1500])}</code>"
            self.send_or_edit(chat_id, txt, reply_markup=kb_awg(), message_id=msg_id)
            return

        if data.startswith("awg:remove?confirm=1"):
            self.send_or_edit(
                chat_id,
                "🗑 <b>Удаление AWG Manager</b>\nУдалить пакет <code>awg-manager</code> (opkg remove)?",
                reply_markup=kb_confirm("awg:remove!do", "m:awg"),
                message_id=msg_id,
            )
            return
        if data == "awg:remove!do":
            self.awg.init_action("stop")
            rc, out = self.opkg.remove("awg-manager")
            self.send_or_edit(chat_id, f"opkg remove rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return

        # --- AWG API (локальный, т.к. authDisabled=true) ---
        if data == "awg:api:statusall":
            ok, msg, obj = self.awg.api_get("/status/all")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"📊 <b>AWG status/all</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:updatecheck":
            ok, msg, obj = self.awg.api_get("/system/update/check")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"⬆️ <b>AWG update/check</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:logs":
            ok, msg, obj = self.awg.api_get("/logs")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"🧾 <b>AWG logs</b>\n<pre><code>{escape_html(pretty[-3500:])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:tunnels":
            ok, msg, obj = self.awg.api_get("/tunnels/list")
            if not ok or obj is None:
                self.send_or_edit(chat_id, f"⚠️ tunnels/list: {escape_html(msg)}", reply_markup=kb_awg(), message_id=msg_id)
                return
            tunnels = obj if isinstance(obj, list) else (obj.get("items") if isinstance(obj, dict) else None)
            if not isinstance(tunnels, list):
                pretty = json.dumps(obj, ensure_ascii=False, indent=2) if isinstance(obj, (dict, list)) else str(obj)
                self.send_or_edit(chat_id, f"⚠️ Неожиданный формат tunnels/list\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
                return
            self._awg_cache_set(chat_id, user_id, tunnels, ttl_sec=300)

            lines = []
            kb = InlineKeyboardMarkup()
            max_btn = 10
            for i, t in enumerate(tunnels[:max_btn]):
                tid = t.get("id") or t.get("tunnelId") or t.get("interface") or str(i)
                name = t.get("name") or t.get("title") or t.get("interfaceName") or tid
                lines.append(f"{i}. {name} ({tid})")
                kb.row(InlineKeyboardButton(f"{i}. {name}"[:50], callback_data=f"awg:tunnel:{i}"))
            kb.row(InlineKeyboardButton("🏠 Home", callback_data="m:main"))

            txt = "🧭 <b>AWG туннели</b>\n" + "<pre><code>" + escape_html("\n".join(lines)[:3500]) + "</code></pre>"
            self.send_or_edit(chat_id, txt, reply_markup=kb, message_id=msg_id)
            return

        if data.startswith("awg:tunnel:"):
            try:
                idx = int(data.split(":")[2])
            except Exception:
                self.send_or_edit(chat_id, "⚠️ Некорректный индекс туннеля.", reply_markup=kb_awg(), message_id=msg_id)
                return
            tunnels = self._awg_cache_get(chat_id, user_id)
            if not tunnels or idx < 0 or idx >= len(tunnels):
                self.send_or_edit(chat_id, "⚠️ Кэш туннелей устарел. Открой 'Туннели' заново.", reply_markup=kb_awg(), message_id=msg_id)
                return

            t = tunnels[idx]
            tid = t.get("id") or t.get("tunnelId") or t.get("interface") or str(idx)

            # подтянем актуальный статус
            ok_s, msg_s, st = self.awg.api_get("/status/all")
            if ok_s and isinstance(st, list):
                for item in st:
                    if (item.get("id") or item.get("tunnelId")) == tid:
                        # аккуратно "поверх" добавляем статусные поля
                        for k, v in item.items():
                            t[f"status_{k}"] = v
                        break

            pretty = json.dumps(t, ensure_ascii=False, indent=2)
            self.send_or_edit(
                chat_id,
                f"📋 <b>Туннель #{idx}</b> (<code>{escape_html(str(tid))}</code>)\n<pre><code>{escape_html(pretty[:3500])}</code></pre>",
                reply_markup=kb_awg_tunnel(idx),
                message_id=msg_id,
            )
            return


        if data.startswith("awg:tunnelact:"):
            parts = data.split(":")
            if len(parts) < 4:
                self.send_or_edit(chat_id, "⚠️ Некорректная команда.", reply_markup=kb_awg(), message_id=msg_id)
                return
            idx = int(parts[2])
            action = parts[3]
            tunnels = self._awg_cache_get(chat_id, user_id)
            if not tunnels or idx < 0 or idx >= len(tunnels):
                self.send_or_edit(chat_id, "⚠️ Кэш туннелей устарел. Открой 'Туннели' заново.", reply_markup=kb_awg(), message_id=msg_id)
                return
            t = tunnels[idx]
            tid = t.get("id") or t.get("tunnelId") or t.get("interface")
            enc = urllib.parse.quote(str(tid))

            if action == "start":
                endpoint = f"/control/start?id={enc}"
            elif action == "stop":
                endpoint = f"/control/stop?id={enc}"
            elif action == "restart":
                endpoint = f"/control/restart?id={enc}"
            elif action == "toggle":
                endpoint = f"/control/toggle-enabled?id={enc}"
            elif action == "default":
                endpoint = f"/control/toggle-default-route?id={enc}"
            else:
                self.send_or_edit(chat_id, "⚠️ Неизвестное действие.", reply_markup=kb_awg_tunnel(idx), message_id=msg_id)
                return

            ok, msg, obj = self.awg.api_post(endpoint, body=None)
            payload = obj if obj is not None else {"message": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"✅ <b>{action}</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg_tunnel(idx), message_id=msg_id)
            return



        if data == "awg:api:systeminfo":
            ok1, msg1, info = self.awg.api_get("/system/info")
            ok2, msg2, wan = self.awg.api_get("/wan/status")
            payload = {"system/info": info if ok1 else {"error": msg1}, "wan/status": wan if ok2 else {"error": msg2}}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
            self.send_or_edit(chat_id, f"ℹ️ <b>AWG system/wan</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:diagr":
            ok, msg, obj = self.awg.api_post("/diagnostics/run", body=None)
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"🧪 <b>AWG diagnostics/run</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:diags":
            ok, msg, obj = self.awg.api_get("/diagnostics/status")
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"🧪 <b>AWG diagnostics/status</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:api:updateapply?confirm=1":
            self.send_or_edit(
                chat_id,
                "⬆️ <b>AWG update/apply</b>\nТочно применить обновление (это может перезапустить сервис/модули)?",
                reply_markup=kb_confirm("awg:api:updateapply!do", "m:awg"),
                message_id=msg_id,
            )
            return
        if data == "awg:api:updateapply!do":
            ok, msg, obj = self.awg.api_post("/system/update/apply", body=None)
            payload = obj if obj is not None else {"error": msg}
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
            self.send_or_edit(chat_id, f"⬆️ <b>AWG update/apply</b>\n<pre><code>{escape_html(pretty[:3500])}</code></pre>", reply_markup=kb_awg(), message_id=msg_id)
            return

        if data == "awg:status":
            self.send_or_edit(chat_id, self.awg.status_text(), reply_markup=kb_awg(), message_id=msg_id)
            return
        if data in ("awg:start", "awg:stop", "awg:restart"):
            action = data.split(":", 1)[1]
            rc, out = self.awg.init_action(action)
            self.send_or_edit(chat_id, f"{action} rc={rc}\n<code>{escape_html(out[:3000])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:web":
            self.send_or_edit(chat_id, f"🌐 WebUI: <code>{self.awg.web_url()}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:health":
            ok, out = self.awg.health_check()
            self.send_or_edit(chat_id, f"💓 Health: {'✅' if ok else '⚠️'}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:wg":
            txt = self.awg.wg_status()
            self.send_or_edit(chat_id, f"🧵 <b>wg show</b>\n<code>{escape_html(txt[:3500])}</code>", reply_markup=kb_awg(), message_id=msg_id)
            return
        if data == "awg:file:settings.json":
            if AWG_SETTINGS.exists():
                try:
                    self.bot.send_document(chat_id, InputFile(str(AWG_SETTINGS)), caption="settings.json")
                except Exception as e:
                    self.bot.send_message(chat_id, f"⚠️ {escape_html(str(e))}")
            else:
                self.bot.send_message(chat_id, "settings.json не найден.")
            self.send_or_edit(chat_id, self.awg.status_text(), reply_markup=kb_awg(), message_id=msg_id)
            return

    def _handle_opkg_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        if data == "opkg:update":
            self.send_or_edit(chat_id, "🔄 Выполняю <code>opkg update</code>…", reply_markup=kb_opkg(), message_id=msg_id)
            rc, out = self.opkg.update()
            self.send_or_edit(chat_id, f"opkg update rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data == "opkg:upg":
            rc, out = self.opkg.list_upgradable()
            if rc != 0:
                self.send_or_edit(chat_id, f"⚠️ rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            else:
                self.send_or_edit(chat_id, f"⬆️ <b>list-upgradable</b>\n<code>{escape_html(out[:3500] or 'нет обновлений')}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data == "opkg:versions":
            vers = self._cached('snap:vers', 60, lambda: self.opkg.target_versions())
            if not vers:
                self.send_or_edit(chat_id, "Не удалось получить версии (opkg).", reply_markup=kb_opkg(), message_id=msg_id)
            else:
                lines = [f"{k}={v}" for k, v in vers.items()]
                self.send_or_edit(chat_id, "📦 <b>Версии</b>\n<code>" + escape_html("\n".join(lines)) + "</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data.startswith("opkg:upgrade?confirm=1"):
            self.send_or_edit(
                chat_id,
                "⬆️ <b>Upgrade TARGET</b>\nОбновить только целевые пакеты?\n<code>{}</code>".format(" ".join(TARGET_PKGS)),
                reply_markup=kb_confirm("opkg:upgrade!do", "m:opkg"),
                message_id=msg_id,
            )
            return
        if data == "opkg:upgrade!do":
            self.send_or_edit(chat_id, "⬆️ Выполняю upgrade…", reply_markup=kb_opkg(), message_id=msg_id)
            rc, out = self.opkg.upgrade(TARGET_PKGS)
            self.send_or_edit(chat_id, f"opkg upgrade rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return
        if data == "opkg:installed":
            rc, out = self.opkg.list_installed()
            if rc != 0:
                self.send_or_edit(chat_id, f"⚠️ rc={rc}\n<code>{escape_html(out[:3500])}</code>", reply_markup=kb_opkg(), message_id=msg_id)
                return
            # фильтруем target
            lines = []
            for ln in out.splitlines():
                pkg = ln.split(" ", 1)[0]
                if pkg in TARGET_PKGS:
                    lines.append(ln)
            self.send_or_edit(chat_id, "📃 <b>Installed (target)</b>\n<code>" + escape_html("\n".join(lines) or "—") + "</code>", reply_markup=kb_opkg(), message_id=msg_id)
            return

    def _handle_logs_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        kind = data.split(":", 1)[1]
        if kind == "bot":
            p = Path(LOG_PATH)
        elif kind == "nfqws":
            p = NFQWS_LOG
        elif kind == "hrneo":
            p = HR_NEO_LOG_DEFAULT
        elif kind == "dmesg":
            rc, out = self.sh.run(["dmesg", "-T"], timeout_sec=10)
            self.send_or_edit(chat_id, f"📜 <b>dmesg</b>\n<code>{escape_html(out[-3500:])}</code>", reply_markup=kb_logs(), message_id=msg_id)
            return
        else:
            self.send_or_edit(chat_id, "Неизвестный лог.", reply_markup=kb_logs(), message_id=msg_id)
            return

        ok, txt = self.sh.read_file(p, max_bytes=40_000)
        if not ok:
            self.send_or_edit(chat_id, f"⚠️ {escape_html(txt)}", reply_markup=kb_logs(), message_id=msg_id)
            return
        self.send_or_edit(chat_id, f"📜 <b>{escape_html(p.name)}</b>\n<code>{escape_html(txt[-3500:])}</code>", reply_markup=kb_logs(), message_id=msg_id)


    def _acquire_instance_lock(self) -> bool:
        """
        Prevent 2 instances running simultaneously (fixes Telegram 409 conflicts).
        Uses an atomic mkdir lock under /opt/var/run.
        """
        lock_dir = Path("/opt/var/run/keenetic-tg-bot.lock")
        pid_path = lock_dir / "pid"
        lock_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            try:
                pid = int(pid_path.read_text().strip())
                os.kill(pid, 0)
                log_line(f"instance lock exists, pid alive: {pid}")
                return False
            except Exception:
                # stale lock
                try:
                    shutil.rmtree(lock_dir, ignore_errors=True)
                    lock_dir.mkdir(parents=True, exist_ok=False)
                except Exception as e:
                    log_line(f"cannot acquire lock: {e}")
                    return False
        try:
            pid_path.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        atexit.register(lambda: shutil.rmtree(lock_dir, ignore_errors=True))
        return True

    def run(self) -> None:
        log_line("bot starting")
        if not self._acquire_instance_lock():
            return
        if self.monitor:
            try:
                self.monitor.start()
            except Exception as e:
                log_line(f"monitor start error: {e}")

        # уведомим админов
        try:
            for uid in self.cfg.admins:
                self.bot.send_message(uid, "✅ Keenetic Router Bot запущен.", disable_web_page_preview=True)
        except Exception:
            pass

        telebot.logger.setLevel(logging.INFO if self.cfg.debug_enabled else logging.CRITICAL)
        backoff = 5
        err_streak = 0
        last_notify = 0.0

        while True:
            try:
                self.bot.infinity_polling(
                    timeout=60,
                    long_polling_timeout=20,
                    interval=self.cfg.poll_interval_sec,
                    skip_pending=True,
                    allowed_updates=["message", "callback_query"],
                    logger_level=(logging.INFO if self.cfg.debug_enabled else logging.CRITICAL),
                    non_stop=True,
                )
                backoff = 5
                err_streak = 0
            except Exception as e:
                err_streak += 1
                log_line(f"polling error: {e}")
                now = time.time()
                # throttle: notify admins only after several consecutive errors, max once/hour
                if err_streak >= 3 and (now - last_notify) >= 3600:
                    last_notify = now
                    for uid in self.cfg.admins:
                        try:
                            self.bot.send_message(
                                uid,
                                "⚠️ Telegram polling нестабилен (timeout/reset). Проверь маршрут до api.telegram.org: /diag → Telegram.",
                                disable_web_page_preview=True,
                            )
                        except Exception:
                            pass
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

def main() -> None:
    cfg_path = os.getenv("BOT_CONFIG", DEFAULT_CONFIG_PATH)
    if not os.path.exists(cfg_path):
        raise SystemExit(
            f"Config not found: {cfg_path}\n"
            f"Create it from config.example.json and set BOT_CONFIG or put it at {DEFAULT_CONFIG_PATH}"
        )
    cfg = load_config_or_exit()
    app = App(cfg)
    app.run()


if __name__ == "__main__":
    main()
