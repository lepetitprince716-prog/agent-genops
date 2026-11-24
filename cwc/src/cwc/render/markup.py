"""Numbers and text as SVG writes them, shared by both skins."""

from __future__ import annotations

import math
import re
from xml.sax.saxutils import escape

from cwc.canvas.envelope import Point

# What XML 1.0 refuses in text: C0 controls other than tab, newline and carriage return, lone
# surrogates and the two non-characters at the end of the basic plane.
_NOT_XML = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")
_ENTITIES = {'"': "&quot;", "'": "&apos;"}


def num(value: float) -> str:
    """A number with at most two decimals and no trailing zeros, ``-0`` written ``0``."""
    if not math.isfinite(value):
        raise ValueError(f"cannot draw a non-finite coordinate: {value}")
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def pair(point: Point) -> str:
    return f"{num(point[0])} {num(point[1])}"


def clean(text: str) -> str:
    return _NOT_XML.sub("", text)


def text(value: str) -> str:
    """Element text: characters XML cannot hold dropped, ``& < > " '`` escaped."""
    return escape(clean(value), _ENTITIES)


def attr(value: str) -> str:
    """Attribute value: as :func:`text`, with white space written as spaces."""
    return text(re.sub(r"\s", " ", value))
