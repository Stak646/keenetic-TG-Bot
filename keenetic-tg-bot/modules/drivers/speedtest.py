
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .base import DriverBase
from ..utils.shell import ShellResult


@dataclass(frozen=True)
class SpeedTestResult:
    ok: bool
    method: str
    download_mbps: Optional[float] = None
    upload_mbps: Optional[float] = None
    ping_ms: Optional[float] = None
    server: str = ""
    raw: str = ""


DEFAULT_HTTP_SERVERS: List[Tuple[str, str]] = [
    ("Cloudflare (Global)", "https://speed.cloudflare.com/__down?bytes=50000000"),
    ("Hetzner (DE)", "https://speed.hetzner.de/100MB.bin"),
]


class SpeedTestDriver(DriverBase):
    def http_download(self, url: str, max_time_sec: int = 20) -> SpeedTestResult:
        # speed_download is bytes/sec
        cmd = f"curl -L -o /dev/null -s -w '%{{speed_download}}' --connect-timeout 5 --max-time {int(max_time_sec)} {url!r}"
        res: ShellResult = self.sh.run(cmd, timeout_sec=max_time_sec + 5, cache_ttl_sec=0)
        if res.rc != 0:
            return SpeedTestResult(ok=False, method="http", server=url, raw=res.err or res.out)
        raw = (res.out or "").strip().replace("\n", "")
        try:
            bps = float(raw)
            mbps = (bps * 8) / 1_000_000
            return SpeedTestResult(ok=True, method="http", download_mbps=round(mbps, 2), server=url, raw=raw)
        except Exception:
            return SpeedTestResult(ok=False, method="http", server=url, raw=raw)

    def has_speedtest_go(self) -> bool:
        return self.sh.exists("speedtest-go")

    def run_speedtest_go(self, args: str = "") -> SpeedTestResult:
        # Try JSON mode; fall back to plain.
        cmd = f"speedtest-go --json {args}".strip()
        res = self.sh.run(cmd + " 2>/dev/null || true", timeout_sec=120, cache_ttl_sec=0)
        if not res.out:
            return SpeedTestResult(ok=False, method="speedtest-go", raw=res.err or "")
        try:
            d = json.loads(res.out)
            dl = None
            ul = None
            ping = None
            server = ""
            if isinstance(d, dict):
                # best-effort fields
                ping = float(d.get("ping", {}).get("latency", 0) or 0) if isinstance(d.get("ping"), dict) else None
                dl_bps = d.get("download", {}).get("bandwidth") if isinstance(d.get("download"), dict) else None
                ul_bps = d.get("upload", {}).get("bandwidth") if isinstance(d.get("upload"), dict) else None
                # Some tools report bytes/sec bandwidth
                if isinstance(dl_bps, (int, float)):
                    dl = (float(dl_bps) * 8) / 1_000_000
                if isinstance(ul_bps, (int, float)):
                    ul = (float(ul_bps) * 8) / 1_000_000
                srv = d.get("server") or {}
                if isinstance(srv, dict):
                    server = str(srv.get("name", "")) or str(srv.get("host", "")) or ""
            return SpeedTestResult(ok=True, method="speedtest-go", download_mbps=round(dl, 2) if dl else None, upload_mbps=round(ul, 2) if ul else None, ping_ms=round(ping, 2) if ping else None, server=server, raw=res.out)
        except Exception:
            return SpeedTestResult(ok=False, method="speedtest-go", raw=res.out)
