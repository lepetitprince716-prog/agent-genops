"""ComfyUI-Canvas-Turbo: Frontend Anti-Lag Extension & Lazy/VRAM Companion Nodes.

Installs as a standard ComfyUI custom node pack (``WEB_DIRECTORY = "./web"``).
Provides:
1. Frontend anti-lag engine (``web/canvas_turbo.js`` + ``web/canvas_turbo_core.mjs``):
   zoom-adaptive LOD rendering, offscreen Vue Nodes 2.0 DOM freezing, preview texture
   budget eviction, live FPS telemetry HUD, and one-click workflow lag auditing.
2. Zero-dependency companion backend nodes (``CanvasTurboVRAMGate`` and
   ``CanvasTurboLazyBranchSwitch`` with genuine ComfyUI ``lazy: True`` evaluation).
"""

from __future__ import annotations

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
