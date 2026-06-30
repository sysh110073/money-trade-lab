from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any


MOJIBAKE_MARKERS = ("????", "???", "\ufffd")


def text(value: Any) -> str:
    """HTML-safe text: escape markup and encode non-ASCII as entities."""
    escaped = escape("" if value is None else str(value), quote=True)
    return "".join(f"&#x{ord(char):x};" if ord(char) > 127 else char for char in escaped)


def write(path: Path, html: str) -> None:
    bad = [marker for marker in MOJIBAKE_MARKERS if marker in html]
    if bad:
        raise ValueError(f"Refusing to write likely mojibake markers: {bad}")
    path.write_text(html, encoding="utf-8")

