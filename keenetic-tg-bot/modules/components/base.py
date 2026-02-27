
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ..ui import Screen
from ..utils.i18n import I18N


class ComponentBase:
    id: str = "base"
    emoji: str = "❓"
    title_key: str = "app.title"

    def title(self, i18n: I18N) -> str:
        return i18n.t(self.title_key)

    def is_available(self) -> bool:
        return True

    def quick_status(self) -> Optional[str]:
        """
        Return a short status string for monitor notifications.
        None disables monitoring for this component.
        """
        return None

    def render(self, app: "App", cmd: str, params: Dict[str, str]) -> Screen:
        raise NotImplementedError
