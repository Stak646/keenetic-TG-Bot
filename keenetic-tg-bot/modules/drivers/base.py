
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..utils.shell import Shell


@dataclass
class ServiceStatus:
    installed: bool
    running: bool
    version: Optional[str] = None
    detail: str = ""


class DriverBase:
    def __init__(self, sh: Shell):
        self.sh = sh
