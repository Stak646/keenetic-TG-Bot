
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from .utils.i18n import I18N
from .utils.text import esc


@dataclass
class Screen:
    text: str
    kb: Optional[InlineKeyboardMarkup] = None
    disable_preview: bool = True


def kb(rows: Sequence[Sequence[Tuple[str, str]]]) -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    for row in rows:
        buttons: List[InlineKeyboardButton] = []
        for label, data in row:
            buttons.append(InlineKeyboardButton(text=label, callback_data=data))
        m.row(*buttons)
    return m


def btn(label: str, data: str) -> Tuple[str, str]:
    # callback_data max 64 bytes; caller must ensure.
    return (label, data)


def nav_home(i18n: I18N) -> Tuple[str, str]:
    return btn(i18n.t("btn.home"), "h|m")


def nav_back(i18n: I18N, back_to: str) -> Tuple[str, str]:
    return btn(i18n.t("btn.back"), back_to)


def pager(i18n: I18N, base: str, page: int, pages: int) -> List[Tuple[str, str]]:
    """
    base: callback data prefix without page, e.g. "r|routes|"
    We will append "p=<n>" to it.
    """
    prev_p = max(1, page - 1)
    next_p = min(pages, page + 1)
    prev_data = f"{base}p={prev_p}"
    next_data = f"{base}p={next_p}"
    mid = f"{page}/{pages}"
    # "noop" must be handled by app to just answer callback.
    return [
        btn(i18n.t("btn.prev"), prev_data if page > 1 else "noop"),
        btn(mid, "noop"),
        btn(i18n.t("btn.next"), next_data if page < pages else "noop"),
    ]


def action_row(i18n: I18N, actions: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    return list(actions)


def on_off(i18n: I18N, on: bool, data_on: str, data_off: str) -> Tuple[str, str]:
    return btn(i18n.t("btn.debug_on") if on else i18n.t("btn.debug_off"), data_on if on else data_off)
