# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List

from .constants import LOG_PATH, NFQWS_LOG, HR_NEO_LOG_DEFAULT

def opt_status(shell) -> str:
    parts: List[str] = []
    _, df = shell.run(["df", "-h", "/opt"], timeout_sec=10)
    if df:
        parts.append(df.strip())
    _, mount = shell.run(["mount"], timeout_sec=10)
    if mount:
        for ln in mount.splitlines():
            if " on /opt " in ln:
                parts.append("")
                parts.append("mount:")
                parts.append(ln.strip())
                break
    return "\n".join(parts).strip()

def opt_top(shell, depth: int = 2, n: int = 20) -> str:
    # BusyBox du supports -d; coreutils supports --max-depth
    cmds = [
        f"du -k -d {depth} /opt 2>/dev/null | sort -nr | head -n {n}",
        f"du -k --max-depth {depth} /opt 2>/dev/null | sort -nr | head -n {n}",
    ]
    for cmd in cmds:
        rc, out = shell.sh(cmd, timeout_sec=60)
        if rc == 0 and out:
            return out.strip()
    return "du/sort/head failed"

def cleanup(shell) -> str:
    actions: List[str] = []
    # truncate logs (best-effort)
    for p in [LOG_PATH, str(NFQWS_LOG), str(HR_NEO_LOG_DEFAULT)]:
        rc, _ = shell.sh(f": > {p} 2>/dev/null || true", timeout_sec=10)
        actions.append(f"truncated: {p}" if rc == 0 else f"truncate failed: {p}")

    # remove opkg lists (safe)
    shell.sh("rm -f /opt/var/opkg-lists/* 2>/dev/null || true", timeout_sec=15)
    actions.append("cleared: /opt/var/opkg-lists/*")

    # cleanup tmp installers
    shell.sh("rm -rf /opt/tmp/keenetic-tg-bot-installer* 2>/dev/null || true", timeout_sec=15)
    actions.append("removed: /opt/tmp/keenetic-tg-bot-installer*")

    return "\n".join(actions).strip()
