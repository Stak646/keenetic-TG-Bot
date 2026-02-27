# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .constants import DEFAULT_CONFIG_PATH, ALT_CONFIG_PATH
from .utils import log_line

@dataclass
class BotConfig:

    bot_token: str
    admins: List[int]
    allow_chats: Optional[List[int]] = None  # если None/пусто — разрешаем личку админам
    command_timeout_sec: int = 30
    poll_interval_sec: int = 2

    monitor_enabled: bool = True
    monitor_interval_sec: int = 60
    opkg_update_interval_sec: int = 24 * 3600
    internet_check_interval_sec: int = 5 * 60

    cpu_load_threshold: float = 3.5
    disk_free_mb_threshold: int = 200

    # уведомления
    notify_on_updates: bool = True
    notify_on_service_down: bool = True
    notify_on_internet_down: bool = True
    notify_on_log_errors: bool = True

    # ограничение спама
    notify_cooldown_sec: int = 300

    # анти-спам точечно
    notify_disk_interval_sec: int = 6 * 3600
    notify_load_interval_sec: int = 30 * 60

    # debug
    debug_enabled: bool = False
    debug_log_output_max: int = 5000


def load_config(path: str) -> BotConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return BotConfig(
        bot_token=raw["bot_token"],
        admins=raw["admins"],
        allow_chats=raw.get("allow_chats"),
        command_timeout_sec=int(raw.get("command_timeout_sec", 30)),
        poll_interval_sec=int(raw.get("poll_interval_sec", 2)),
        monitor_enabled=bool(raw.get("monitor", {}).get("enabled", True)),
        monitor_interval_sec=int(raw.get("monitor", {}).get("interval_sec", 60)),
        opkg_update_interval_sec=int(raw.get("monitor", {}).get("opkg_update_interval_sec", 24 * 3600)),
        internet_check_interval_sec=int(raw.get("monitor", {}).get("internet_check_interval_sec", 5 * 60)),
        cpu_load_threshold=float(raw.get("monitor", {}).get("cpu_load_threshold", 3.5)),
        disk_free_mb_threshold=int(raw.get("monitor", {}).get("disk_free_mb_threshold", 200)),
        notify_on_updates=bool(raw.get("notify", {}).get("updates", True)),
        notify_on_service_down=bool(raw.get("notify", {}).get("service_down", True)),
        notify_on_internet_down=bool(raw.get("notify", {}).get("internet_down", True)),
        notify_on_log_errors=bool(raw.get("notify", {}).get("log_errors", True)),
        notify_cooldown_sec=int(raw.get("notify", {}).get("cooldown_sec", 300)),
        notify_disk_interval_sec=int(raw.get("notify", {}).get("disk_interval_sec", 6*3600)),
        notify_load_interval_sec=int(raw.get("notify", {}).get("load_interval_sec", 30*60)),
        debug_enabled=bool(raw.get("debug", {}).get("enabled", False)),
        debug_log_output_max=int(raw.get("debug", {}).get("log_output_max", 5000)),
    )


