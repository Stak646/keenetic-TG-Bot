
from __future__ import annotations

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

    def _req(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> AwgApiResult:
        """AWG Manager API helper.

        Many endpoints return {success:true,data:...} or {error:true,message:...}.
        Some *non-API* paths respond with HTML (Svelte app) — treat as error.
        """
        url = self.base_url() + path
        try:
            r = self.sess.request(
                method=method.upper(),
                url=url,
                params=params,
                json=body,
                headers={"Accept": "application/json"},
                timeout=self.timeout_sec,
            )
            ct = (r.headers.get("content-type") or "").lower()
            if "application/json" not in ct:
                snippet = (r.text or "").strip().replace("\n", " ")[:120]
                return AwgApiResult(ok=False, status=r.status_code, data=r.text, err=f"non-json response ({r.status_code}): {snippet}")

            data = r.json()

            # /api/health is special: {"status":"ok"}
            if isinstance(data, dict) and data.get("status") == "ok":
                return AwgApiResult(ok=True, status=r.status_code, data=data)

            # Standard wrapper
            if isinstance(data, dict) and data.get("success") is True:
                return AwgApiResult(ok=True, status=r.status_code, data=data.get("data"))

            # Error wrapper
            if isinstance(data, dict) and data.get("error") is True:
                msg = str(data.get("message") or data.get("code") or "error")
                return AwgApiResult(ok=False, status=r.status_code, data=data, err=msg)

            ok = 200 <= r.status_code < 300
            return AwgApiResult(ok=ok, status=r.status_code, data=data, err="" if ok else str(data))

        except Exception as e:
            return AwgApiResult(ok=False, status=0, data=None, err=str(e))

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> AwgApiResult:
        return self._req("GET", path, params=params)

    def _post(self, path: str, params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> AwgApiResult:
        return self._req("POST", path, params=params, body=body)

    def detect(self) -> bool:
        # Installed check (multiple package names exist across repos/forks)
        if self.opkg_installed("awg-manager", cache_ttl_sec=30) or self.opkg_installed("awgmanager", cache_ttl_sec=30):
            return True

        # Legacy/manual installs may leave an init script without an opkg record.
        s = self.sh.run(
            "ls /opt/etc/init.d 2>/dev/null | grep -Eqi 'awg(-manager)?' && echo yes || echo no",
            timeout_sec=5,
            cache_ttl_sec=30,
        ).out.strip()
        if s == "yes":
            return True

        # Try API (service may be running even if opkg metadata is absent)
        # /api/health is stable and returns JSON.
        return self._get("/api/health").ok

    def version(self) -> AwgApiResult:
        # Version is part of /api/system/info
        res = self._get("/api/system/info")
        if res.ok and isinstance(res.data, dict) and "version" in res.data:
            return AwgApiResult(ok=True, status=res.status, data=str(res.data.get("version")))
        return res

    def public_ip(self) -> AwgApiResult:
        # AWG Manager checks IP per tunnel: /api/test/ip?id=<tunnel>
        tunnels, err = self.tunnels(raw=True)
        if err or not tunnels:
            return AwgApiResult(ok=False, status=0, data=None, err=err or "no tunnels")

        tid = ""
        for t in tunnels:
            if isinstance(t, dict) and t.get("defaultRoute") is True:
                tid = str(t.get("id") or "")
                break
        if not tid:
            tid = str(tunnels[0].get("id") or "") if isinstance(tunnels[0], dict) else ""
        if not tid:
            return AwgApiResult(ok=False, status=0, data=None, err="no tunnel id")

        res = self._get("/api/test/ip", params={"id": tid})
        if res.ok and isinstance(res.data, dict):
            ip = res.data.get("ip") or res.data.get("address") or res.data.get("result")
            if ip:
                return AwgApiResult(ok=True, status=res.status, data=str(ip))
        return res

    def tunnels(self, raw: bool = False) -> Tuple[List[Any], str]:
        """Return tunnels.

        raw=False (default): List[AwgTunnel]
        raw=True: List[dict] as returned by API (/api/tunnels/list)
        """
        res = self._get("/api/tunnels/list")
        if not res.ok:
            return [], res.err

        items = res.data
        if not isinstance(items, list):
            return [], "bad response"
        if raw:
            return items, ""

        tunnels: List[AwgTunnel] = []
        try:
            for it in items:
                if not isinstance(it, dict):
                    continue
                tid = str(it.get("id") or it.get("name") or "")
                name = str(it.get("name") or tid)
                enabled = bool(it.get("enabled", True))
                status = str(it.get("status") or "").lower()
                running = status == "running" or bool(it.get("running") is True)
                ip = str(it.get("address") or "")
                endpoint = str(it.get("endpoint") or "")
                tunnels.append(AwgTunnel(id=tid, name=name, enabled=enabled, running=running, ip=ip, endpoint=endpoint))
        except Exception as e:
            return [], str(e)
        return tunnels, ""

    def tunnel_action(self, tunnel_id: str, action: str) -> AwgApiResult:
        action = (action or "").lower().strip()
        if action not in ("start", "stop", "restart"):
            return AwgApiResult(ok=False, status=0, data=None, err="unsupported action")
        return self._post(f"/api/control/{action}", params={"id": tunnel_id})

    def tunnel_toggle(self, tunnel_id: str) -> AwgApiResult:
        return self._post("/api/control/toggle-default-route", params={"id": tunnel_id})

    def logs(self, limit: int = 200) -> AwgApiResult:
        return self._get("/api/logs", params={"limit": int(limit)})

    def speed_servers(self) -> AwgApiResult:
        return self._get("/api/test/speed/servers")

    def speed_test(self, tunnel_id: str, server: str, port: int, direction: str) -> AwgApiResult:
        return self._get("/api/test/speed", params={"id": tunnel_id, "server": server, "port": int(port), "direction": direction})
