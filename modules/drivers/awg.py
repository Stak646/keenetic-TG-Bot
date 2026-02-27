# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
import socket
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ..constants import *
from ..utils import *
from ..shell import Shell
from .opkg import OpkgDriver
from .router import RouterDriver

class AwgDriver:
    def __init__(self, sh: Shell, opkg: OpkgDriver, router: RouterDriver):
        self.sh = sh
        self.opkg = opkg
        self.router = router

    def installed(self) -> bool:
        return AWG_INIT.exists() or which("awg-manager") is not None or Path("/opt/bin/awg-manager").exists()

    def init_action(self, action: str) -> Tuple[int, str]:
        if AWG_INIT.exists():
            return self.sh.run([str(AWG_INIT), action], timeout_sec=30)
        # fallback
        if which("awg-manager"):
            return self.sh.run(["awg-manager", "--service", action], timeout_sec=30)
        return 127, "awg-manager не найден"

    def web_port(self) -> int:
        # settings.json содержит порт (install.sh: /opt/etc/awg-manager/settings.json)
        if AWG_SETTINGS.exists():
            try:
                raw = json.loads(AWG_SETTINGS.read_text(encoding="utf-8"))
                p = int(raw.get("port") or raw.get("listenPort") or raw.get("listen_port") or 2222)
                if 1 <= p <= 65535:
                    return p
            except Exception:
                pass
        return 2222

    def web_url(self) -> str:
        return f"http://{self.router.lan_ip()}:{self.web_port()}"

    def health_check(self) -> Tuple[bool, str]:
        # без внешних зависимостей: пробуем curl/wget, иначе сокетом
        port = self.web_port()
        url = f"http://127.0.0.1:{port}/api/health"
        if which("curl"):
            rc, out = self.sh.run(["curl", "-sS", "--max-time", "3", url], timeout_sec=5)
            return (rc == 0 and out != ""), out if out else ("curl error" if rc != 0 else "empty")
        if which("wget"):
            rc, out = self.sh.run(["wget", "-qO-", url], timeout_sec=5)
            return (rc == 0 and out != ""), out if out else ("wget error" if rc != 0 else "empty")
        # минимальный HTTP GET через socket
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=3)
            req = f"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            s.sendall(req.encode("ascii"))
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            s.close()
            text = data.decode("utf-8", errors="replace")
            # crude parse
            body = text.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in text else text
            return True, body.strip()[:1000]
        except Exception as e:
            return False, str(e)


    def api_request(self, endpoint: str, method: str = "GET", body: Optional[dict] = None, timeout: int = 8) -> Tuple[bool, str, Optional[dict]]:
        """
        Универсальный запрос к AWG Manager API.
        endpoint: путь после /api, например '/tunnels/list'
        Возвращает (ok, message, json_dict)
        """
        port = self.web_port()
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = f"http://127.0.0.1:{port}/api{endpoint}"

        data = None
        headers = {
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        try:
            req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                ct = resp.headers.get("Content-Type", "")
        except Exception as e:
            return False, f"HTTP error: {e}", None

        if "application/json" not in (ct or ""):
            # иногда может отдать html
            return False, f"Non-JSON response ({ct}): {raw[:200]}", None

        try:
            j = json.loads(raw)
        except Exception as e:
            return False, f"JSON parse error: {e}", None

        # Частый формат: {error, message, data}
        if isinstance(j, dict) and (j.get("error") or j.get("success") is False):
            return False, j.get("message") or j.get("error") or "API error", j

        data_obj = j.get("data") if isinstance(j, dict) else j
        return True, "OK", data_obj if isinstance(data_obj, (dict, list)) else j

    def api_get(self, endpoint: str, timeout: int = 8) -> Tuple[bool, str, Optional[dict]]:
        return self.api_request(endpoint, "GET", None, timeout)

    def api_post(self, endpoint: str, body: Optional[dict] = None, timeout: int = 12) -> Tuple[bool, str, Optional[dict]]:
        return self.api_request(endpoint, "POST", body, timeout)

    def api_quick_summary(self) -> str:
        ok1, msg1, sysinfo = self.api_get("/system/info")
        ok2, msg2, wan = self.api_get("/wan/status")
        ok3, msg3, st = self.api_get("/status/all")
        parts = []
        parts.append("API: " + ("✅" if (ok1 or ok2 or ok3) else "⚠️"))
        if ok1 and isinstance(sysinfo, dict):
            # попытка вытащить пару полей
            parts.append(f"Версия: {sysinfo.get('version') or sysinfo.get('appVersion') or '?'}")
            parts.append(f"Backend: {sysinfo.get('backend') or sysinfo.get('mode') or '?'}")
        if ok2 and isinstance(wan, (dict, list)):
            parts.append("WAN: OK")
        if ok3 and isinstance(st, (dict, list)):
            parts.append("Tunnels status: OK")
        if not parts:
            return f"API недоступен: {msg1 or msg2 or msg3}"
        return "\n".join(parts)
    def wg_status(self) -> str:
        # Пытаемся показать wg/amneziawg
        if which("wg"):
            rc, out = self.sh.run(["wg", "show"], timeout_sec=10)
            return out if rc == 0 and out else (out or "wg show пусто/ошибка")
        if which("amneziawg"):
            rc, out = self.sh.run(["amneziawg", "show"], timeout_sec=10)
            return out if rc == 0 and out else (out or "amneziawg show пусто/ошибка")
        return "Не найдено: wg/amneziawg."

    def status_text(self) -> str:
        parts = ["🧿 <b>AWG Manager</b>"]
        if not self.installed():
            parts.append("Не установлено.")
            return "\n".join(parts)
        rc, out = self.init_action("status")
        parts.append(f"• Service: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
        if out:
            parts.append(f"{fmt_code(strip_ansi(out)[:3500])}")
        if NFQWS_WEB_CONF.exists() or Path("/opt/share/nfqws-web").exists() or ("nfqws-keenetic-web" in self.opkg.target_versions()):
            parts.append(f"• WebUI: <code>{self.web_url()}</code>")
        else:
            parts.append("• WebUI: ➖ (не установлен)")
        ok, h = self.health_check()
        parts.append(f"• Health: {'✅' if ok else '⚠️'} <code>{escape_html(h[:500])}</code>")
        vers = self.opkg.target_versions()
        if "awg-manager" in vers:
            parts.append(f"• awg-manager: <code>{escape_html(vers['awg-manager'])}</code>")
        return "\n".join(parts)


# -----------------------------
# Парсеры конфигов (env-like)
# -----------------------------
