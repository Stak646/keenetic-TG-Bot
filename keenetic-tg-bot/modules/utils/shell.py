
from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from .log import get_logger


@dataclass(frozen=True)
class ShellResult:
    cmd: str
    rc: int
    out: str
    err: str
    ms: int


class Shell:
    def __init__(self, timeout_sec: int = 8, cache_ttl_sec: int = 3, debug: bool = False):
        self.timeout_sec = max(1, int(timeout_sec))
        self.cache_ttl_sec = max(0, int(cache_ttl_sec))
        self.debug = bool(debug)
        self._cache: Dict[str, Tuple[float, ShellResult]] = {}
        self.log = get_logger()

        # Init scripts on Keenetic/Entware may run with a minimal PATH that doesn't
        # include /opt/bin. Ensure opkg and other Entware binaries are always found.
        base_path = os.environ.get("PATH", "")
        if "/opt/bin" not in base_path.split(":"):
            base_path = "/opt/bin:/opt/sbin:" + base_path
        self._base_env: Dict[str, str] = dict(os.environ)
        self._base_env["PATH"] = base_path

    def _key(self, cmd: Union[str, List[str]]) -> str:
        if isinstance(cmd, list):
            return "\x00".join(cmd)
        return cmd

    def which(self, exe: str) -> Optional[str]:
        for p in os.environ.get("PATH", "").split(":"):
            cand = os.path.join(p, exe)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    def exists(self, exe: str) -> bool:
        return self.which(exe) is not None

    def run(
        self,
        cmd: Union[str, List[str]],
        timeout_sec: Optional[int] = None,
        cache_ttl_sec: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> ShellResult:
        """
        Run a command with timeout and optional caching.
        If cmd is a string, it's executed via sh -c (BusyBox ash compatible).
        """
        ttl = self.cache_ttl_sec if cache_ttl_sec is None else max(0, int(cache_ttl_sec))
        key = self._key(cmd)
        now = time.time()
        if ttl > 0:
            cached = self._cache.get(key)
            if cached and (now - cached[0]) <= ttl:
                return cached[1]

        t0 = time.time()
        to = self.timeout_sec if timeout_sec is None else max(1, int(timeout_sec))

        if isinstance(cmd, list):
            popen_args = cmd
            printable = " ".join(shlex.quote(x) for x in cmd)
        else:
            # Use /bin/sh -c (ash)
            popen_args = ["/bin/sh", "-c", cmd]
            printable = cmd

        if self.debug:
            self.log.debug("[sh] %s", printable)

        try:
            run_env = dict(self._base_env)
            if env:
                run_env.update(env)
            p = subprocess.run(
                popen_args,
                capture_output=True,
                text=True,
                timeout=to,
                env=run_env,
                cwd=cwd,
            )
            out = (p.stdout or "").strip()
            err = (p.stderr or "").strip()
            rc = int(p.returncode)
        except subprocess.TimeoutExpired as e:
            out = ((e.stdout or "") if isinstance(e.stdout, str) else "").strip()
            err = "TIMEOUT"
            rc = 124
        except Exception as e:
            out = ""
            err = str(e)
            rc = 127

        ms = int((time.time() - t0) * 1000)
        res = ShellResult(cmd=printable, rc=rc, out=out, err=err, ms=ms)

        if ttl > 0:
            self._cache[key] = (now, res)

        return res
