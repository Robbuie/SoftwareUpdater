"""Theme tokens as Qt colours and fonts, for what is painted rather than styled.

`parse_colour` and `mono_font` are File Compare 1.26.0's (`ui/diffview.py`),
moved to a module of their own here because this application has no diff
view to keep them in.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont


def parse_colour(value: str | None) -> QColor:
    """A token as a `QColor`. The derived tints are written `rgba(r, g, b, a)`
    for the stylesheet, which `QColor` does not read -- given one it comes back
    invalid and paints black, which is how the current-difference outline
    first rendered on the light theme."""
    if not value:
        return QColor()
    text = value.strip()
    if text.startswith("rgba(") and text.endswith(")"):
        try:
            r, g, b, a = (part.strip() for part in text[5:-1].split(","))
            colour = QColor(int(r), int(g), int(b))
            colour.setAlphaF(float(a))
            return colour
        except ValueError:
            return QColor()
    return QColor(text)


def mono_font(tokens: dict[str, str]) -> QFont:
    font = QFont()
    font.setFamilies(["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"])
    font.setStyleHint(QFont.Monospace)
    size = float(str(tokens.get("ui_font", "13px")).rstrip("px") or 13)
    font.setPixelSize(max(9, round(size)))
    return font

