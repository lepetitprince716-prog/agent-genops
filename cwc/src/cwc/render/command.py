"""``cwc render GRAPH.ui.json -o OUT.svg``: draw a canvas without a browser."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, TextIO

from cwc import TOOL_NAME
from cwc.emit.canonical import json_bytes, write_atomic
from cwc.ingest import load_canvas, read_file
from cwc.nodedefs.registry import NodeDefs, read_source
from cwc.render.skin import Theme, render_diagram
from cwc.render.svg import render
from cwc.report import CwcError, ExitCode

SKINS = ("debug", "diagram")


def command(args: argparse.Namespace, out: TextIO, err: TextIO) -> ExitCode:
    if args.skin == "debug" and args.theme is not None:
        return _fail(args, out, err, ExitCode.USAGE, "--theme applies to --skin diagram only")
    try:
        canvas = load_canvas(read_file(args.graph, "canvas file"))
        defs = NodeDefs.load(
            object_info=read_source(args.nodedefs) if args.nodedefs else None,
            include_custom=bool(getattr(args, "custom_packs", False)),
        )
    except CwcError as exc:
        return _fail(args, out, err, exc.exit_code, "; ".join(finding.message for finding in exc.findings))
    if args.skin == "diagram":
        rendering = render_diagram(canvas, defs, Theme(args.theme or Theme.LIGHT.value))
    else:
        rendering = render(canvas, defs, show_values=bool(getattr(args, "values", False)))
    target = Path(args.output)
    try:
        write_atomic(target, rendering.svg.encode("utf-8"))
    except OSError as exc:
        return _fail(args, out, err, ExitCode.WRITE_FAILED, f"cannot write to {target}: {exc.strerror or exc}")
    if args.json:
        summary: dict[str, Any] = {
            "ok": True,
            "exit_code": int(ExitCode.OK),
            "output": str(target),
            "view_box": [round(v, 2) for v in rendering.view_box],
            "drawn": {
                "groups": rendering.groups,
                "nodes": rendering.nodes,
                "links": rendering.links,
                "links_unresolved": rendering.links_unresolved,
                "reroutes": rendering.reroutes,
            },
        }
        out.write(json_bytes(summary).decode("utf-8"))
    else:
        out.write(f"wrote {target}\n")
    return ExitCode.OK


def _fail(args: argparse.Namespace, out: TextIO, err: TextIO, code: ExitCode, message: str) -> ExitCode:
    err.write(f"{TOOL_NAME} render: {message}\n")
    if args.json:
        out.write(json_bytes({"ok": False, "exit_code": int(code), "error": message}).decode("utf-8"))
    return code
