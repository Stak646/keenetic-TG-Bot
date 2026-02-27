
from __future__ import annotations

import fcntl
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import telebot
from telebot.apihelper import ApiTelegramException

from .monitor import Monitor
from .ui import Screen, kb, btn, nav_home
from .utils.config import AppConfig, save_config
from .utils.i18n import I18N
from .utils.log import get_logger, log_exception
from .utils.resources import detect_resources, recommend_threads
from .utils.shell import Shell
from .utils.text import esc, pre


def parse_cb(data: str) -> Tuple[str, str, Dict[str, str]]:
    """
    callback_data format: "mod|cmd|k=v&k2=v2"
    cmd may be absent => "m"
    """
    if not data:
        return "", "", {}
    if data == "noop":
        return "noop", "noop", {}
    parts = data.split("|", 2)
    mod = parts[0]
    cmd = parts[1] if len(parts) > 1 and parts[1] else "m"
    qs = parts[2] if len(parts) > 2 else ""
    params: Dict[str, str] = {}
    if qs:
        for seg in qs.split("&"):
            if not seg:
                continue
            if "=" in seg:
                k, v = seg.split("=", 1)
                params[k] = v
            else:
                params[seg] = ""
    return mod, cmd, params


class App:
    def __init__(self, cfg: AppConfig, cfg_path: str):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.i18n = I18N(cfg.language)
        self.log = get_logger()

        self.sh = Shell(timeout_sec=cfg.shell_timeout_sec, cache_ttl_sec=cfg.cache_ttl_sec, debug=cfg.debug)

        res = detect_resources("/opt")
        auto_threads = recommend_threads(res.mem_total_mb, res.cpu_cores)
        self.telegram_threads = auto_threads if str(cfg.telegram_threads).lower() == "auto" else max(1, int(cfg.telegram_threads))
        self.executor_workers = auto_threads if str(cfg.executor_workers).lower() == "auto" else max(1, int(cfg.executor_workers))

        # Telegram API helper timeouts (avoid hanging requests)
        telebot.apihelper.CONNECT_TIMEOUT = 5
        telebot.apihelper.READ_TIMEOUT = 20

        self.bot = telebot.TeleBot(
            cfg.bot_token,
            parse_mode="HTML",
            disable_web_page_preview=True,
            threaded=True,
            num_threads=self.telegram_threads,
        )

        self.executor = ThreadPoolExecutor(max_workers=self.executor_workers)

        self.components: Dict[str, Any] = {}
        self.monitor = Monitor(self)

        self._pending_input: Dict[int, str] = {}  # chat_id -> type
        self._session: Dict[int, Dict[str, Any]] = {}  # chat_id -> dict

        # context for long jobs (set in callback handler)
        self.last_chat_id: int = 0
        self.last_message_id: int = 0
        self.last_user_id: int = 0

        self._lock_fh = None

    # -------- config helpers

    def save_cfg(self) -> None:
        try:
            save_config(self.cfg, self.cfg_path)
        except Exception as e:
            self.log.error("failed to save config: %s", e)

    def set_language(self, lang: str) -> None:
        lang = (lang or "ru").lower()
        self.cfg.language = "en" if lang.startswith("en") else "ru"
        self.i18n = I18N(self.cfg.language)
        self.save_cfg()

    def set_debug(self, on: bool) -> None:
        self.cfg.debug = bool(on)
        # update logger level for our logger
        try:
            lvl = "DEBUG" if self.cfg.debug else "INFO"
            self.log.setLevel(lvl)
            for h in self.log.handlers:
                h.setLevel(lvl)
        except Exception:
            pass
        # update shell debug
        try:
            self.sh.debug = self.cfg.debug
        except Exception:
            pass
        self.save_cfg()

    # -------- access control

    def is_admin(self, user_id: int) -> bool:
        if not self.cfg.admins:
            # if admins list is empty, allow everyone (but better to set admins)
            return True
        return int(user_id) in set(self.cfg.admins)

    # -------- session / pending

    def set_pending_input(self, chat_id: int, kind: str) -> None:
        self._pending_input[int(chat_id)] = kind

    def pop_pending_input(self, chat_id: int) -> Optional[str]:
        return self._pending_input.pop(int(chat_id), None)

    def session_set(self, key: str, value: Any) -> None:
        chat_id = int(self.last_chat_id)
        self._session.setdefault(chat_id, {})[key] = value

    def session_get(self, key: str, default: Any = None) -> Any:
        chat_id = int(self.last_chat_id)
        return self._session.get(chat_id, {}).get(key, default)

    # -------- UI

    def home_screen(self) -> Screen:
        i18n = self.i18n
        rows = [
            [btn(i18n.t("home.router"), "r|m"), btn(i18n.t("home.components"), "c|m")],
            [btn(i18n.t("home.opkg"), "o|m"), btn(i18n.t("home.settings"), "st|m")],
            [btn(i18n.t("home.hydra"), "hy|m"), btn(i18n.t("home.nfqws"), "nq|m")],
            [btn(i18n.t("home.awg"), "aw|m"), btn(i18n.t("home.speed"), "sp|m")],
        ]
        return Screen(text=f"{i18n.t('home.header')}\n\n{i18n.t('home.subtitle')}", kb=kb(rows))

    def send_screen(self, chat_id: int, screen: Screen) -> None:
        try:
            self.bot.send_message(chat_id, screen.text, reply_markup=screen.kb, disable_web_page_preview=screen.disable_preview)
        except Exception as e:
            self.log.error("send_screen error: %s", e)

    def edit_or_send(self, chat_id: int, message_id: int, screen: Screen) -> None:
        try:
            self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=screen.text,
                reply_markup=screen.kb,
                disable_web_page_preview=screen.disable_preview,
            )
        except Exception:
            # fallback: send new
            self.send_screen(chat_id, screen)

    def notify_admins(self, html_text: str) -> None:
        for admin_id in self.cfg.admins or []:
            try:
                self.bot.send_message(int(admin_id), html_text, disable_web_page_preview=True)
            except Exception:
                continue

    # -------- long jobs with "animation"

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def run_long_job(
        self,
        title: str,
        job: Callable[[], Any],
        back: str,
        title_prefix: str = "",
    ) -> Screen:
        """
        Schedule a potentially long blocking job (opkg install, speedtest...) in background.
        Returns an immediate 'running' screen; the message will be edited when job finishes.
        Requires last_chat_id and last_message_id to be set by the handler.
        """
        chat_id = int(self.last_chat_id)
        msg_id = int(self.last_message_id)
        i18n = self.i18n

        head = title_prefix or title
        running_text = f"{self._SPINNER[0]} <b>{esc(head)}</b>\n\n{esc(title)}"
        running_kb = kb([[btn(i18n.t("btn.back"), back), nav_home(i18n)]])

        # Start spinner updater in a thread
        done = threading.Event()

        def spinner():
            idx = 0
            while not done.is_set():
                idx = (idx + 1) % len(self._SPINNER)
                try:
                    self.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=f"{self._SPINNER[idx]} <b>{esc(head)}</b>\n\n{esc(title)}",
                        reply_markup=running_kb,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
                done.wait(1.2)

        self.executor.submit(spinner)

        def runner():
            try:
                result = job()
                text = self.format_job_result(head, result)
                screen = Screen(
                    text=text,
                    kb=kb([[btn(i18n.t("btn.back"), back), nav_home(i18n)]]),
                )
                done.set()
                time.sleep(0.2)
                self.edit_or_send(chat_id, msg_id, screen)
            except Exception as e:
                log_exception(self.log, "long job failed", e)
                screen = Screen(
                    text=f"❌ <b>{esc(head)}</b>\n\n{esc(str(e))}",
                    kb=kb([[btn(i18n.t("btn.back"), back), nav_home(i18n)]]),
                )
                done.set()
                time.sleep(0.2)
                self.edit_or_send(chat_id, msg_id, screen)
            finally:
                done.set()

        self.executor.submit(runner)
        return Screen(text=running_text, kb=running_kb)

    def format_job_result(self, head: str, result: Any) -> str:
        """
        Convert different result objects to human-readable HTML.
        """
        # duck-typing for known shapes
        if hasattr(result, "ok") and hasattr(result, "out"):
            # OpkgResult-like
            ok = bool(getattr(result, "ok"))
            out = str(getattr(result, "out", "") or "")
            err = str(getattr(result, "err", "") or "")
            status = "✅" if ok else "❌"
            body = out or err or ""
            return f"{status} <b>{esc(head)}</b>\n\n{pre(body)}"

        if hasattr(result, "installed") and hasattr(result, "running"):
            ok = bool(getattr(result, "installed")) and bool(getattr(result, "running"))
            status = "✅" if ok else "⚠️"
            detail = str(getattr(result, "detail", "") or "")
            return f"{status} <b>{esc(head)}</b>\n\n{pre(detail or str(result))}"

        if hasattr(result, "ok") and hasattr(result, "data"):
            ok = bool(getattr(result, "ok"))
            status = "✅" if ok else "❌"
            data = getattr(result, "data")
            err = str(getattr(result, "err", "") or "")
            body = str(data) if ok else err
            return f"{status} <b>{esc(head)}</b>\n\n{pre(body)}"

        if hasattr(result, "cmd") and hasattr(result, "rc"):
            ok = int(getattr(result, "rc")) == 0
            status = "✅" if ok else "❌"
            out = str(getattr(result, "out", "") or "")
            err = str(getattr(result, "err", "") or "")
            body = out or err
            return f"{status} <b>{esc(head)}</b>\n\n{pre(body)}"

        # SpeedTestResult
        if hasattr(result, "method") and hasattr(result, "ok"):
            ok = bool(getattr(result, "ok"))
            status = "✅" if ok else "❌"
            dl = getattr(result, "download_mbps", None)
            ul = getattr(result, "upload_mbps", None)
            ping = getattr(result, "ping_ms", None)
            server = getattr(result, "server", "")
            lines = [f"method: {getattr(result, 'method', '')}"]
            if server:
                lines.append(f"server: {server}")
            if dl is not None:
                lines.append(f"download: {dl} Mbps")
            if ul is not None:
                lines.append(f"upload: {ul} Mbps")
            if ping is not None:
                lines.append(f"ping: {ping} ms")
            raw = getattr(result, "raw", "") or ""
            if raw and (not ok):
                lines.append(f"raw: {raw}")
            return f"{status} <b>{esc(head)}</b>\n\n{pre(chr(10).join(lines))}"

        return f"✅ <b>{esc(head)}</b>\n\n{pre(str(result))}"

    # -------- lifecycle

    def acquire_lock(self) -> bool:
        """
        Prevent running 2 bot processes on the same router.
        """
        lock_path = "/opt/var/run/keenetic-tg-bot.lock"
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        try:
            fh = open(lock_path, "w")
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fh.write(str(os.getpid()))
            fh.flush()
            self._lock_fh = fh
            return True
        except Exception:
            return False

    def register(self) -> None:
        i18n = self.i18n

        @self.bot.message_handler(commands=["start", "help"])
        def _start(m):
            if not self.is_admin(m.from_user.id):
                self.bot.send_message(m.chat.id, i18n.t("err.no_access"))
                return
            self.send_screen(m.chat.id, self.home_screen())

        @self.bot.message_handler(commands=["home"])
        def _home(m):
            if not self.is_admin(m.from_user.id):
                return
            self.send_screen(m.chat.id, self.home_screen())

        @self.bot.message_handler(func=lambda m: True, content_types=["text"])
        def _text(m):
            if not self.is_admin(m.from_user.id):
                return
            kind = self.pop_pending_input(m.chat.id)
            if kind == "opkg_search":
                q = (m.text or "").strip()
                # render opkg search results by callback-style invocation
                self.last_chat_id = m.chat.id
                self.last_message_id = 0
                # send as new message
                comp = self.components.get("o")
                if comp:
                    screen = comp.render(self, "search_do", {"q": q})
                    self.send_screen(m.chat.id, screen)
                return
            # Default: show home
            self.send_screen(m.chat.id, self.home_screen())

        @self.bot.callback_query_handler(func=lambda call: True)
        def _cb(call):
            try:
                self.bot.answer_callback_query(call.id, text="")
            except Exception:
                pass

            if call.data == "noop":
                return

            if not self.is_admin(call.from_user.id):
                try:
                    self.bot.answer_callback_query(call.id, text=self.i18n.t("err.no_access"), show_alert=True)
                except Exception:
                    pass
                return

            self.last_chat_id = call.message.chat.id
            self.last_message_id = call.message.message_id
            self.last_user_id = call.from_user.id

            mod, cmd, params = parse_cb(call.data)
            if mod == "h":
                screen = self.home_screen()
                self.edit_or_send(call.message.chat.id, call.message.message_id, screen)
                return

            comp = self.components.get(mod)
            if not comp:
                self.edit_or_send(call.message.chat.id, call.message.message_id, Screen(text=self.i18n.t("err.not_found"), kb=kb([[nav_home(self.i18n)]])))
                return

            try:
                screen = comp.render(self, cmd, params)
            except Exception as e:
                log_exception(self.log, f"render error {mod}.{cmd}", e)
                screen = Screen(text=self.i18n.t("err.try_again"), kb=kb([[nav_home(self.i18n)]]))
            self.edit_or_send(call.message.chat.id, call.message.message_id, screen)

    def start(self) -> None:
        if not self.acquire_lock():
            self.log.error("Another instance is running (lock file). Exiting.")
            return

        # Reset webhook (prevents 409 if webhook was set)
        try:
            self.bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass

        self.register()
        self.monitor.start()

        # Polling loop with backoff
        backoff = 2
        while True:
            try:
                self.bot.infinity_polling(timeout=20, long_polling_timeout=20)
            except ApiTelegramException as e:
                # 409 conflict -> likely another getUpdates
                self.log.error("Telegram API error: %s", e)
                time.sleep(backoff)
                backoff = min(60, backoff * 2)
            except Exception as e:
                self.log.error("Polling error: %s", e, exc_info=True)
                time.sleep(backoff)
                backoff = min(60, backoff * 2)
