from __future__ import annotations

import re
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
    """Driver for AWG Manager (awg-manager).

    Notes:
      - Real API endpoints are usually /api/<group>/<action>.
      - Many non-API paths return Svelte HTML with HTTP 200; we treat those as errors.
      - Most endpoints return one of:
          * {"success": true, "data": ...}
          * {"error": true, "message": ..., "code": ...}
        but /api/health returns {"status":"ok"}.
    """

    def __init__(
        self,
        sh,
        host: str = "127.0.0.1",
        port: int = 2222,
        timeout_sec: int = 3,
        debug: bool = False,
    ):
        super().__init__(sh)
        self.host = host
        self.port = int(port)
        self.timeout_sec = max(1, int(timeout_sec))
        self.debug = bool(debug)
        self.sess = requests.Session()

    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _req(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> AwgApiResult:
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

    def _req_bytes(self, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[bool, int, bytes, Dict[str, str], str]:
        """Fetch a raw (non-JSON) resource, e.g. diagnostics report."""
        url = self.base_url() + path
        try:
            r = self.sess.get(url, params=params, timeout=max(self.timeout_sec, 10))
            if not (200 <= r.status_code < 300):
                return False, r.status_code, b"", dict(r.headers), (r.text or "").strip()[:200]
            return True, r.status_code, r.content or b"", dict(r.headers), ""
        except Exception as e:
            return False, 0, b"", {}, str(e)

    # -------- detection / identity

    def detect(self) -> bool:
        if self.opkg_installed("awg-manager", cache_ttl_sec=30) or self.opkg_installed("awgmanager", cache_ttl_sec=30):
            return True

        s = self.sh.run(
            "ls /opt/etc/init.d 2>/dev/null | grep -Eqi 'awg(-manager)?' && echo yes || echo no",
            timeout_sec=5,
            cache_ttl_sec=30,
        ).out.strip()
        if s == "yes":
            return True

        return self.health().ok

    def version(self) -> AwgApiResult:
        res = self.system_info()
        if res.ok and isinstance(res.data, dict) and "version" in res.data:
            return AwgApiResult(ok=True, status=res.status, data=str(res.data.get("version")))
        return res

    # -------- basic / status

    def health(self) -> AwgApiResult:
        return self._get("/api/health")

    def boot_status(self) -> AwgApiResult:
        return self._get("/api/boot-status")

    def auth_status(self) -> AwgApiResult:
        return self._get("/api/auth/status")

    def system_info(self) -> AwgApiResult:
        return self._get("/api/system/info")

    def wan_status(self) -> AwgApiResult:
        return self._get("/api/wan/status")

    def wan_interfaces(self) -> AwgApiResult:
        return self._get("/api/system/wan-interfaces")

    def hotspot(self) -> AwgApiResult:
        return self._get("/api/hotspot")

    # -------- tunnels

    def tunnels(self, raw: bool = False) -> Tuple[List[Any], str]:
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

    def tunnel_get(self, tunnel_id: str) -> AwgApiResult:
        return self._get("/api/tunnels/get", params={"id": tunnel_id})

    @staticmethod
    def sanitize_tunnel(data: Any, include_secrets: bool = False) -> Any:
        if include_secrets:
            return data
        if not isinstance(data, dict):
            return data
        d = dict(data)
        d.pop("configPreview", None)
        iface = d.get("interface")
        if isinstance(iface, dict):
            iface = dict(iface)
            for k in ("privateKey", "presharedKey", "i1", "i2"):
                iface.pop(k, None)
            d["interface"] = iface

        peer = d.get("peer")
        if isinstance(peer, dict):
            peer = dict(peer)
            peer.pop("presharedKey", None)
            d["peer"] = peer

        return d

    @staticmethod
    def _build_update_payload(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        allowed_top = {
            "name",
            "enabled",
            "defaultRoute",
            "ispInterface",
            "ispInterfaceLabel",
            "type",
            "interface",
            "peer",
            "pingCheck",
        }
        out: Dict[str, Any] = {}
        for k in allowed_top:
            if k in current:
                out[k] = current.get(k)

        # Remove secrets unless explicitly provided
        if isinstance(out.get("interface"), dict) and "interface" not in (patch or {}):
            iface = dict(out["interface"])
            for k in ("privateKey", "presharedKey", "i1", "i2"):
                iface.pop(k, None)
            out["interface"] = iface

        if isinstance(out.get("peer"), dict) and "peer" not in (patch or {}):
            peer = dict(out["peer"])
            peer.pop("presharedKey", None)
            out["peer"] = peer

        out.update(patch or {})
        return out

    def tunnel_update(self, tunnel_id: str, patch: Dict[str, Any]) -> AwgApiResult:
        cur = self.tunnel_get(tunnel_id)
        if not cur.ok or not isinstance(cur.data, dict):
            return cur
        payload = self._build_update_payload(cur.data, patch)
        return self._post("/api/tunnels/update", params={"id": tunnel_id}, body=payload)

    def tunnel_delete(self, tunnel_id: str) -> AwgApiResult:
        return self._post("/api/tunnels/delete", params={"id": tunnel_id})

    def tunnel_action(self, tunnel_id: str, action: str) -> AwgApiResult:
        action = (action or "").lower().strip()
        if action not in ("start", "stop", "restart"):
            return AwgApiResult(ok=False, status=0, data=None, err="unsupported action")
        return self._post(f"/api/control/{action}", params={"id": tunnel_id})

    def tunnel_toggle_default_route(self, tunnel_id: str) -> AwgApiResult:
        return self._post("/api/control/toggle-default-route", params={"id": tunnel_id})

    def traffic_history(self, tunnel_id: str, period: str = "24h") -> AwgApiResult:
        return self._get("/api/tunnels/traffic-history", params={"id": tunnel_id, "period": period})

    # -------- tests

    def test_ip_services(self) -> AwgApiResult:
        return self._get("/api/test/ip/services")

    def test_ip(self, tunnel_id: str, service: str = "") -> AwgApiResult:
        params: Dict[str, Any] = {"id": tunnel_id}
        if service:
            params["service"] = service
        return self._get("/api/test/ip", params=params)

    def test_connectivity(self, tunnel_id: str) -> AwgApiResult:
        return self._get("/api/test/connectivity", params={"id": tunnel_id})

    # -------- speedtest

    def speed_servers(self) -> AwgApiResult:
        return self._get("/api/test/speed/servers")

    def speed_test(self, tunnel_id: str, server: str, port: int, direction: str) -> AwgApiResult:
        return self._get(
            "/api/test/speed",
            params={"id": tunnel_id, "server": server, "port": int(port), "direction": direction},
        )

    # -------- logs

    def logs(self, limit: int = 200) -> AwgApiResult:
        return self._get("/api/logs", params={"limit": int(limit)})

    def logs_filtered(self, level: str = "", category: str = "", limit: int = 200) -> AwgApiResult:
        params: Dict[str, Any] = {"limit": int(limit)}
        if level:
            params["level"] = level
        if category:
            params["category"] = category
        return self._get("/api/logs", params=params)

    def logs_clear(self) -> AwgApiResult:
        return self._post("/api/logs/clear")

    # -------- pingcheck

    def pingcheck_status(self) -> AwgApiResult:
        return self._get("/api/pingcheck/status")

    def pingcheck_logs(self, tunnel_id: str = "") -> AwgApiResult:
        params: Dict[str, Any] = {}
        if tunnel_id:
            params["tunnelId"] = tunnel_id
        return self._get("/api/pingcheck/logs", params=params)

    def pingcheck_check_now(self) -> AwgApiResult:
        return self._post("/api/pingcheck/check-now")

    def pingcheck_logs_clear(self) -> AwgApiResult:
        return self._post("/api/pingcheck/logs/clear")

    # -------- diagnostics

    def diagnostics_status(self) -> AwgApiResult:
        return self._get("/api/diagnostics/status")

    def diagnostics_run(self, mode: str = "quick", restart: bool = False) -> AwgApiResult:
        body = {"mode": mode, "restart": bool(restart)}
        res = self._post("/api/diagnostics/run", body=body)
        if res.ok or res.status != 400:
            return res
        return self._post("/api/diagnostics/run")

    def diagnostics_result(self) -> Tuple[bool, str, bytes, str]:
        ok, status, content, headers, err = self._req_bytes("/api/diagnostics/result")
        if not ok:
            return False, err or f"HTTP {status}", b"", ""
        cd = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
        m = re.search(r'filename="?([^";]+)"?', cd)
        filename = m.group(1) if m else "diagnostics.json"
        ctype = headers.get("Content-Type") or headers.get("content-type") or "application/octet-stream"
        return True, filename, content, ctype

    # -------- settings / system maintenance

    def settings_get(self) -> AwgApiResult:
        return self._get("/api/settings/get")

    def settings_update(self, patch: Dict[str, Any]) -> AwgApiResult:
        cur = self.settings_get()
        if not cur.ok or not isinstance(cur.data, dict):
            return cur

        def merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
            out = dict(a)
            for k, v in (b or {}).items():
                if isinstance(v, dict) and isinstance(out.get(k), dict):
                    out[k] = merge(out[k], v)
                else:
                    out[k] = v
            return out

        new = merge(cur.data, patch or {})
        return self._post("/api/settings/update", body=new)

    def system_update_check(self, force: bool = False) -> AwgApiResult:
        return self._get("/api/system/update/check", params={"force": "true"} if force else None)

    def system_update_apply(self) -> AwgApiResult:
        return self._post("/api/system/update/apply")

    def system_change_backend(self, mode: str) -> AwgApiResult:
        return self._post("/api/system/change-backend", body={"mode": mode})

    def kmod_versions(self) -> AwgApiResult:
        return self._get("/api/system/kmod/versions")

    def kmod_swap(self, version: str) -> AwgApiResult:
        return self._post("/api/system/kmod/swap", body={"version": version})

    def kmod_download(self) -> AwgApiResult:
        return self._post("/api/system/kmod/download")

    # -------- policies / routing

    def policies_list(self) -> AwgApiResult:
        return self._get("/api/policies/list")

    def policy_create(self, payload: Dict[str, Any]) -> AwgApiResult:
        return self._post("/api/policies/create", body=payload)

    def policy_update(self, payload: Dict[str, Any]) -> AwgApiResult:
        return self._post("/api/policies/update", body=payload)

    def policy_delete(self, policy_id: str) -> AwgApiResult:
        return self._post("/api/policies/delete", params={"id": policy_id})

    def external_tunnels(self) -> AwgApiResult:
        return self._get("/api/external-tunnels")

    # -------- imports

    def import_conf(self, content: str, name: str = "") -> AwgApiResult:
        return self._post("/api/import/conf", body={"content": content, "name": name or "imported"})
