
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .shell import Shell
from .log import get_logger


OPKG_DIR = "/opt/etc/opkg"
OPKG_CONF_GLOB = ["/opt/etc/opkg/*.conf", "/opt/etc/opkg/custom.conf", "/opt/etc/opkg.conf"]


@dataclass(frozen=True)
class ArchInfo:
    arch: str           # aarch64 / mipsel / mips / unknown
    entware_arch: str   # aarch64-k3.10 / mipsel-k3.4 / mips-k3.4
    hoaxisr_arch: str   # aarch64-3.10-kn / mipsel-3.4-kn / mips-3.4-kn


def detect_arch(sh: Shell) -> ArchInfo:
    out = sh.run("opkg print-architecture 2>/dev/null | awk '{print $2}'", timeout_sec=5, cache_ttl_sec=30).out
    archs = [x.strip() for x in out.splitlines() if x.strip()]
    # pick first non-"all"
    cand = ""
    for a in archs:
        if a.lower() == "all":
            continue
        cand = a.lower()
        break

    if cand.startswith("aarch64"):
        return ArchInfo(arch="aarch64", entware_arch="aarch64-k3.10", hoaxisr_arch="aarch64-3.10-kn")
    if cand.startswith("mipsel"):
        return ArchInfo(arch="mipsel", entware_arch="mipsel-k3.4", hoaxisr_arch="mipsel-3.4-kn")
    if cand.startswith("mips"):
        return ArchInfo(arch="mips", entware_arch="mips-k3.4", hoaxisr_arch="mips-3.4-kn")
    # fallback: use uname
    um = sh.run("uname -m 2>/dev/null || true", timeout_sec=3, cache_ttl_sec=30).out.lower()
    if "aarch64" in um or "arm64" in um:
        return ArchInfo(arch="aarch64", entware_arch="aarch64-k3.10", hoaxisr_arch="aarch64-3.10-kn")
    if "mipsel" in um:
        return ArchInfo(arch="mipsel", entware_arch="mipsel-k3.4", hoaxisr_arch="mipsel-3.4-kn")
    if "mips" in um:
        return ArchInfo(arch="mips", entware_arch="mips-k3.4", hoaxisr_arch="mips-3.4-kn")
    return ArchInfo(arch="unknown", entware_arch="", hoaxisr_arch="")


def _read_existing_sources() -> str:
    buf: List[str] = []
    for p in ["/opt/etc/opkg.conf", "/opt/etc/opkg/custom.conf"]:
        if os.path.isfile(p):
            try:
                buf.append(Path(p).read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
    if os.path.isdir(OPKG_DIR):
        for f in sorted(Path(OPKG_DIR).glob("*.conf")):
            try:
                buf.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
    return "\n".join(buf)


def ensure_src(sh: Shell, name: str, url: str, filename: str) -> bool:
    """
    Ensure src/gz entry exists in /opt/etc/opkg/<filename>.
    Returns True if changed.
    """
    logger = get_logger()
    Path(OPKG_DIR).mkdir(parents=True, exist_ok=True)
    existing = _read_existing_sources()
    # if URL already present anywhere, do nothing
    if url in existing:
        return False

    conf_path = Path(OPKG_DIR) / filename
    line = f"src/gz {name} {url}\n"
    try:
        with open(conf_path, "a", encoding="utf-8") as f:
            f.write(line)
        logger.info("Added opkg source %s -> %s", name, url)
        return True
    except Exception as e:
        logger.error("Failed to write opkg source %s: %s", conf_path, e)
        return False


def remove_src(url_substring: str) -> int:
    """
    Remove lines containing url_substring from OPKG conf files inside /opt/etc/opkg.
    Returns number of modified files.
    """
    count = 0
    if not os.path.isdir(OPKG_DIR):
        return 0
    for f in Path(OPKG_DIR).glob("*.conf"):
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore").splitlines(True)
            new = [ln for ln in txt if url_substring not in ln]
            if new != txt:
                f.write_text("".join(new), encoding="utf-8")
                count += 1
        except Exception:
            continue
    return count
