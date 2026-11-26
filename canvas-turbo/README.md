# ComfyUI-Canvas-Turbo (`v1.0`)

A lightweight, zero-dependency ComfyUI frontend anti-lag extension and companion lazy/VRAM node pack built specifically for 200–500+ node mega-workflows across **both Classic LiteGraph Canvas and Vue Nodes 2.0**.

## What It Fixes

1. **Zoom-Adaptive LOD Rendering**: Automatically switches spline curves to linear links and disables node shadows below `0.55x` zoom, and hides heavy DOM inputs/widgets below `0.28x` overview zoom (with hysteresis so boundary zooming never flickers).
2. **Offscreen Vue Nodes 2.0 DOM Freeze**: Applies `content-visibility: hidden` + `contain: layout style paint` to offscreen `[data-node-id]` wrappers inside `requestAnimationFrame` coalesced passes (never forces synchronous layout inside wheel/pan handlers), always preserving selected, pinned, and executing nodes.
3. **Preview Bitmap Texture Budget**: LRU + viewport-distance eviction keeps at most `N` (default `4`, max `16 MP`) decoded `node.imgs` preview bitmaps live in browser memory.
4. **Live Anti-Lag Auditor & HUD**: Floating corner badge (`FPS / p95 ms / Visible Ratio / LOD`) with 1-click **Audit** (scores any workflow `0–100` and flags `Use Everywhere` broadcast nodes, nested subgraphs, root DOM bloat, preview bloat, and multi-checkpoint VRAM contention), **Purge UI**, and **Flush VRAM** (`/free`).
5. **Companion Backend Nodes**:
   - `CanvasTurboVRAMGate`: Explicit passthrough VRAM checkpoint (`soft_cache_clear` / `unload_models_and_cache` / `passthrough_only`).
   - `CanvasTurboLazyBranchSwitch`: True ComfyUI `lazy: True` (`check_lazy_status`) 8-way switch so unselected branches never load or execute.

## Install into ComfyUI

Copy or symlink `canvas-turbo/` into `ComfyUI/custom_nodes/ComfyUI-Canvas-Turbo` and restart ComfyUI. No extra `pip` dependencies are required.

## Run Tests & 400-Node Stress Benchmark

```bash
node --test canvas-turbo/tests/test_canvas_turbo_core.mjs
python3 -B -m unittest discover -s canvas-turbo/tests -v
node canvas-turbo/tests/benchmark_400_nodes.mjs
```
