# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple, Optional

@dataclass
class CmdEvent:
    cmd: str
    dt: float
    rc: int

class CommandProfiler:
    def __init__(self, max_events: int = 200):
        self.events: Deque[CmdEvent] = deque(maxlen=max_events)

    def record(self, cmd: str, dt: float, rc: int) -> None:
        self.events.append(CmdEvent(cmd=cmd, dt=dt, rc=rc))

    def top(self, n: int = 10) -> List[Tuple[str, int, float, float]]:
        # returns list: (cmd, count, avg, max)
        agg: Dict[str, List[float]] = {}
        for ev in self.events:
            agg.setdefault(ev.cmd, []).append(ev.dt)
        items = []
        for cmd, dts in agg.items():
            c = len(dts)
            avg = sum(dts) / c
            mx = max(dts)
            items.append((cmd, c, avg, mx))
        items.sort(key=lambda x: (x[3], x[2]), reverse=True)
        return items[:n]

    def format_top(self, n: int = 10) -> str:
        items = self.top(n=n)
        if not items:
            return "No data yet."
        lines = ["# top slow commands (max/avg)"]
        for cmd, c, avg, mx in items:
            lines.append(f"{mx:6.2f}s  avg={avg:5.2f}s  n={c:3d}  {cmd}")
        return "\n".join(lines)
