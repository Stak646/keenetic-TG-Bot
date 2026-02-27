# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ..constants import *
from ..utils import *
from ..shell import Shell

from .opkg import OpkgDriver
from .router import RouterDriver

class NfqwsDriver:
    def __init__(self, sh: Shell, opkg: OpkgDriver, router: RouterDriver):
        self.sh = sh
        self.opkg = opkg
        self.router = router

    def installed(self) -> bool:
        return NFQWS_INIT.exists() or which("nfqws2") is not None

    def init_action(self, action: str) -> Tuple[int, str]:
        if NFQWS_INIT.exists():
            return self.sh.run([str(NFQWS_INIT), action], timeout_sec=30)
        # fallback: try service
        return 127, "init-скрипт nfqws2 не найден"

    def status_text(self) -> str:
        parts = ["🧷 <b>NFQWS2</b>"]
        if not self.installed():
            parts.append("Не установлено.")
            return "\n".join(parts)
        rc, out = self.init_action("status")
        parts.append(f"• Service: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
        if out:
            parts.append(f"{fmt_code(strip_ansi(out)[:3500])}")

        # конфиг summary
        if NFQWS_CONF.exists():
            ok, txt = self.sh.read_file(NFQWS_CONF, max_bytes=60_000)
            if ok:
                # вытащим пару ключей
                kv = parse_env_like(txt)
                iface = kv.get("ISP_INTERFACE") or kv.get("ISP_IFACE") or kv.get("IFACE") or "?"
                ipv6 = kv.get("IPV6_ENABLED") or kv.get("IPV6") or "?"
                mode = kv.get("MODE") or kv.get("NFQWS_MODE")
                if not mode:
                    m = re.search(r"--mode(?:=|\s+)(\S+)", txt)
                    if m:
                        mode = m.group(1)
                mode = mode or "?"
                parts.append(f"• iface: <code>{escape_html(str(iface))}</code>  ipv6: <code>{escape_html(str(ipv6))}</code>  mode: <code>{escape_html(str(mode))}</code>")

        parts.append(f"• Logs: <code>{NFQWS_LOG}</code>")
        if NFQWS_WEB_CONF.exists() or Path("/opt/share/nfqws-web").exists() or ("nfqws-keenetic-web" in self.opkg.target_versions()):
            parts.append(f"• WebUI: <code>{self.web_url()}</code>")
        else:
            parts.append("• WebUI: ➖ (не установлен)")
        return "\n".join(parts)

    def web_url(self) -> str:
        ip = self.router.lan_ip()
        port = self.web_port()
        return f"http://{ip}:{port}"

    def web_port(self) -> int:
        # по умолчанию 90 (как в описаниях), но пытаемся прочитать конфиг
        if NFQWS_WEB_CONF.exists():
            ok, txt = self.sh.read_file(NFQWS_WEB_CONF, max_bytes=40_000)
            if ok:
                # ищем первое число порта
                m = re.search(r"\bport\s*=\s*(\d+)\b", txt, flags=re.I)
                if not m:
                    m = re.search(r"\bPORT\s*=\s*(\d+)\b", txt)
                if m:
                    p = int(m.group(1))
                    if 1 <= p <= 65535:
                        return p
        return 90

    def lists_stats(self) -> str:
        if not NFQWS_LISTS_DIR.exists():
            return "lists/ не найден."
        rows = []
        for fn in sorted(NFQWS_LISTS_DIR.glob("*.list")):
            try:
                cnt = sum(1 for _ in open(fn, "r", encoding="utf-8", errors="ignore") if _.strip() and not _.lstrip().startswith("#"))
            except Exception:
                cnt = -1
            rows.append(f"{fn.name}: {cnt}")
        return "\n".join(rows) if rows else "Нет *.list"

    def add_to_list(self, list_name: str, domains: List[str]) -> Tuple[bool, str]:
        target = NFQWS_LISTS_DIR / list_name
        if not target.exists():
            return False, f"Файл не найден: {target}"
        ok_domains = []
        for d in domains:
            d = d.strip().lower()
            if not d:
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9\.-]{1,250}[a-z0-9]", d) or re.fullmatch(r"[a-z0-9]{1,63}", d):
                ok_domains.append(d)
        if not ok_domains:
            return False, "Нет валидных доменов."
        # читаем/дописываем уникально
        try:
            existing = set()
            with open(target, "r", encoding="utf-8", errors="ignore") as f:
                for ln in f:
                    ln = ln.strip().lower()
                    if ln and not ln.startswith("#"):
                        existing.add(ln)
            new = [d for d in ok_domains if d not in existing]
            if not new:
                return True, "Уже есть в списке."
            bkp = self.sh.backup_file(target)
            with open(target, "a", encoding="utf-8") as f:
                for d in new:
                    f.write(d + "\n")
            # reload
            self.init_action("reload")
            return True, f"Добавлено: {', '.join(new)}\nФайл: {target}" + (f"\nБэкап: {bkp}" if bkp else "")
        except Exception as e:
            return False, f"Ошибка: {e}"

    def clear_list(self, list_name: str) -> Tuple[bool, str]:
        target = NFQWS_LISTS_DIR / list_name
        if not target.exists():
            return False, f"Файл не найден: {target}"
        ok, msg = self.sh.write_file(target, "")
        if ok:
            self.init_action("reload")
        return ok, msg + ("\nreload выполнен." if ok else "")

    def diag_iptables_queue(self) -> str:
        if not which("iptables"):
            return "iptables не найден."
        # ищем NFQUEUE 300 (по докам nfqws2 использует queue-num 300)
        rc, out = self.sh.run(["iptables", "-t", "mangle", "-S"], timeout_sec=20)
        if rc != 0:
            return out or "Ошибка iptables"
        q_lines = [ln for ln in out.splitlines() if "NFQUEUE" in ln or "queue-num" in ln]
        if not q_lines:
            return "Не нашёл правил NFQUEUE в iptables -t mangle."
        # подсветим queue-num 300
        show = []
        for ln in q_lines[:80]:
            show.append(ln)
        if len(q_lines) > 80:
            show.append("… (обрезано)")
        return "\n".join(show)
