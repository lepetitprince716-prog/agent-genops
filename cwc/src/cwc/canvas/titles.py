"""Where the frontend draws a group's title text.

``LGraphGroup.draw`` (ComfyUI_frontend 1.59.1) writes the title in 20 px Inter, left-aligned
10 px inside the frame, centred in a 30 px title bar along the frame's top, and does not clip it,
so a long title runs past the frame's right side. The ``font_size`` a canvas writes into a group
is not read there. A link drawn over that text makes the title hard to read.
"""

from __future__ import annotations

from cwc.canvas.geometry import Rect
from cwc.canvas.model import Group
from cwc.canvas.textwidth import text_width

__all__ = ["TITLE_BAR", "TITLE_FONT", "TITLE_INSET", "TITLE_MARGIN", "title_rect"]

TITLE_FONT = 20  # LiteGraph.GROUP_TEXT_SIZE
TITLE_INSET = 10  # the text's left edge from the frame's left side: half the font size
TITLE_BAR = 30  # NODE_TITLE_HEIGHT, the bar the text is centred in
TITLE_MARGIN = 4  # px added on each side: text_width bounds Inter, other sans fonts run a little wider


def title_rect(group: Group) -> Rect:
    """The title text of ``group`` as the frontend draws it, ``TITLE_MARGIN`` wider on each side,
    the full height of the title bar."""
    frame = group.bounding
    width = text_width(group.title, TITLE_FONT)
    return Rect(frame.x + TITLE_INSET - TITLE_MARGIN, frame.y, width + 2 * TITLE_MARGIN, TITLE_BAR)
