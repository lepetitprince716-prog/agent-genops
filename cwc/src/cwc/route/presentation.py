"""Link presentation: ``extra.linkPresentation``, the frontend's own way to hide a link.

A link marked ``{"hidden": true}`` is drawn as a small tag at each end instead of a curve; the
unlabelled hidden links that leave one output are stacked into one tag, a labelled one always keeps
a tag of its own, and a reroute that only hidden links pass through is not drawn. The link stays in ``links``, so the
workflow and the API prompt it queues do not change. A frontend that does not know the key draws
every such link as the route that was written for it.

``hide`` ``resources`` marks the links layout lists in ``LayoutResult.forced`` (links between
columns) whose type is in :data:`RESOURCE_TYPES`: they carry a loaded model, text encoder, VAE or
prompt to a far column, and a curve per consumer hides what the picture is about. A link inside a
column and the main flow (latents, images) stay drawn.

Labels: tags of one type that all start at one output need no text, the stacked tag already
reads ``VAE x2``. When a type's hidden links start at two or more outputs, each output is named
the way the frontend titles its node: its title, else its definition's display name (the class
name when the definition gives no other), else its class name, and ``<name>: <output name>``
when one node feeds two or more outputs of the type. A link is labelled with its output's name
only when no other output of the type has the same name: a label two sources share tells them
apart no better than the type the frontend shows without one.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from cwc.canvas.model import Canvas, Link, Node
from cwc.layout.types import HideLinks
from cwc.nodedefs.registry import NodeDefs

KEY = "linkPresentation"
RESOURCE_TYPES = frozenset({"MODEL", "CLIP", "VAE", "CONDITIONING"})


def mark_hidden(canvas: Canvas, forced: Iterable[int], hide: HideLinks, defs: NodeDefs) -> None:
    """Write (or remove) ``extra.linkPresentation`` for ``hide`` on ``canvas``."""
    extra = canvas.extra
    extra.pop(KEY, None)
    if hide is HideLinks.NONE:
        return
    wanted = set(forced)
    links = sorted((link for link in canvas.links if link.id in wanted and link.type in RESOURCE_TYPES), key=lambda link: link.id)
    if not links:
        return
    nodes = canvas.node_map()
    labels = _labels(links, nodes, defs)
    extra[KEY] = {str(link.id): {"hidden": True, **({"label": labels[link.id]} if link.id in labels else {})} for link in links}


def _labels(links: list[Link], nodes: dict[str, Node], defs: NodeDefs) -> dict[int, str]:
    out: dict[int, str] = {}
    for kind in sorted({link.type for link in links}):
        of_kind = [link for link in links if link.type == kind]
        sources = {(link.origin_id, link.origin_slot) for link in of_kind}
        if len(sources) < 2:
            continue
        slots_of: dict[Any, set[int]] = {}
        for node_id, slot in sources:
            slots_of.setdefault(node_id, set()).add(slot)
        named: dict[tuple[Any, int], str] = {}
        for link in of_kind:
            node = nodes.get(str(link.origin_id))
            name = _node_name(node, link, defs)
            if len(slots_of[link.origin_id]) > 1:
                name = f"{name}: {_output_name(node, link)}"
            named[(link.origin_id, link.origin_slot)] = name
        sharing = Counter(named.values())
        for link in of_kind:
            name = named[(link.origin_id, link.origin_slot)]
            if sharing[name] == 1:
                out[link.id] = name
    return out


def _node_name(node: Node | None, link: Link, defs: NodeDefs) -> str:
    """The source node's header as the frontend writes it: title, else display name, else class."""
    if node is None:
        return str(link.type)
    if node.title:
        return node.title
    nodedef = defs.get(node.type)
    if nodedef is not None and nodedef.display_name:
        return nodedef.display_name
    return node.type


def _output_name(node: Node | None, link: Link) -> str:
    outputs = node.outputs if node is not None else []
    if link.origin_slot < len(outputs) and outputs[link.origin_slot].get("name"):
        return str(outputs[link.origin_slot]["name"])
    return str(link.type)
