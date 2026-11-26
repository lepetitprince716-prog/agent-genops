"""The compile pipeline: an authoring document to a verified canvas and its prompts.

Stages: normalize -> instantiate -> annotate -> apply_notes -> layout -> route -> verify
(``verify_compile`` and ``check_geometry`` in compile mode, merged into one report). Every
stage reads the previous stage's output only. Notes and the guide (M3) are not written yet.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from cwc.annotate import annotate, apply_notes
from cwc.annotate.types import PlanCounts
from cwc.canvas.model import Canvas, id_order
from cwc.effects import authoring_effects, overridden_keys
from cwc.instantiate import instantiate
from cwc.layout import GUIDE_HEIGHT, layout
from cwc.canvas.geometry import snap_up
from cwc.layout.presets import DEFAULT, load_presets
from cwc.layout.section import BAND_GAP, SCREEN_W
from cwc.layout.types import HideLinks, LayoutResult
from cwc.nodedefs.derive import widget_layout
from cwc.nodedefs.registry import NodeDefs
from cwc.normalize import normalize
from cwc.normalize.types import Authoring
from cwc.notes import has_guide_content, measure_guide_bottom, place_guide
from cwc.prompt.from_canvas import canvas_to_prompt
from cwc.prompt.model import Prompt, is_link, prompt_diff
from cwc.render.notes import collect_notes, write_notes
from cwc.report import Code, CwcError, ExitCode, Finding, Mode, Report, Severity
from cwc.route import RouteResult, route
from cwc.route.presentation import mark_hidden
from cwc.subgraph import pack_subgraphs as pack_canvas_subgraphs
from cwc.verify import verify_compile
from cwc.verify.equivalence import all_enabled
from cwc.verify.geometry import check_geometry

AUTO = "auto"  # choose the preset from the plan's counts (:func:`choose_auto`)
AUTHORED = "_workflow.layout.preset"

# The automatic choice's thresholds (small graphs, many parallel control branches, large graphs;
# docs/ARCHITECTURE.md, row ``pipeline``). Code, not data: the rules' order and comparisons
# are code anyway, and the presets
# document holds only the presets themselves.
AUTO_SMALL_NODES = 16  # at most this many nodes, and no optional module: tower-preview
AUTO_PARALLEL_BRANCHES = 3  # at least this many control or mask branches: swimlanes
AUTO_LARGE_NODES = 60  # at least this many nodes: cockpit-split


def preset_guide() -> dict[str, tuple[str, str]]:
    """`cwc presets`: what each preset looks like and when to pick it, by name, ``auto`` last.

    Only what layout does today: the corridors the presets name are reserved space, and the
    router does not use them yet (docs/ARCHITECTURE.md), so no description promises them for
    links. Numbers come from the presets document and the layout constants. A test keeps the
    names here and in presets.json the same, and measures the geometry described."""
    presets = load_presets()
    bento, tower, stack = presets["bento"], presets["tower-preview"], presets["stack"]
    preview = tower.preview
    assert preview is not None  # the presets document gives tower-preview its preview
    preview_w = snap_up(round(preview.share * SCREEN_W, 6))
    wrap = f"The main row wraps onto a new row below when it gets wider than {bento.wrap_ratio:g} times its height."
    columns = (
        "every other group in one row of columns in data-flow order, a control branch in the column of "
        "the stage it steers, no second row"
    )
    return {
        "bento": (
            "Controls group first, then models and prompts side by side, sampling, post-processing and output "
            f"in one main row; control branches and optional modules in a second row below it. {wrap}",
            "most graphs; the default",
        ),
        "swimlanes": (
            f"Controls group first, then {columns}; an empty strip {BAND_GAP} px high above each row.",
            f"several parallel control or mask branches (auto picks it at {AUTO_PARALLEL_BRANCHES} or more)",
        ),
        "cockpit-split": (
            "Controls group first, split in two boxes when it holds both kinds: prompts, reference image, size "
            f"and seed in the top box, the other controls in a box under it. Then a gap of {BAND_GAP} px and "
            f"{columns}.",
            f"large graphs (auto picks it at {AUTO_LARGE_NODES} nodes or more)",
        ),
        "tower-preview": (
            "The bento arrangement. When the output group holds a node that shows an image preview, the group "
            f"is at least {preview_w} px wide and {preview.min_height} px high and the preview node grows to "
            "fill it.",
            f"small graphs whose result you look at while tuning (auto picks it at {AUTO_SMALL_NODES} nodes or "
            "fewer with no optional module)",
        ),
        "stepped": (
            "Groups titled Step 1, Step 2 and so on; the models and Controls groups one above "
            "the other in the first column, then prompts, sampling, post-processing and output; control "
            "branches and optional modules in a second row.",
            "a graph meant to be followed in order, like a tutorial",
        ),
        "stack": (
            "Every group a box read top to bottom, Controls first: in a box the main chain runs down the "
            "middle, the nodes that feed it stand to its left and the previews of its stages to its right. "
            "The boxes stack in columns, and a column higher than "
            f"{stack.wrap_ratio:g} times the canvas's width wraps into a new column on its right. An optional "
            "module is one box.",
            "a staged graph read top to bottom like an architecture diagram, with a preview per stage",
        ),
        "gallery": (
            f"Controls stays paired with the top pipeline row (separated by {BAND_GAP} px; tall "
            "cockpits of 5+ controls split side by side) with the final output flush on the right; "
            "intermediate step previews, control branches and optional comparisons dock below the "
            f"stages that feed them with enlarged preview viewports (at least "
            f"{snap_up(round(presets['gallery'].preview.share * SCREEN_W, 6))} px wide and "
            f"{presets['gallery'].preview.min_height} px high).",
            "multi-step workflows with intermediate step previews or side-by-side comparisons",
        ),
        "square": (
            f"2D minimal-area compact dashboard layout: searches balanced stacked rows (wrapping past "
            f"{presets['square'].wrap_ratio:g}x height), vertical column bin-packing of short stages, "
            "skyline lower-band tucking, and sidebar nesting under the measured Quick Guide card to "
            "minimize total bounding-box area and maximize node area utilization; docks step previews "
            "and optional comparisons inside each row's width with enlarged viewports (at least "
            f"{snap_up(round(presets['square'].preview.share * SCREEN_W, 6))} px wide and "
            f"{presets['square'].preview.min_height} px high).",
            "minimal-area 4:3/square showcase screenshots, laptops, or dense multi-stage graphs without wide scrolling",
        ),
        AUTO: (
            f"Picks a preset from the graph's counts, the first rule that holds: at most {AUTO_SMALL_NODES} "
            f"nodes and no optional module: tower-preview; {AUTO_PARALLEL_BRANCHES} or more control or mask "
            f"branches: swimlanes; {AUTO_LARGE_NODES} nodes or more: cockpit-split; otherwise: bento. The "
            "compile summary and the report say which rule held.",
            "you have no preference",
        ),
    }


@dataclass(frozen=True)
class AutoChoice:
    preset: str
    rule: str  # the rule that matched, for the report and error messages


@dataclass(frozen=True)
class Compiled:
    authoring: Authoring
    canvas: Canvas
    report: Report  # verification and geometry findings plus the authoring warnings
    layout: LayoutResult
    routes: RouteResult
    counts: PlanCounts  # what auto read; the command line's summary reports the optional modules


def _remap_packed_prompt(prompt: Prompt, id_map: dict[str, str]) -> Prompt:
    """Map flattened ``<inst>:<inner>`` keys back to original flat node keys for exact diff verification."""
    if not id_map:
        return prompt
    out: Prompt = {}
    for key, entry in prompt.items():
        mapped_key = id_map.get(key, key)
        new_inputs = {}
        for iname, val in entry.get("inputs", {}).items():
            if is_link(val):
                new_inputs[iname] = [id_map.get(val[0], val[0]), val[1]]
            else:
                new_inputs[iname] = val
        out[mapped_key] = {**entry, "inputs": new_inputs}
    return out


def compile_document(
    doc: dict[str, Any],
    defs: NodeDefs,
    *,
    allow_unknown: bool = False,
    preset: str | None = None,
    portable: bool = False,
    hide_links: HideLinks | None = None,
    guide_note: bool | None = None,
    pack_subgraphs: bool = False,
) -> Compiled:
    """Compile a parsed authoring document.

    The layout preset is ``preset`` when given, else the document's ``_workflow.layout.preset``,
    else ``bento``; ``auto`` (from either place) picks one after annotate by :func:`choose_auto`,
    and the report's ``metrics["preset_auto"]`` then records the rule and the counts.
    ``hide_links`` overrides the preset's own choice of which links are written hidden
    (:mod:`cwc.route.presentation`). Raises ``CwcError(INPUT_ERROR)`` for authoring errors (E1-E7), for an
    unknown preset name, and for a preset layout does not implement yet (E7), also when
    ``auto`` chose it: it never falls back to another preset. Verification
    and geometry failures do not raise: they are errors in the returned report, and
    ``report.ok`` is false.
    """
    authoring, warnings = normalize(doc, defs, allow_unknown=allow_unknown, portable=portable)
    name = _choose(preset, authoring.workflow.preset)
    canvas = instantiate(authoring)
    plan = annotate(canvas, defs, authoring)
    apply_notes(canvas, plan)
    auto = choose_auto(plan.counts) if name == AUTO else None
    chosen = load_presets()[auto.preset if auto is not None else name]
    emit_guide = chosen.guide_note if guide_note is None else guide_note
    try:
        if chosen.compact and plan.reserve_guide:
            if not (emit_guide and has_guide_content(authoring)):
                if chosen.compact_under_guide:
                    laid = layout(canvas, plan, chosen, defs, guide_height=0.0)
                else:
                    laid = layout(canvas, plan, chosen, defs)
            else:
                laid = layout(canvas, plan, chosen, defs)
                real_guide_h = measure_guide_bottom(canvas, authoring, plan, laid, chosen, defs)
                if real_guide_h != float(GUIDE_HEIGHT):
                    laid = layout(canvas, plan, chosen, defs, guide_height=real_guide_h)
        else:
            laid = layout(canvas, plan, chosen, defs)
    except NotImplementedError as exc:
        if auto is None:
            message = f"preset {chosen.name!r} is not available yet: {exc}"
        else:
            message = (
                f"preset {AUTO!r} is not available yet for this graph: it chose {chosen.name!r} "
                f"({auto.rule}; {_counts_text(plan.counts)}), and {exc}"
            )
        raise CwcError(ExitCode.INPUT_ERROR, [_preset_error(message)]) from None
    if emit_guide:
        _, laid = place_guide(canvas, authoring, plan, laid, chosen, defs)
    routes = route(canvas, laid, defs)
    mark_hidden(canvas, laid.forced, chosen.hide_links if hide_links is None else hide_links, defs)
    write_notes(canvas, collect_notes(authoring, plan, laid, canvas))
    report = verify_compile(canvas, authoring, defs)
    geometry = check_geometry(
        canvas, defs, mode=Mode.COMPILE, membership=laid.membership, preset=chosen, cockpit=laid.cockpit
    )
    report.extend(_with_unresolved(geometry.findings, canvas, routes))
    report.metrics["preset"] = chosen.name
    if auto is not None:
        report.metrics["preset_auto"] = {"rule": auto.rule, **_counts_json(plan.counts)}
    report.metrics["geometry"] = geometry.metrics
    report.metrics["route"] = _route_metrics(routes)
    effects = authoring_effects(authoring, plan, canvas)
    report.metrics["authoring_keys"] = effects
    report.extend(warnings)
    report.extend(overridden_keys(authoring, effects))
    report.extend(authoring.notices)
    if pack_subgraphs and report.ok:
        packed = pack_canvas_subgraphs(canvas, defs, skip_group_indices=laid.cockpit)
        # Verify exact round-trip prompt equivalence for both factory and all-enabled states
        for state_name, code, expected, target_canvas in (
            ("factory-state", Code.Q2, authoring.factory, packed.canvas),
            ("all-enabled", Code.Q1, authoring.full, all_enabled(packed.canvas)),
        ):
            try:
                exported = canvas_to_prompt(target_canvas, defs, widget_layout=widget_layout, expand_subgraphs=True)
                remapped = _remap_packed_prompt(exported, packed.id_map)
                diff = prompt_diff(expected, remapped)
                if diff:
                    report.findings.append(
                        Finding(
                            code,
                            Severity.ERROR,
                            f"packed subgraph {state_name} canvas differs from strict prompt in {len(diff)} place(s)",
                            data={"diff": diff},
                        )
                    )
            except ValueError as exc:
                report.findings.append(
                    Finding(code, Severity.ERROR, f"packed subgraph {state_name} export failed: {exc}")
                )
        packed_routes = route(packed.canvas, replace(laid, waypoints={}, forced=(), tracks={}), defs)
        routes = packed_routes
        canvas = packed.canvas
        report.metrics["route"] = _route_metrics(packed_routes)
        report.metrics["subgraphs"] = packed.metrics()
    return Compiled(authoring, canvas, report, laid, routes, plan.counts)


def choose_auto(counts: PlanCounts) -> AutoChoice:
    """The preset ``auto`` picks: the first rule that holds, in the order of
    docs/ARCHITECTURE.md (a small graph with no optional module beats many control branches,
    which beat a large graph)."""
    if counts.nodes <= AUTO_SMALL_NODES and counts.optional_modules == 0:
        return AutoChoice("tower-preview", f"at most {AUTO_SMALL_NODES} nodes and no optional module")
    if counts.control_branches >= AUTO_PARALLEL_BRANCHES:
        return AutoChoice("swimlanes", f"at least {AUTO_PARALLEL_BRANCHES} control or mask branches")
    if counts.nodes >= AUTO_LARGE_NODES:
        return AutoChoice("cockpit-split", f"at least {AUTO_LARGE_NODES} nodes")
    return AutoChoice(DEFAULT, "no other rule holds")


def _counts_json(counts: PlanCounts) -> dict[str, int]:
    return {"nodes": counts.nodes, "optional_modules": counts.optional_modules, "control_branches": counts.control_branches}


def _counts_text(counts: PlanCounts) -> str:
    return ", ".join(f"{key} {value}" for key, value in _counts_json(counts).items())


def _choose(given: str | None, authored: str | None) -> str:
    """The preset name by priority: ``given`` (the command line), the authored one, the default;
    ``auto`` is resolved later, from the plan. An unknown authored name is an error even when
    ``given`` overrides it: a misspelt name would otherwise go unnoticed until the override is
    dropped."""
    presets = load_presets()
    unknown = [
        _preset_error(f"unknown preset {name!r}{where}")
        for where, name in (("", given), (f" in {AUTHORED}", authored))
        if name is not None and name != AUTO and name not in presets
    ]
    if unknown:
        raise CwcError(ExitCode.INPUT_ERROR, unknown)
    return given if given is not None else authored if authored is not None else DEFAULT


def _preset_error(message: str) -> Finding:
    names = ", ".join(sorted([*load_presets(), AUTO]))
    return Finding(Code.E7, Severity.ERROR, message, hint=f"presets: {names}")


def _with_unresolved(findings: list[Finding], canvas: Canvas, routes: RouteResult) -> list[Finding]:
    """``findings`` with one G2 error per link routing could not keep out of node boxes (it keeps
    its plain spline): the geometry check's own G2 for that link, marked ``unresolved``, or one of
    the router's when the check did not report it."""
    stuck = frozenset(routes.unresolved)
    reported: list[int] = []
    out = []
    for finding in findings:
        link_id = finding.data.get("link") if finding.code is Code.G2 else None
        if link_id in stuck:
            reported.append(link_id)
            finding = replace(finding, data={**finding.data, "unresolved": True})
        out.append(finding)
    links = {link.id: link for link in canvas.links}
    for link_id in routes.unresolved:
        if link_id in reported:
            continue
        link = links[link_id]
        ends = (str(link.origin_id), str(link.target_id))
        out.append(
            Finding(
                Code.G2,
                Severity.ERROR,
                f"routing found no path for link {link_id} from node {ends[0]} to node {ends[1]} clear of node boxes",
                nodes=tuple(sorted(set(ends), key=id_order)),
                data={"link": link_id, "unresolved": True},
            )
        )
    return out


def _route_metrics(routes: RouteResult) -> dict[str, Any]:
    return {
        "rerouted": len(routes.rerouted),
        "dummy": routes.dummy,
        "unresolved": list(routes.unresolved),
        "short_channels": len(routes.shortfalls),
        "shared_edges": routes.shared_edges,
    }
