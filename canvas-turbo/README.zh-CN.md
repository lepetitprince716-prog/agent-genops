# ComfyUI-Canvas-Turbo（前端防卡顿插件 + 惰性/清显存配套节点）

零第三方依赖的 ComfyUI 前端防卡顿扩展，专门解决 **200–500+ 节点超大工作流**在 **Classic Canvas** 与 **Vue Nodes 2.0** 下的拖动掉帧、缩放卡死与预览显存泄漏问题。

## 核心能力

1. **缩放自适应 LOD（带迟滞防抖）**：缩放低于 `0.55x` 自动切直线连线并关阴影；低于 `0.28x` 俯瞰模式自动隐藏重型 DOM 控件（`<textarea>`/`<select>`/滑条），拖动全图依然满帧。
2. **Vue Nodes 2.0 离屏 DOM 冻结**：在 `requestAnimationFrame` 合并帧里给视口外节点施加 `content-visibility: hidden` + `contain: layout style paint`，绝不阻塞滚轮/拖拽主线程；始终保持选中、固定、正在执行的节点活跃。
3. **预览图显存预算（LRU + 视口距离淘汰）**：默认限制最多 4 组活跃预览位图 / 16MP 像素预算，自动回收离屏旧预览，防止浏览器 GPU 纹理爆内存。
4. **实时 FPS 遥测 HUD 与一键工作流体检**：右下角轻量浮条实时展示 FPS、p95 帧耗时、活跃节点比与当前 LOD；一键弹出 **0–100 防卡顿体检报告**（精准抓出 `Use Everywhere` 广播节点、嵌套子图、主画布 DOM 膨胀、多预览图泛滥、多底模显存争抢），并附带 **Purge UI** 与 **Flush VRAM** 一键清缓存按钮。
5. **配套零依赖后端节点**：`CanvasTurboVRAMGate`（阶段间显存清仓闸门）与 `CanvasTurboLazyBranchSwitch`（真 `lazy: True` 8 路惰性分支开关）。

## 本地测试与 400 节点压测

```bash
node --test canvas-turbo/tests/test_canvas_turbo_core.mjs
python3 -B -m unittest discover -s canvas-turbo/tests -v
node canvas-turbo/tests/benchmark_400_nodes.mjs
```
