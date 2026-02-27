# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .constants import LOG_PATH

def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def log_line(msg: str) -> None:
    try:
        msg = (msg or "")
        if len(msg) > 2000:
            msg = msg[:2000] + "…(truncated)"
        # keep log safe
        try:
            msg = msg.encode("utf-8", "replace").decode("utf-8", "replace")
        except Exception:
            pass

        Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{_now_ts()}] {msg}\n")
    except Exception:
        pass

def escape_html(s: str) -> str:
    s = s or ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s or "")

def clip_text(s: str, max_lines: int = 120, max_chars: int = 3500) -> str:
    s = s or ""
    lines = s.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["… (truncated)"]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n… (truncated)"
    return out

def fmt_code(s: str) -> str:
    return f"<pre><code>{escape_html(clip_text(s))}</code></pre>"

def chunk_text(text: str, limit: int = 3800) -> List[str]:
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > limit and cur:
            chunks.append("".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks

def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd, path=os.environ.get("PATH", ""))

def parse_env_like(text: str) -> Dict[str, str]:
    kv: Dict[str, str] = {}
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            kv[k] = v
    return kv

def fmt_ip_route(out: str) -> str:
    out = (out or "").strip()
    if not out:
        return out
    lines = out.splitlines()
    default = [ln for ln in lines if ln.startswith("default ")]
    rest = [ln for ln in lines if ln not in default]
    groups: Dict[str, List[str]] = {}
    for ln in rest:
        m = re.search(r"\bdev\s+(\S+)", ln)
        dev = m.group(1) if m else "other"
        groups.setdefault(dev, []).append(ln)
    res: List[str] = []
    if default:
        res += ["# default"] + default + [""]
    for dev in sorted(groups.keys()):
        res += [f"# dev {dev}"] + groups[dev] + [""]
    return "\n".join([x for x in res if x != ""])

def summarize_iptables(out: str) -> str:
    chains: Dict[str, Dict[str, Any]] = {}
    rules = 0
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if ln.startswith("-P "):
            parts = ln.split()
            if len(parts) >= 3:
                chains.setdefault(parts[1], {"policy": parts[2], "rules": 0})
        elif ln.startswith("-A "):
            rules += 1
            parts = ln.split()
            if len(parts) >= 2:
                chains.setdefault(parts[1], {"policy": "?", "rules": 0})
                chains[parts[1]]["rules"] += 1
    lines = [f"Total rules: {rules}"]
    for ch in sorted(chains.keys()):
        lines.append(f"{ch:14} rules={chains[ch]['rules']} policy={chains[ch]['policy']}")
    return "\n".join(lines)
