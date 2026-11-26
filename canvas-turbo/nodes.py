"""Companion backend anti-lag nodes for ComfyUI-Canvas-Turbo.

Designed to degrade gracefully outside a live ComfyUI/PyTorch runtime so pure Python
unit tests can verify lazy-evaluation and VRAM-gate contracts deterministically.
"""

from __future__ import annotations

import gc
from typing import Any


class _AnyType(str):
    """ComfyUI wildcard type matching any socket type during graph validation."""

    __hash__ = str.__hash__

    def __ne__(self, other: object) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return True


ANY = _AnyType("*")


def _flush_comfy_vram(unload_models: bool) -> dict[str, bool]:
    """Flush GPU cache and optionally unload cached models via ComfyUI model_management."""
    result = {"gc_collected": False, "models_unloaded": False, "cache_cleared": False}
    try:
        import comfy.model_management as mm  # type: ignore[import-not-found]
    except ImportError:
        mm = None

    if mm is not None:
        if unload_models and hasattr(mm, "unload_all_models"):
            mm.unload_all_models()
            result["models_unloaded"] = True
        if hasattr(mm, "soft_empty_cache"):
            mm.soft_empty_cache()
            result["cache_cleared"] = True

    gc.collect()
    result["gc_collected"] = True
    return result


class CanvasTurboVRAMGate:
    """Explicit VRAM checkpoint passthrough between heavy model engines and post-FX."""

    CATEGORY = "CanvasTurbo/Performance"
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("output",)
    FUNCTION = "execute"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "anything": (ANY,),
                "flush_mode": (
                    ["soft_cache_clear", "unload_models_and_cache", "passthrough_only"],
                    {"default": "unload_models_and_cache"},
                ),
            }
        }

    @classmethod
    def IS_CHANGED(cls, anything: Any = None, flush_mode: str = "unload_models_and_cache") -> float:
        """Force re-execution on every queue so VRAM flushing is never skipped by cache hits."""
        _ = (anything, flush_mode)
        return float("nan")

    def execute(self, anything: Any, flush_mode: str = "unload_models_and_cache") -> tuple[Any]:
        if flush_mode == "unload_models_and_cache":
            _flush_comfy_vram(unload_models=True)
        elif flush_mode == "soft_cache_clear":
            _flush_comfy_vram(unload_models=False)
        return (anything,)


class CanvasTurboLazyBranchSwitch:
    """True ComfyUI lazy-evaluation N-way branch switch (up to 8 inputs).

    Unselected branches are NEVER requested by ComfyUI's execution engine, preventing
    unused checkpoints, preprocessors, or video models from loading or executing.
    """

    MAX_BRANCHES = 8
    CATEGORY = "CanvasTurbo/Performance"
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("selected",)
    FUNCTION = "execute"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        optional = {f"branch_{i}": (ANY, {"lazy": True}) for i in range(cls.MAX_BRANCHES)}
        return {
            "required": {
                "index": ("INT", {"default": 0, "min": 0, "max": cls.MAX_BRANCHES - 1, "step": 1}),
            },
            "optional": optional,
        }

    def check_lazy_status(self, index: int = 0, **kwargs: Any) -> list[str]:
        clamped = max(0, min(self.MAX_BRANCHES - 1, int(index)))
        key = f"branch_{clamped}"
        if kwargs.get(key) is None:
            return [key]
        return []

    def execute(self, index: int = 0, **kwargs: Any) -> tuple[Any]:
        clamped = max(0, min(self.MAX_BRANCHES - 1, int(index)))
        key = f"branch_{clamped}"
        return (kwargs.get(key),)


NODE_CLASS_MAPPINGS = {
    "CanvasTurboVRAMGate": CanvasTurboVRAMGate,
    "CanvasTurboLazyBranchSwitch": CanvasTurboLazyBranchSwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CanvasTurboVRAMGate": "VRAM Checkpoint Gate [CanvasTurbo]",
    "CanvasTurboLazyBranchSwitch": "Lazy Branch Switch (8-Way) [CanvasTurbo]",
}
