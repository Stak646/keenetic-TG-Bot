
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG_PATHS = [
    "/opt/etc/keenetic-tg-bot/config/config.json",
    "/opt/etc/keenetic-tg-bot/config.json",  # legacy
]


def _deep_get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


@dataclass
class AppConfig:
    bot_token: str = ""
    admins: List[int] = field(default_factory=list)
    language: str = "ru"  # 'ru' or 'en'

    # Performance
    debug: bool = False
    telegram_threads: str = "auto"  # or int
    executor_workers: str = "auto"  # or int
    shell_timeout_sec: int = 8
    cache_ttl_sec: int = 3

    # Notifications / monitor
    notify_enabled: bool = True
    notify_disk_enabled: bool = True
    notify_updates_enabled: bool = True
    notify_services_enabled: bool = True
    notify_cooldown_sec: int = 3600  # per-event cooldown
    monitor_interval_sec: int = 60
    disk_warn_free_mb: int = 64  # threshold for /opt

    # AWG API
    awg_host: str = "127.0.0.1"
    awg_port: int = 2222
    awg_timeout_sec: int = 3

    # HydraRoute
    hydra_web_port: int = 2000

    # NFQWS web
    nfqws_web_port: int = 80  # best-effort, may differ

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AppConfig":
        cfg = cls()
        cfg.bot_token = str(d.get("bot_token", d.get("token", "")) or "").strip()
        admins = d.get("admins") or d.get("admin_ids") or []
        if isinstance(admins, (int, str)):
            admins = [admins]
        cfg.admins = [int(x) for x in admins if str(x).strip().lstrip("-").isdigit()]
        lang = str(d.get("language", d.get("lang", cfg.language)) or cfg.language).lower()
        cfg.language = "en" if lang.startswith("en") else "ru"

        perf = d.get("performance") or {}
        cfg.debug = bool(perf.get("debug", d.get("debug", cfg.debug)))
        cfg.telegram_threads = str(perf.get("telegram_threads", cfg.telegram_threads))
        cfg.executor_workers = str(perf.get("executor_workers", cfg.executor_workers))
        cfg.shell_timeout_sec = int(perf.get("shell_timeout_sec", cfg.shell_timeout_sec))
        cfg.cache_ttl_sec = int(perf.get("cache_ttl_sec", cfg.cache_ttl_sec))

        notify = d.get("notify") or {}
        cfg.notify_enabled = bool(notify.get("enabled", cfg.notify_enabled))
        cfg.notify_disk_enabled = bool(notify.get("disk", cfg.notify_disk_enabled))
        cfg.notify_updates_enabled = bool(notify.get("updates", cfg.notify_updates_enabled))
        cfg.notify_services_enabled = bool(notify.get("services", cfg.notify_services_enabled))
        cfg.notify_cooldown_sec = int(notify.get("cooldown_sec", cfg.notify_cooldown_sec))
        cfg.monitor_interval_sec = int(notify.get("monitor_interval_sec", cfg.monitor_interval_sec))
        cfg.disk_warn_free_mb = int(notify.get("disk_warn_free_mb", cfg.disk_warn_free_mb))

        awg = d.get("awg") or {}
        cfg.awg_host = str(awg.get("host", cfg.awg_host))
        cfg.awg_port = int(awg.get("port", cfg.awg_port))
        cfg.awg_timeout_sec = int(awg.get("timeout_sec", cfg.awg_timeout_sec))

        hydra = d.get("hydra") or {}
        cfg.hydra_web_port = int(hydra.get("web_port", cfg.hydra_web_port))

        nfqws = d.get("nfqws") or {}
        cfg.nfqws_web_port = int(nfqws.get("web_port", cfg.nfqws_web_port))

        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bot_token": self.bot_token,
            "admins": self.admins,
            "language": self.language,
            "performance": {
                "debug": self.debug,
                "telegram_threads": self.telegram_threads,
                "executor_workers": self.executor_workers,
                "shell_timeout_sec": self.shell_timeout_sec,
                "cache_ttl_sec": self.cache_ttl_sec,
            },
            "notify": {
                "enabled": self.notify_enabled,
                "disk": self.notify_disk_enabled,
                "updates": self.notify_updates_enabled,
                "services": self.notify_services_enabled,
                "cooldown_sec": self.notify_cooldown_sec,
                "monitor_interval_sec": self.monitor_interval_sec,
                "disk_warn_free_mb": self.disk_warn_free_mb,
            },
            "awg": {
                "host": self.awg_host,
                "port": self.awg_port,
                "timeout_sec": self.awg_timeout_sec,
            },
            "hydra": {"web_port": self.hydra_web_port},
            "nfqws": {"web_port": self.nfqws_web_port},
        }


def load_config(path: Optional[str] = None) -> AppConfig:
    candidates = [path] if path else []
    candidates += DEFAULT_CONFIG_PATHS
    for p in candidates:
        if not p:
            continue
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                return AppConfig.from_dict(d if isinstance(d, dict) else {})
        except Exception:
            continue
    return AppConfig()


def save_config(cfg: AppConfig, path: str) -> None:
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
