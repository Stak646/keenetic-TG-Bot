# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import socket
import subprocess
import time
from typing import List, Optional, Tuple

from .utils import strip_ansi, log_line
from .profiler import CommandProfiler

class Shell:

    def __init__(self, timeout_sec: int = 30, debug_enabled: bool = False):
        self.timeout_sec = timeout_sec
        self.debug_enabled = bool(debug_enabled)
        self.debug = False
        self.debug_output_max = 5000
        self.env = os.environ.copy()
        self.profiler = CommandProfiler()
        # entware binaries
        self.env["PATH"] = "/opt/bin:/opt/sbin:/usr/bin:/usr/sbin:/bin:/sbin:" + self.env.get("PATH", "")

    def run(self, args: List[str], timeout_sec: Optional[int] = None) -> Tuple[int, str]:
        timeout = timeout_sec if timeout_sec is not None else self.timeout_sec
        t0 = time.time()
        cmd = " ".join(args)
        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=self.env,
                timeout=timeout,
            )
            out = strip_ansi((proc.stdout or "")).strip()
            rc = proc.returncode
            dt = time.time() - t0
            if getattr(self, 'debug', False):
                log_line(f"DEBUG cmd={cmd} rc={rc} dt={dt:.3f}s")
                if out:
                    log_line("DEBUG out:\n" + out[: getattr(self, 'debug_output_max', 5000)])
            self.profiler.record(cmd, dt, rc)
            if self.debug_enabled:
                log_line(f"cmd dt={dt:.2f}s rc={rc} :: {cmd}")
            return rc, out
        except subprocess.TimeoutExpired as e:
            out = strip_ansi((e.stdout or "")).strip() if e.stdout else ""
            dt = time.time() - t0
            if getattr(self, "debug", False):
                log_line(f"DEBUG cmd={cmd} rc=124 dt={dt:.3f}s")
                if out:
                    log_line("DEBUG out:\n" + out[: getattr(self, "debug_output_max", 5000)])
            self.profiler.record(cmd, dt, 124)
            return 124, f"TIMEOUT {timeout}s\n{out}"
        except FileNotFoundError:
            dt = time.time() - t0
            if getattr(self, "debug", False):
                log_line(f"DEBUG cmd={cmd} rc=127 dt={dt:.3f}s")
            self.profiler.record(cmd, dt, 127)
            return 127, f"Команда не найдена: {args[0]}"
        except Exception as e:
            dt = time.time() - t0
            if getattr(self, "debug", False):
                log_line(f"DEBUG cmd={cmd} rc=1 dt={dt:.3f}s")
            self.profiler.record(cmd, dt, 1)
            return 1, f"Ошибка запуска: {e}"

    def sh(self, cmdline: str, timeout_sec: Optional[int] = None) -> Tuple[int, str]:
        # Используем /bin/sh -lc для простых пайпов/грепа в диагностике.
        # ВНИМАНИЕ: НЕ передавать сюда пользовательский ввод!
        return self.run(["/bin/sh", "-c", cmdline], timeout_sec=timeout_sec)

    def read_file(self, path: Path, max_bytes: int = 200_000) -> Tuple[bool, str]:
        try:
            if not path.exists():
                return False, f"Файл не найден: {path}"
            size = path.stat().st_size
            if size > max_bytes:
                # читаем хвост
                with open(path, "rb") as f:
                    f.seek(max(0, size - max_bytes))
                    data = f.read(max_bytes)
                text = data.decode("utf-8", errors="replace")
                return True, f"(показан хвост файла, {max_bytes} байт)\n{text}"
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return True, f.read()
        except Exception as e:
            return False, f"Не удалось прочитать {path}: {e}"

    def backup_file(self, path: Path) -> Optional[Path]:
        try:
            if not path.exists():
                return None
            ts = time.strftime("%Y%m%d-%H%M%S")
            bkp = path.with_suffix(path.suffix + f".bak-{ts}")
            shutil.copy2(path, bkp)
            return bkp
        except Exception:
            return None

    def write_file(self, path: Path, content: str) -> Tuple[bool, str]:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            bkp = self.backup_file(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True, f"Файл сохранён: {path}" + (f"\nБэкап: {bkp}" if bkp else "")
        except Exception as e:
            return False, f"Не удалось записать {path}: {e}"


# -----------------------------
# Драйверы сервисов / функций
# -----------------------------
