
from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from .base import DriverBase


@dataclass(frozen=True)
class AwgApiResult:
    ok: bool
    status: int
    data: Any
    err: str = ""


@dataclass(frozen=True)
class AwgTunnel:
    id: str
    name: str
    enabled: bool
    running: bool
    ip: str = ""
    endpoint: str = ""


class AwgDriver(DriverBase):
    def __init__(self, sh, host: str = "127.0.0.1", port: int = 2222, timeout_sec: int = 3, debug: bool = False):
        super().__init__(sh)
        self.host = host
        self.port = int(port)
        self.timeout_sec = max(1, int(timeout_sec))
        self.debug = bool(debug)
        self.sess = requests.Session()

    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> AwgApiResult:
        url = self.base_url() + path
        try:
            r = self.sess.get(url, params=params, timeout=self.timeout_sec)
            ct = (r.headers.get("content-type") or "").lower()
            if "application/json" in ct:
                data = r.json()
            else:
                # try json anyway
                try:
                    data = r.json()
                except Exception:
                    data = r.text
            ok = r.status_code >= 200 and r.status_code < 300
            return AwgApiResult(ok=ok, status=r.status_code, data=data, err="" if ok else str(data))
        except Exception as e:
            return AwgApiResult(ok=False, status=0, data=None, err=str(e))

    def detect(self) -> bool:
        # Package presence (different names in forks)
        cmd = """(for p in awg-manager awg amnezia-wg amneziawg; do opkg status $p >/dev/null 2>&1 && exit 0; done; exit 1)"""
        if self.sh.run(cmd + " && echo yes || echo no", timeout_sec=5, cache_ttl_sec=30).out.strip() == "yes":
            return True
        # Init scripts (some installs don't ship opkg metadata)
        init_dir = "/opt/etc/init.d"
        if os.path.isdir(init_dir):
            try:
                for n in os.listdir(init_dir):
                    nn = n.lower()
                    if "awg" in nn or "amnez" in nn:
                        return True
            except Exception:
                pass
        # Binaries
        for b in ("/opt/sbin/awg-manager", "/opt/sbin/awg", "/opt/bin/awg-manager", "/opt/bin/awg"):
            if os.path.exists(b):
                return True
        # Try API
        res = self._get("/api/version")
        return res.ok

    def version(self) -> AwgApiResult:
        res = self._get("/api/version")
        if res.ok:
            return res
        return self._get("/api/info")

    def public_ip(self) -> AwgApiResult:
        return self._get("/api/ip")

    def tunnels(self) -> Tuple[List[AwgTunnel], str]:
        res = self._get("/api/tunnels/list")
        if not res.ok:
            return [], res.err
        data = res.data
        tunnels: List[AwgTunnel] = []
        try:
            if isinstance(data, dict) and "tunnels" in data:
                items = data["tunnels"]
            else:
                items = data
            if not isinstance(items, list):
                return [], "bad response"
            for it in items:
                if not isinstance(it, dict):
                    continue
                tid = str(it.get("id", it.get("name", "")))
                name = str(it.get("name", tid))
                enabled = bool(it.get("enabled", True))
                running = bool(it.get("running", it.get("up", False)))
                ip = str(it.get("ip", it.get("address", "")) or "")
                endpoint = str(it.get("endpoint", it.get("peer", "")) or "")
                tunnels.append(AwgTunnel(id=tid, name=name, enabled=enabled, running=running, ip=ip, endpoint=endpoint))
        except Exception as e:
            return [], str(e)
        return tunnels, ""

    def tunnel_action(self, tunnel_id: str, action: str) -> AwgApiResult:
        return self._get("/api/tunnels/action", params={"id": tunnel_id, "action": action})

    def tunnel_toggle(self, tunnel_id: str) -> AwgApiResult:
        return self._get("/api/tunnels/toggle", params={"id": tunnel_id})

    def logs(self, limit: int = 200) -> AwgApiResult:
        return self._get("/api/logs", params={"limit": int(limit)})

    def speed_servers(self) -> AwgApiResult:
        return self._get("/api/test/speed/servers")

    def speed_test(self, tunnel_id: str, server: str, port: int, direction: str) -> AwgApiResult:
        return self._get("/api/test/speed", params={"id": tunnel_id, "server": server, "port": int(port), "direction": direction})
