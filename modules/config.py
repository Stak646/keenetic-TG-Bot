# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

from .constants import DEFAULT_CONFIG_PATH
from .utils import log_line

ALT_CONFIG_PATHS = [
    "/opt/etc/keenetic-tg-bot/config/config.json",
    "/opt/etc/keenetic-tg-bot/config.json",
    "/opt/etc/keenetic-tg-bot/config/config.json",
]

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


def load_config_file() -> str:
    # env override
    p = os.environ.get("BOT_CONFIG")
    if p and os.path.exists(p):
        return p
    for p in ALT_CONFIG_PATHS:
        if os.path.exists(p):
            return p
    return DEFAULT_CONFIG_PATH


def load_config(path: str) -> BotConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # admins: list of ints
    admins = []
    for x in (raw.get("admins") or raw.get("admin_ids") or []):
        try:
            admins.append(int(x))
        except Exception:
            pass

    return BotConfig(
        bot_token=str(raw.get("bot_token", "")).strip(),
        admins=admins,
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
        notify_disk_interval_sec=int(raw.get("notify", {}).get("disk_interval_sec", 6 * 3600)),
        notify_load_interval_sec=int(raw.get("notify", {}).get("load_interval_sec", 30 * 60)),
        debug_enabled=bool(raw.get("debug", {}).get("enabled", False)),
        debug_log_output_max=int(raw.get("debug", {}).get("log_output_max", 5000)),
    )


def load_config_or_exit() -> BotConfig:
    path = load_config_file()
    try:
        cfg = load_config(path)
        if not cfg.bot_token or not cfg.admins:
            raise ValueError("bot_token/admins missing")
        return cfg
    except Exception as e:
        log_line(f"Config error at {path}: {e}")
        raise
