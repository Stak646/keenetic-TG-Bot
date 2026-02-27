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

class HydraRouteDriver:
    def __init__(self, sh: Shell, opkg: OpkgDriver, router: RouterDriver):
        self.sh = sh
        self.opkg = opkg
        self.router = router

    def is_neo_available(self) -> bool:
        return which("neo") is not None or Path("/opt/bin/neo").exists()

    def is_classic_available(self) -> bool:
        return which("hr") is not None or Path("/opt/bin/hr").exists()

    def neo_cmd(self, sub: str) -> Tuple[int, str]:
        # Управление из документации: neo start/stop/restart/status
        return self.sh.run(["neo", sub], timeout_sec=30)

    def classic_cmd(self, sub: str) -> Tuple[int, str]:
        return self.sh.run(["hr", sub], timeout_sec=30)

    def status_text(self) -> str:
        parts = ["🧬 <b>HydraRoute</b>"]
        if self.is_neo_available():
            rc, out = self.neo_cmd("status")
            parts.append(f"• Neo: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
            if out:
                parts.append(f"{fmt_code(strip_ansi(out)[:3500])}")
            if ("hrweb" in self.opkg.target_versions()) or Path("/opt/share/hrweb").exists() or Path("/opt/etc/init.d/S50hrweb").exists():
                parts.append(f"• HRweb: <code>http://{self.router.lan_ip()}:2000</code>")
            else:
                parts.append("• HRweb: ➖ (не установлен)")
        elif self.is_classic_available():
            rc, out = self.classic_cmd("status")
            parts.append(f"• Classic: {'✅ RUNNING' if rc == 0 else '⛔ STOPPED'}")
            if out:
                parts.append(f"{fmt_code(strip_ansi(out)[:3500])}")
        else:
            parts.append("Не найдено (нет neo/hr).")
        # Версии пакетов
        vers = self.opkg.target_versions()
        for k in ("hrneo", "hrweb", "hydraroute"):
            if k in vers:
                parts.append(f"• {k}: <code>{escape_html(vers[k])}</code>")
        return "\n".join(parts)

    def installed_variant(self) -> str:
        if self.is_neo_available():
            return "neo"
        if self.is_classic_available():
            return "classic"
        return "none"

    def diag_ipset(self) -> str:
        if not which("ipset"):
            return "ipset не установлен/не найден."
        rc, out = self.sh.run(["ipset", "list", "-name"], timeout_sec=15)
        if rc != 0:
            return out or "Ошибка ipset"
        names = [x.strip() for x in out.splitlines() if x.strip()]
        # фильтруем hydraroute наборы по префиксам (часто HR_*)
        hr_names = [n for n in names if "Hydra" in n or n.lower().startswith(("hr", "hydra"))]
        show = hr_names[:60] if hr_names else names[:60]
        return "IPSet (первые 60):\n" + "\n".join(show)

    def diag_iptables(self) -> str:
        if not which("iptables"):
            return "iptables не найден."
        rc, out = self.sh.run(["iptables", "-t", "mangle", "-S"], timeout_sec=20)
        if rc != 0:
            return out or "Ошибка iptables"
        # вытащим строки с MARK/ipset/nflog
        lines = []
        for ln in out.splitlines():
            if any(k in ln for k in ("ipset", "MARK", "NFLOG", "Hydra", "hrneo", "HydraRoute")):
                lines.append(ln)
        if not lines:
            lines = out.splitlines()[:80] + ["… (обрезано)"]
        return "\n".join(lines)

    def file_get(self, kind: str) -> Tuple[bool, str, Optional[Path]]:
        mapping = {
            "hrneo.conf": HR_NEO_CONF,
            "domain.conf": HR_DOMAIN_CONF,
            "ip.list": HR_IP_LIST,
        }
        p = mapping.get(kind)
        if not p:
            return False, "Неизвестный файл", None
        if not p.exists():
            return False, f"Файл не найден: {p}", None
        return True, str(p), p

    def file_put(self, kind: str, content: str) -> Tuple[bool, str]:
        mapping = {
            "hrneo.conf": HR_NEO_CONF,
            "domain.conf": HR_DOMAIN_CONF,
            "ip.list": HR_IP_LIST,
        }
        p = mapping.get(kind)
        if not p:
            return False, "Неизвестный файл"
        return self.sh.write_file(p, content)

    def add_domain(self, domains: List[str], target: str) -> Tuple[bool, str]:
        """
        Добавить домены в domain.conf.
        Формат строки: домен1,домен2/Target
        """
        if not domains:
            return False, "Пустой список доменов"
        # валидация
        ok_domains = []
        for d in domains:
            d = d.strip().lower()
            if not d:
                continue
            # разрешаем geosite:TAG
            if d.startswith("geosite:"):
                if re.fullmatch(r"geosite:[A-Za-z0-9_-]{1,40}", d):
                    ok_domains.append(d)
                continue
            if re.fullmatch(r"[a-z0-9][a-z0-9\.-]{1,250}[a-z0-9]", d) or re.fullmatch(r"[a-z0-9]{1,63}", d):
                ok_domains.append(d)
        if not ok_domains:
            return False, "Не нашёл валидных доменов (разрешены домены и geosite:TAG)."

        # читаем файл
        if not HR_DOMAIN_CONF.exists():
            HR_DOMAIN_CONF.parent.mkdir(parents=True, exist_ok=True)
            HR_DOMAIN_CONF.write_text("", encoding="utf-8")
        text = HR_DOMAIN_CONF.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        target = target.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", target):
            return False, "Некорректное имя политики/интерфейса."

        # Ищем существующую строку вида ".../target" без geosite-only (чтобы не ломать)
        inserted = False
        new_lines = []
        for ln in lines:
            stripped = ln.strip()
            if (not inserted
                and stripped
                and not stripped.startswith("#")
                and "/" in stripped
                and stripped.rsplit("/", 1)[1] == target
                and "geosite:" not in stripped
            ):
                left, right = stripped.rsplit("/", 1)
                existing = [x.strip() for x in left.split(",") if x.strip()]
                merged = existing + [d for d in ok_domains if d not in existing]
                new_lines.append(",".join(merged) + "/" + right)
                inserted = True
            else:
                new_lines.append(ln)
        if not inserted:
            new_lines.append(",".join(ok_domains) + "/" + target)

        ok, msg = self.sh.write_file(HR_DOMAIN_CONF, "\n".join(new_lines) + "\n")
        if ok and self.is_neo_available():
            self.neo_cmd("restart")
        return ok, msg + ("\nNeo перезапущен." if ok and self.is_neo_available() else "")

    def remove_domain(self, domain: str) -> Tuple[bool, str]:
        domain = domain.strip().lower()
        if not domain:
            return False, "Пустой домен"
        if not HR_DOMAIN_CONF.exists():
            return False, "domain.conf не найден"
        text = HR_DOMAIN_CONF.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        changed = False
        new_lines = []
        for ln in lines:
            stripped = ln.strip()
            if not stripped or stripped.startswith("#") or "/" not in stripped:
                new_lines.append(ln)
                continue
            left, right = stripped.rsplit("/", 1)
            items = [x.strip() for x in left.split(",") if x.strip()]
            if domain in items:
                items = [x for x in items if x != domain]
                changed = True
                if items:
                    new_lines.append(",".join(items) + "/" + right)
                else:
                    # если больше ничего не осталось — комментируем строку, чтобы не потерять target
                    new_lines.append("# " + stripped)
            else:
                new_lines.append(ln)

        if not changed:
            return False, "Не нашёл домен в domain.conf"
        ok, msg = self.sh.write_file(HR_DOMAIN_CONF, "\n".join(new_lines) + "\n")
        if ok and self.is_neo_available():
            self.neo_cmd("restart")
        return ok, msg + ("\nNeo перезапущен." if ok and self.is_neo_available() else "")


    def parse_domain_conf(self) -> Tuple[bool, str, List[Tuple[int, str, str, List[str]]]]:
        """Парсит domain.conf: (line_no, raw_line, target, domains[])."""
        if not HR_DOMAIN_CONF.exists():
            return False, "domain.conf не найден", []
        try:
            lines = HR_DOMAIN_CONF.read_text(encoding="utf-8", errors="replace").splitlines()
            rules: List[Tuple[int, str, str, List[str]]] = []
            for i, ln in enumerate(lines, start=1):
                s = ln.strip()
                if not s or s.startswith("#") or "/" not in s:
                    continue
                left, target = s.rsplit("/", 1)
                domains = [x.strip() for x in left.split(",") if x.strip()]
                rules.append((i, ln, target.strip(), domains))
            return True, "OK", rules
        except Exception as e:
            return False, str(e), []

    def domain_summary(self, limit_targets: int = 25) -> str:
        ok, msg, rules = self.parse_domain_conf()
        if not ok:
            return msg
        per_target: Dict[str, int] = {}
        total = 0
        for _, _, target, domains in rules:
            per_target[target] = per_target.get(target, 0) + len(domains)
            total += len(domains)
        items = sorted(per_target.items(), key=lambda x: x[1], reverse=True)
        head = [f"Всего доменов: {total}", f"Правил: {len(rules)}", ""]
        for t, c in items[:limit_targets]:
            head.append(f"{t}: {c}")
        if len(items) > limit_targets:
            head.append("… (обрезано)")
        return "\n".join(head)

    def find_domain(self, query: str, limit: int = 20) -> str:
        query = query.strip().lower()
        if not query:
            return "Пустой запрос"
        ok, msg, rules = self.parse_domain_conf()
        if not ok:
            return msg
        hits: List[str] = []
        for ln_no, _, target, domains in rules:
            for d in domains:
                if query in d.lower():
                    hits.append(f"#{ln_no} -> {target}: {d}")
                    break
            if len(hits) >= limit:
                break
        return "\n".join(hits) if hits else "Совпадений не найдено."

    def duplicates(self, limit: int = 50) -> str:
        ok, msg, rules = self.parse_domain_conf()
        if not ok:
            return msg
        seen: Dict[str, List[str]] = {}
        for _, _, target, domains in rules:
            for d in domains:
                k = d.lower()
                seen.setdefault(k, []).append(target)
        dup = [(d, tgts) for d, tgts in seen.items() if len(set(tgts)) > 1]
        dup.sort(key=lambda x: len(set(x[1])), reverse=True)
        lines: List[str] = []
        for d, tgts in dup[:limit]:
            uniq = sorted(set(tgts))
            lines.append(f"{d}: {', '.join(uniq)}")
        if not lines:
            return "Дубликатов не найдено."
        if len(dup) > limit:
            lines.append("… (обрезано)")
        return "\n".join(lines)
