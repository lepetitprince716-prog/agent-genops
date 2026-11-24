"""N7: a stage handoff (one sampler's latent reaching another sampler) with no preview.

A multi-stage workflow can only be compared stage by stage when every boundary shows its
picture. A boundary is covered when an IMAGE made from the first sampler's output, on the
way to the next sampler or decoded beside it, feeds an output node that runs. Report-only.

* A sampler has a LATENT output, a LATENT input and a MODEL or GUIDER input. Muted samplers
  (mode 2) are not stages. Following a sampler's output stops at the next sampler.
* An output node that is muted does not count. A bypassed one counts only inside an optional
  module (one group box whose real nodes are all bypassed; the box is what the frontend
  toggles, so two boxes are two modules) that also holds both samplers, because
  the module is toggled as a whole: with the main branch running and the preview bypassed,
  the boundary has no preview.
* Links pass through frontend-only nodes; a node of unknown type counts as an output node,
  as in N1.
"""

from __future__ import annotations

from collections import defaultdict

from cwc.canvas.model import Link, Node, NodeMode, id_order
from cwc.report import Code, Finding, Severity
from cwc.verify.graph import CanvasFacts

LATENT = "LATENT"
IMAGE = "IMAGE"
BYPASSED = int(NodeMode.BYPASS)
MUTED = int(NodeMode.NEVER)

HINT = "in a multi-stage workflow put a PreviewImage at every stage boundary (an ImageCompare for A/B) so each stage can be compared"


def check_stage_previews(facts: CanvasFacts) -> list[Finding]:
    nodes = {node.key: node for node in facts.canvas.nodes}
    outgoing: dict[str, list[Link]] = defaultdict(list)
    for link in facts.canvas.links:
        if str(link.origin_id) in nodes and str(link.target_id) in nodes:
            outgoing[str(link.origin_id)].append(link)
    samplers = [node for node in facts.nodes if node.mode != MUTED and _is_sampler(facts, node)]
    modules = _bypassed_modules(facts)
    out = []
    for first in samplers:
        reached, handoffs = _follow(facts, nodes, outgoing, first)
        for second in sorted(handoffs, key=lambda node: id_order(node.key)):
            if not _previewed(facts, nodes, outgoing, modules, first, second, reached):
                out.append(_finding(facts, nodes, outgoing, first, second, reached))
    return out


def _is_sampler(facts: CanvasFacts, node: Node) -> bool:
    nodedef = facts.nodedef(node)
    if nodedef is None or nodedef.virtual:
        return False
    inputs = {spec.type for spec in nodedef.inputs}
    return any(spec.type == LATENT for spec in nodedef.outputs) and LATENT in inputs and bool(inputs & {"MODEL", "GUIDER"})


def _follow(facts: CanvasFacts, nodes: dict[str, Node], outgoing: dict[str, list[Link]], first: Node) -> tuple[set[str], list[Node]]:
    """Nodes reached from ``first`` without passing a sampler, and the samplers whose LATENT
    input they feed (a muted sampler is neither followed nor a handoff)."""
    reached: set[str] = set()
    handoffs: dict[str, Node] = {}
    stack = [first.key]
    while stack:
        for link in outgoing.get(stack.pop(), ()):
            target = nodes[str(link.target_id)]
            if target.key == first.key:
                continue
            if _is_sampler(facts, target):
                if target.mode != MUTED and _input_type(facts, target, link) == LATENT:
                    handoffs[target.key] = target
            elif target.key not in reached:
                reached.add(target.key)
                stack.append(target.key)
    return reached, list(handoffs.values())


def _previewed(
    facts: CanvasFacts,
    nodes: dict[str, Node],
    outgoing: dict[str, list[Link]],
    modules: list[set[str]],
    first: Node,
    second: Node,
    reached: set[str],
) -> bool:
    for producer in _stage_images(facts, nodes, outgoing, second, reached):
        if facts.virtual(producer):
            continue
        for output in _output_consumers(facts, nodes, outgoing, producer, IMAGE):
            if _runs_with(modules, first, second, output):
                return True
    return False


def _stage_images(facts: CanvasFacts, nodes: dict[str, Node], outgoing: dict[str, list[Link]], second: Node, reached: set[str]) -> list[Node]:
    """Nodes after the first sampler that are not after the second one: the pictures of the
    first stage, decoded on the way to the second sampler or beside it."""
    after_second = _descendants(outgoing, second.key)
    return [nodes[key] for key in sorted(reached - after_second, key=id_order)]


def _descendants(outgoing: dict[str, list[Link]], key: str) -> set[str]:
    seen: set[str] = set()
    stack = [key]
    while stack:
        for link in outgoing.get(stack.pop(), ()):
            target = str(link.target_id)
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def _output_consumers(facts: CanvasFacts, nodes: dict[str, Node], outgoing: dict[str, list[Link]], producer: Node, type_: str) -> list[Node]:
    """Output nodes fed directly by an output of ``producer`` of ``type_``, links passing
    through frontend-only nodes."""
    found: dict[str, Node] = {}
    seen: set[str] = set()
    stack = [(producer, True)]
    while stack:
        node, is_producer = stack.pop()
        for link in outgoing.get(node.key, ()):
            if is_producer and _output_type(facts, node, link) != type_:
                continue
            target = nodes[str(link.target_id)]
            if facts.virtual(target):
                if target.key not in seen:
                    seen.add(target.key)
                    stack.append((target, False))
                continue
            nodedef = facts.nodedef(target)
            if nodedef is None or nodedef.output_node:
                found[target.key] = target
    return list(found.values())


def _runs_with(modules: list[set[str]], first: Node, second: Node, output: Node) -> bool:
    if output.mode == MUTED:
        return False
    if output.mode != BYPASSED:
        return True
    if first.mode != BYPASSED or second.mode != BYPASSED:
        return False
    return any({first.key, second.key, output.key} <= module for module in modules)


def _bypassed_modules(facts: CanvasFacts) -> list[set[str]]:
    """The optional modules: group boxes whose real nodes are all bypassed and which hold at
    least one. A box is the unit the frontend toggles, so a module split over two boxes is two
    modules whatever the titles say."""
    modules = []
    for group in facts.groups():
        real = [node for node in group.members if not facts.virtual(node)]
        if real and all(node.mode == BYPASSED for node in real):
            modules.append({node.key for node in group.members})
    return modules


def _finding(
    facts: CanvasFacts, nodes: dict[str, Node], outgoing: dict[str, list[Link]], first: Node, second: Node, reached: set[str]
) -> Finding:
    images = [node for node in _stage_images(facts, nodes, outgoing, second, reached) if _makes_image(facts, node)]
    if images:
        place = f"add a PreviewImage on the IMAGE output of node {images[0].key} ({images[0].type})"
    else:
        place = f"decode the output of node {first.key} ({first.type}) and add a PreviewImage on the decoded IMAGE"
    return Finding(
        Code.N7,
        Severity.INFO,
        f"the handoff from node {first.key} ({first.type}) to node {second.key} ({second.type}) has no preview: {place}",
        nodes=(first.key, second.key),
        hint=HINT,
        data={"from": first.key, "to": second.key},
    )


def _makes_image(facts: CanvasFacts, node: Node) -> bool:
    nodedef = facts.nodedef(node)
    return nodedef is not None and not nodedef.virtual and any(spec.type == IMAGE for spec in nodedef.outputs)


def _output_type(facts: CanvasFacts, node: Node, link: Link) -> str | None:
    """The type of the output ``link`` leaves: the canvas slot first, then the definition."""
    if 0 <= link.origin_slot < len(node.outputs):
        slot_type = node.outputs[link.origin_slot].get("type")
        if slot_type:
            return str(slot_type)
    nodedef = facts.nodedef(node)
    if nodedef is not None and 0 <= link.origin_slot < len(nodedef.outputs):
        return nodedef.outputs[link.origin_slot].type
    return str(link.type) if link.type is not None else None


def _input_type(facts: CanvasFacts, node: Node, link: Link) -> str | None:
    if 0 <= link.target_slot < len(node.inputs):
        slot_type = node.inputs[link.target_slot].get("type")
        if slot_type:
            return str(slot_type)
    return str(link.type) if link.type is not None else None


__all__ = ["check_stage_previews"]
