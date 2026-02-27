
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import List, Sequence, Tuple


def esc(s: str) -> str:
    return html.escape(s or "")


def pre(s: str) -> str:
    return f"<pre>{esc(s)}</pre>"


def bold(s: str) -> str:
    return f"<b>{esc(s)}</b>"


def trunc_lines(lines: Sequence[str], max_lines: int) -> List[str]:
    if max_lines <= 0:
        return list(lines)
    if len(lines) <= max_lines:
        return list(lines)
    return list(lines[:max_lines]) + [f"... ({len(lines) - max_lines} more)"]


def chunk_text_lines(lines: Sequence[str], max_chars: int = 3500) -> List[str]:
    """
    Split lines into pages that fit Telegram 4096 limit (keep some margin for header).
    """
    pages: List[str] = []
    buf: List[str] = []
    cur = 0
    for line in lines:
        ln = line.rstrip("\n")
        add = len(ln) + 1
        if buf and cur + add > max_chars:
            pages.append("\n".join(buf))
            buf = [ln]
            cur = len(ln) + 1
        else:
            buf.append(ln)
            cur += add
    if buf:
        pages.append("\n".join(buf))
    if not pages:
        pages = [""]
    return pages


@dataclass(frozen=True)
class Page:
    text: str
    page: int
    pages: int


def paginate_lines(lines: Sequence[str], page: int, max_chars: int = 3500) -> Page:
    pages = chunk_text_lines(lines, max_chars=max_chars)
    total = len(pages)
    p = max(1, min(int(page), total))
    return Page(text=pages[p-1], page=p, pages=total)
