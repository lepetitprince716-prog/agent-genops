"""``extra.cwc``: the author's title and notes, kept in the canvas for the diagram skin.

Compile writes it when the document sets ``_workflow.title``, a ``_meta.ui_note`` or a
``_workflow.groups.<id>.note``::

    {"format": 1, "title": str | null,
     "notes": {node id: str},
     "groups": {group title as written in the canvas: {"note": str}}}

Groups are keyed by their written title (``02 Sampling``) because a canvas group has no
other name that survives a load in the frontend. The frontend keeps unknown ``extra`` keys
through load and ``serialize()``; only ``linkExtensions`` and ``linkPresentation`` are
rewritten. :func:`read_notes` is the one reader: it takes what is well formed and drops the
rest, so a hand-edited block never stops a render.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from cwc.annotate.infer import author_group
from cwc.annotate.types import Annotations
from cwc.canvas.model import Canvas, id_order
from cwc.layout.types import LayoutResult
from cwc.normalize.types import Authoring

KEY = "cwc"
FORMAT = 1


@dataclass(frozen=True)
class DiagramNotes:
    title: str | None = None
    notes: Mapping[str, str] = field(default_factory=dict)  # node key -> note
    groups: Mapping[str, str] = field(default_factory=dict)  # written group title -> note


def collect_notes(authoring: Authoring, plan: Annotations, laid: LayoutResult, canvas: Canvas) -> DiagramNotes:
    """What the author wrote for the diagram, keyed the way the written canvas names things."""
    present = set(canvas.node_map())
    notes = {key: intent.ui_note for key, intent in authoring.intents.items() if intent.ui_note and key in present}
    titles = [group.title for group in canvas.groups]
    groups: dict[str, str] = {}
    for group in plan.groups:
        group_id = author_group(group.key, group.zone, list(group.members), authoring.intents)
        info = authoring.workflow.groups.get(group_id) if group_id is not None else None
        if info is None or not info.note:
            continue
        for part, index in sorted(laid.group_index.items(), key=lambda item: item[1]):
            if part == group.key or part.startswith(f"{group.key}/"):
                groups[titles[index]] = info.note
    return DiagramNotes(
        title=authoring.workflow.title or None,
        notes={key: notes[key] for key in sorted(notes, key=id_order)},
        groups=groups,
    )


def write_notes(canvas: Canvas, notes: DiagramNotes) -> None:
    """Set ``extra.cwc``; a canvas with nothing to say gets no block."""
    if notes.title is None and not notes.notes and not notes.groups:
        canvas.extra.pop(KEY, None)
        return
    canvas.extra[KEY] = {
        "format": FORMAT,
        "title": notes.title,
        "notes": dict(notes.notes),
        "groups": {title: {"note": note} for title, note in notes.groups.items()},
    }


def read_notes(canvas: Canvas) -> DiagramNotes:
    """``extra.cwc`` of a canvas; empty when absent, of another format, or malformed."""
    raw = canvas.raw.get("extra")
    block = raw.get(KEY) if isinstance(raw, dict) else None
    if not isinstance(block, dict) or block.get("format") != FORMAT or isinstance(block.get("format"), bool):
        return DiagramNotes()
    title = block.get("title")
    return DiagramNotes(
        title=title if isinstance(title, str) and title else None,
        notes=_strings(block.get("notes"), lambda value: value),
        groups=_strings(block.get("groups"), lambda value: value.get("note") if isinstance(value, dict) else None),
    )


def _strings(raw: Any, pick: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        text = pick(value)
        if isinstance(key, str) and isinstance(text, str) and text:
            out[key] = text
    return out
