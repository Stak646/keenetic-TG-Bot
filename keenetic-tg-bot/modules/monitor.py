
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .utils.log import get_logger
from .utils.resources import detect_resources


class Monitor(threading.Thread):
    def __init__(self, app: "App"):
        super().__init__(daemon=True)
        self.app = app
        self.log = get_logger()
        self._stop = threading.Event()
        self._last_sent: Dict[str, float] = {}
        self._last_service_state: Dict[str, str] = {}

    def stop(self) -> None:
        self._stop.set()

    def _cooldown_ok(self, key: str, cooldown_sec: int) -> bool:
        now = time.time()
        last = self._last_sent.get(key, 0)
        if now - last >= cooldown_sec:
            self._last_sent[key] = now
            return True
        return False

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                # Only in debug, avoid spamming logs
                if self.app.cfg.debug:
                    self.log.error("monitor loop error: %s", e, exc_info=True)
            # sleep
            self._stop.wait(max(5, int(self.app.cfg.monitor_interval_sec)))

    def tick(self) -> None:
        cfg = self.app.cfg
        if not cfg.notify_enabled:
            return

        res = detect_resources("/opt")
        if cfg.notify_disk_enabled and res.opt_total_mb > 0:
            if res.opt_free_mb <= cfg.disk_warn_free_mb:
                if self._cooldown_ok("disk_low", cfg.notify_cooldown_sec):
                    msg = (
                        "💾⚠️ <b>Мало места на /opt</b>\n"
                        f"Свободно: <b>{res.opt_free_mb} MB</b> из {res.opt_total_mb} MB\n\n"
                        "👉 Совет: очистить логи/кэш, удалить ненужные пакеты."
                        if self.app.i18n.lang == "ru" else
                        "💾⚠️ <b>Low disk space on /opt</b>\n"
                        f"Free: <b>{res.opt_free_mb} MB</b> of {res.opt_total_mb} MB\n\n"
                        "👉 Tip: clean logs/cache, remove unused packages."
                    )
                    self.app.notify_admins(msg)

        # Service state change notifications (best-effort)
        if cfg.notify_services_enabled:
            # check core bot process is running is pointless; check components
            for comp_id, comp in self.app.components.items():
                try:
                    st = comp.quick_status()
                except Exception:
                    continue
                if not st:
                    continue
                prev = self._last_service_state.get(comp_id)
                if prev is None:
                    self._last_service_state[comp_id] = st
                    continue
                if st != prev:
                    self._last_service_state[comp_id] = st
                    if self._cooldown_ok(f"svc_{comp_id}", cfg.notify_cooldown_sec):
                        title = comp.title(self.app.i18n)
                        self.app.notify_admins(f"🔔 <b>{title}</b>: {st}")
