# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, Optional

from telebot.types import InlineKeyboardMarkup

from .constants import *
from .utils import log_line, escape_html
from .ui import kb_notice_actions, kb_confirm, kb_home_back, kb_install
from .drivers import RouterDriver, HydraRouteDriver, NfqwsDriver, AwgDriver

class Monitor(threading.Thread):
    def __init__(
        self,
        bot: telebot.TeleBot,
        cfg: BotConfig,
        sh: Shell,
        router: RouterDriver,
        opkg: OpkgDriver,
        hydra: HydraRouteDriver,
        nfqws: NfqwsDriver,
        awg: AwgDriver,
    ):
        super().__init__(daemon=True)
        self.bot = bot
        self.cfg = cfg
        self.sh = sh
        self.router = router
        self.opkg = opkg
        self.hydra = hydra
        self.nfqws = nfqws
        self.awg = awg

        self._stop = threading.Event()

        self._last_opkg_check = 0.0
        self._last_net_check = 0.0

        self._last_upgradable: str = ""
        self._service_state: Dict[str, bool] = {}
        self._internet_state: Optional[bool] = None

        self._last_log_pos: Dict[Path, int] = {}
        self._notify_last: Dict[str, float] = {}

    def stop(self) -> None:
        self._stop.set()

    def _cooldown_ok(self, key: str, interval_sec: Optional[int] = None) -> bool:
        now = time.time()
        last = self._notify_last.get(key, 0)
        min_iv = interval_sec if interval_sec is not None else self.cfg.notify_cooldown_sec
        if now - last >= min_iv:
            self._notify_last[key] = now
            return True
        return False


    def _fmt_notice(self, title: str, summary_lines: list[str], details: str | None = None, hint: str | None = None) -> str:
        """
        Формирует читабельный текст уведомления (HTML).
        - title: заголовок
        - summary_lines: короткие строки-итоги
        - details: подробности (лог/вывод), будет оформлено как pre
        - hint: подсказка "что делать"
        """
        parts: list[str] = []
        parts.append(f"{title}")
        parts.append(f"🕒 <code>{escape_html(_now_ts())}</code>")
        if summary_lines:
            parts.append("")
            parts.extend(summary_lines)
        if hint:
            parts.append("")
            parts.append(f"👉 <b>Что сделать:</b> {escape_html(hint)}")
        if details:
            d = details.strip()
            if len(d) > 3200:
                d = d[-3200:]  # показываем хвост
            parts.append("")
            parts.append(f"<pre><code>{escape_html(d)}</code></pre>")
        return "\n".join(parts)

    def _notify_admins(self, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        # text already formatted HTML
        for uid in self.cfg.admins:
            for attempt in range(2):
                try:
                    self.bot.send_message(uid, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_markup)
                    break
                except Exception as e:
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    log_line(f"notify error to {uid}: {e}")


    def _check_services(self) -> None:
        # грубая проверка: pidof по процессам/скриптам
        def pidof(name: str) -> bool:
            rc, out = self.sh.run(["pidof", name], timeout_sec=5)
            return rc == 0 and bool(out.strip())

        # HydraRoute Neo: process hrneo, Classic: hydraroute maybe; но используем status команду если есть
        hydra_up = False
        if self.hydra.is_neo_available():
            rc, _ = self.hydra.neo_cmd("status")
            hydra_up = (rc == 0) or pidof("hrneo")
        elif self.hydra.is_classic_available():
            rc, _ = self.hydra.classic_cmd("status")
            hydra_up = (rc == 0) or pidof("hydraroute")
        else:
            hydra_up = False

        nfqws_up = False
        if self.nfqws.installed():
            rc, _ = self.nfqws.init_action("status")
            nfqws_up = (rc == 0) or pidof("nfqws2")

        awg_up = False
        if self.awg.installed():
            rc, _ = self.awg.init_action("status")
            awg_up = (rc == 0) or pidof("awg-manager")

        current = {
            "hydra": hydra_up,
            "nfqws": nfqws_up,
            "awg": awg_up,
        }
        for k, v in current.items():
            prev = self._service_state.get(k)
            self._service_state[k] = v
            if prev is None:
                continue
            if prev and (not v) and self.cfg.notify_on_service_down and self._cooldown_ok(f"svc:{k}"):
                restart_map = {"nfqws": "nfqws:restart", "hydra": "hydra:restart", "awg": "awg:restart"}
                logs_map = {"nfqws": "logs:nfqws", "hydra": "logs:hrneo", "awg": "logs:awg"}
                restart_cb = restart_map.get(k)
                logs_cb = logs_map.get(k)
                self._notify_admins(
                    self._fmt_notice(
                        title=f"🚨 <b>Сервис остановлен</b>: <code>{k}</code>",
                        summary_lines=[f"Статус: <b>STOPPED</b>"],
                        hint="Открой /menu → нужный раздел → Status/Restart"
                    ),
                    reply_markup=kb_notice_actions(primary_cb="m:main", restart_cb=restart_cb, logs_cb=logs_cb)
                )

    def _check_internet(self) -> None:
        ok, msg = self.router.internet_check()
        prev = self._internet_state
        self._internet_state = ok
        if prev is None:
            return
        if prev and (not ok) and self.cfg.notify_on_internet_down and self._cooldown_ok("net:down"):
            self._notify_admins(
                self._fmt_notice(
                    title="🌐⚠️ <b>Интернет недоступен</b>",
                    summary_lines=["Проверка ping/DNS не прошла или нестабильна."],
                    details=msg,
                    hint="Проверь WAN/провайдера/маршрутизацию до api.telegram.org"
                ),
                reply_markup=kb_notice_actions(primary_cb="router:net", logs_cb="logs:bot")
            )
        if (not prev) and ok and self._cooldown_ok("net:up"):
            self._notify_admins(
                self._fmt_notice(
                    title="🌐✅ <b>Интернет восстановлен</b>",
                    summary_lines=["Доступ до сети снова есть."],
                    hint="Если бот/сервисы были недоступны — проверь Status в меню"
                ),
                reply_markup=kb_notice_actions(primary_cb="m:main")
            )

    def _check_resources(self) -> None:
        l1, _, _ = self.router.loadavg()
        _, free_mb = self.router.disk_free_mb("/opt")
        if l1 >= self.cfg.cpu_load_threshold and self._cooldown_ok("res:load", interval_sec=self.cfg.notify_load_interval_sec):
            self._notify_admins(
                self._fmt_notice(
                    title="📈⚠️ <b>Высокая нагрузка</b>",
                    summary_lines=[f"load1: <code>{l1:.2f}</code>"],
                    hint="Проверь процессы/логи (NFQWS2/Hydra/AWG), перезапусти при необходимости"
                ),
                reply_markup=kb_notice_actions(primary_cb="router:status", logs_cb="logs:bot")
            )
        if free_mb <= self.cfg.disk_free_mb_threshold and self._cooldown_ok("res:disk", interval_sec=self.cfg.notify_disk_interval_sec):
            is_usb, src = self.router.opt_storage_info()
            hint = "Удалить лишнее: очистить логи/кэш, убрать ненужные пакеты"
            if not is_usb:
                hint = "Похоже, /opt на внутренней памяти. Лучше перенести Entware на USB/SSD или освободить место (opkg remove, очистка логов)."
            self._notify_admins(
                self._fmt_notice(
                    title="💾⚠️ <b>Мало места на /opt</b>",
                    summary_lines=[f"Свободно: <code>{free_mb} MB</code>", f"Носитель: <code>{escape_html(src)}</code>"],
                    hint=hint
                ),
                reply_markup=kb_notice_actions(primary_cb="m:opkg")
            )

    def _check_opkg_updates(self) -> None:
        # делаем opkg update редко, но list-upgradable можно чаще после update
        if not self.cfg.notify_on_updates:
            return
        # update repo
        rc, out = self.opkg.update()
        if rc != 0:
            # не спамим
            if self._cooldown_ok("opkg:update_fail"):
                self._notify_admins(
                self._fmt_notice(
                    title="📦⚠️ <b>Ошибка opkg update</b>",
                    summary_lines=["Не удалось обновить списки пакетов."],
                    details=out,
                    hint="Проверь интернет/DNS и повтори позже (OPKG → opkg update)"
                ),
                reply_markup=kb_notice_actions(primary_cb="opkg:update", logs_cb="logs:bot")
            )
            return
        rc2, out2 = self.opkg.list_upgradable()
        if rc2 != 0:
            return
        if out2.strip() and out2.strip() != self._last_upgradable:
            self._last_upgradable = out2.strip()
            count = len([ln for ln in out2.splitlines() if ln.strip()])
            preview = "\n".join(out2.splitlines()[:20])
            self._notify_admins(
                self._fmt_notice(
                    title="📦⬆️ <b>Доступны обновления opkg</b>",
                    summary_lines=[f"Пакетов: <code>{count}</code>", "Первые строки:"],
                    details=preview,
                    hint="Открой /menu → OPKG → upgrade TARGET (или обнови нужные пакеты)"
                ),
                reply_markup=kb_notice_actions(primary_cb="m:opkg", restart_cb="opkg:upgrade?confirm=1")
            )

    def _tail_new_errors(self, path: Path, pattern: re.Pattern) -> Optional[str]:
        try:
            if not path.exists():
                return None
            size = path.stat().st_size
            pos = self._last_log_pos.get(path, max(0, size - 8192))
            if pos > size:
                pos = max(0, size - 8192)
            if size == pos:
                return None
            read_len = min(65536, size - pos)
            with open(path, "rb") as f:
                f.seek(pos)
                data = f.read(read_len)
            self._last_log_pos[path] = size
            text = data.decode("utf-8", errors="replace")
            # берём только строки с ошибками
            hits = [ln for ln in text.splitlines() if pattern.search(ln)]
            if not hits:
                return None
            # ограничим
            if len(hits) > 20:
                hits = hits[-20:]
            return "\n".join(hits)
        except Exception:
            return None

    def _check_logs(self) -> None:
        if not self.cfg.notify_on_log_errors:
            return
        err_re = re.compile(r"\b(ERROR|FATAL|PANIC)\b", re.I)

        checks = [
            (Path(LOG_PATH), "bot"),
            (NFQWS_LOG, "nfqws2"),
            (HR_NEO_LOG_DEFAULT, "hrneo"),
        ]

        restart_map = {"bot": None, "nfqws2": "nfqws:restart", "hrneo": "hydra:restart"}
        logs_map = {"bot": "logs:bot", "nfqws2": "logs:nfqws", "hrneo": "logs:hrneo"}

        for p, tag in checks:
            try:
                hit = self._tail_new_errors(p, err_re)
                if not hit:
                    continue
                if not self._cooldown_ok(f"log:{tag}"):
                    continue

                restart_cb = restart_map.get(tag)
                logs_cb = logs_map.get(tag, "logs:bot")

                self._notify_admins(
                    self._fmt_notice(
                        title=f"🧾⚠️ <b>Ошибки в логах</b> (<code>{tag}</code>)",
                        summary_lines=["Найдены строки с ERROR/FATAL/PANIC (показан хвост)."],
                        details=hit,
                        hint="Открой /menu → Логи и проверь подробности; при необходимости сделай Restart сервиса."
                    ),
                    reply_markup=kb_notice_actions(primary_cb="m:logs", restart_cb=restart_cb, logs_cb=logs_cb)
                )
            except Exception as e:
                log_line(f"check_logs error ({tag}): {repr(e)}")



    def _handle_install_cb(self, chat_id: int, msg_id: int, data: str) -> None:
        """
        Мини-инсталлятор из бота. Все действия с подтверждением.
        """
        def confirm(title: str, do_cb: str):
            self.send_or_edit(
                chat_id,
                title,
                reply_markup=kb_confirm(do_cb, "m:install"),
                message_id=msg_id,
            )

        if data == "install:hydra?confirm=1":
            confirm(
                "➕ <b>Установить HydraRoute Neo</b>\n"
                "Будет выполнено:\n"
                "<code>opkg update && opkg install curl && curl -Ls https://ground-zerro.github.io/release/keenetic/install-neo.sh | sh</code>",
                "install:hydra!do",
            )
            return
        if data == "install:hydra!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю HydraRoute Neo…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            rc, out = self.sh.sh('opkg update && opkg install curl && curl -Ls "https://ground-zerro.github.io/release/keenetic/install-neo.sh" | sh', timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:nfqws2?confirm=1":
            confirm(
                "➕ <b>Установить NFQWS2</b>\n"
                "Будет добавлен feed и установлен <code>nfqws2-keenetic</code>.",
                "install:nfqws2!do",
            )
            return
        if data == "install:nfqws2!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю NFQWS2…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            script = """set -e
opkg update
opkg install ca-certificates wget-ssl
opkg remove wget-nossl || true
mkdir -p /opt/etc/opkg
if opkg print-architecture | grep -q aarch64-3.10; then
  FEED=https://nfqws.github.io/nfqws2-keenetic/aarch64
else
  FEED=https://nfqws.github.io/nfqws2-keenetic/aarch64
fi
echo "src/gz nfqws2-keenetic $FEED" > /opt/etc/opkg/nfqws2-keenetic.conf
opkg update
opkg install nfqws2-keenetic
"""
            rc, out = self.sh.sh(script, timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:nfqwsweb?confirm=1":
            confirm(
                "➕ <b>Установить NFQWS web</b>\n"
                "Будет добавлен feed и установлен <code>nfqws-keenetic-web</code>.",
                "install:nfqwsweb!do",
            )
            return
        if data == "install:nfqwsweb!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю NFQWS web…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            script = """set -e
opkg update
opkg install ca-certificates wget-ssl
opkg remove wget-nossl || true
mkdir -p /opt/etc/opkg
echo "src/gz nfqws-keenetic-web https://nfqws.github.io/nfqws-keenetic-web/all" > /opt/etc/opkg/nfqws-keenetic-web.conf
opkg update
opkg install nfqws-keenetic-web
"""
            rc, out = self.sh.sh(script, timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:awg?confirm=1":
            confirm(
                "➕ <b>Установить AWG Manager</b>\n"
                "Будет выполнено:\n"
                "<code>curl -sL https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh | sh</code>",
                "install:awg!do",
            )
            return
        if data == "install:awg!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю AWG Manager…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            rc, out = self.sh.sh('opkg update && opkg install ca-certificates curl && curl -sL "https://raw.githubusercontent.com/hoaxisr/awg-manager/main/scripts/install.sh" | sh', timeout_sec=1200)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        if data == "install:cron?confirm=1":
            confirm(
                "➕ <b>Установить cron</b>\n"
                "Будет выполнено: <code>opkg update && opkg install cron</code>",
                "install:cron!do",
            )
            return
        if data == "install:cron!do":
            self.send_or_edit(chat_id, "⏳ Устанавливаю cron…", reply_markup=kb_home_back(back="m:install"), message_id=msg_id)
            rc, out = self.sh.sh("opkg update && opkg install cron && /opt/etc/init.d/S10cron start || true", timeout_sec=600)
            self.send_or_edit(chat_id, f"rc={rc}\n<pre><code>{escape_html(out[:3500])}</code></pre>", reply_markup=kb_install(self.capabilities()), message_id=msg_id)
            return

        self.send_or_edit(chat_id, "Нечего устанавливать или неизвестная команда.", reply_markup=kb_install(self.capabilities()), message_id=msg_id)

    def run(self) -> None:
        log_line("monitor started")
        # init baseline
        try:
            self._check_services()
            self._check_internet()
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                self._check_services()
                self._check_resources()

                now = time.time()
                if now - self._last_net_check >= self.cfg.internet_check_interval_sec:
                    self._last_net_check = now
                    self._check_internet()

                if now - self._last_opkg_check >= self.cfg.opkg_update_interval_sec:
                    self._last_opkg_check = now
                    self._check_opkg_updates()

                self._check_logs()
            except Exception as e:
                log_line(f"monitor loop error: {repr(e)}")
            self._stop.wait(self.cfg.monitor_interval_sec)


# -----------------------------
# Telegram bot app
# -----------------------------

