/**
 * ComfyUI-Canvas-Turbo Frontend Anti-Lag Extension.
 *
 * Works non-destructively across both Classic LiteGraph Canvas and Vue Nodes 2.0:
 * - Zoom-Adaptive LOD rendering (linear links & minimal chrome when zoomed out)
 * - Viewport Offscreen Vue DOM Freeze (`content-visibility: hidden` + CSS containment)
 * - Preview Bitmap LRU/Distance Eviction (prevents WebGL texture memory bloat)
 * - Real-Time FPS / DOM / Anti-Lag Score HUD + 1-Click Audit & VRAM/Cache Purge
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import {
  DEFAULT_CONFIG,
  FrameMetricsTracker,
  auditWorkflowGraph,
  computeVisibleSet,
  computeWorldViewport,
  planPreviewEviction,
  selectLodTier,
} from "./canvas_turbo_core.mjs";

const PATCH_GUARD = Symbol.for("omnistudio.canvasTurbo.patched");

const state = {
  enabled: true,
  lodEnabled: true,
  vueDomCullEnabled: true,
  previewCapEnabled: true,
  hudVisible: true,
  maxPreviewBitmaps: DEFAULT_CONFIG.maxPreviewBitmaps,
  maxPreviewMegapixels: DEFAULT_CONFIG.maxPreviewMegapixels,
  currentLod: "full",
  tick: 0,
  lastSeenByNodeId: new Map(),
  evictedPreviewSrcs: new WeakMap(),
  lastCullSignature: "",
  visibleIds: new Set(),
  offscreenIds: new Set(),
  executingNodeId: null,
  isGenerating: false,
  rafScheduled: false,
  tracker: new FrameMetricsTracker(),
  hudEl: null,
  modalEl: null,
  lastHudUpdateMs: 0,
};

function readSetting(id, fallback) {
  try {
    const val = app?.ui?.settings?.getSettingValue?.(id);
    return val === undefined ? fallback : val;
  } catch {
    return fallback;
  }
}

function syncSettings() {
  state.enabled = Boolean(readSetting("CanvasTurbo.Enabled", true));
  state.lodEnabled = Boolean(readSetting("CanvasTurbo.ZoomLOD", true));
  state.vueDomCullEnabled = Boolean(readSetting("CanvasTurbo.VueDomCulling", true));
  state.previewCapEnabled = Boolean(readSetting("CanvasTurbo.PreviewCap", true));
  state.hudVisible = Boolean(readSetting("CanvasTurbo.ShowHUD", true));
  state.maxPreviewBitmaps = Number(readSetting("CanvasTurbo.MaxPreviews", DEFAULT_CONFIG.maxPreviewBitmaps));
  if (state.hudEl) {
    state.hudEl.style.display = state.enabled && state.hudVisible ? "flex" : "none";
  }
}

/**
 * Apply or clear offscreen CSS freeze on Vue Nodes 2.0 DOM wrappers.
 * Coalesced inside requestAnimationFrame so wheel/drag handlers never force sync reflow.
 */
function applyVueDomCulling(visibleIds, offscreenIds, lodTier) {
  if (typeof document === "undefined") return;
  const domNodes = document.querySelectorAll("[data-node-id]");
  if (!domNodes.length) return;

  const hideHeavyInputs = state.enabled && state.lodEnabled && lodTier === "overview";
  for (const el of domNodes) {
    const rawId = el.getAttribute("data-node-id");
    const numId = Number(rawId);
    const hasMatch =
      offscreenIds.has(rawId) || (rawId !== null && rawId !== "" && !Number.isNaN(numId) && offscreenIds.has(numId));
    const isOffscreen = state.enabled && state.vueDomCullEnabled && hasMatch;

    if (isOffscreen) {
      if (el.dataset.ctCulled !== "1") {
        el.dataset.ctCulled = "1";
        el.style.contentVisibility = "hidden";
        el.style.contain = "layout style paint";
        el.style.pointerEvents = "none";
      }
    } else if (el.dataset.ctCulled === "1") {
      delete el.dataset.ctCulled;
      el.style.contentVisibility = "";
      el.style.contain = "";
      el.style.pointerEvents = "";
    }

    if (!isOffscreen) {
      el.classList.toggle("ct-lod-overview", hideHeavyInputs);
    }
  }
}

function enforcePreviewBudget(graphNodes, visibleIds) {
  if (!state.enabled || !state.previewCapEnabled) return 0;
  const entries = [];
  let totalBitmaps = 0;
  let totalPixels = 0;
  // Restore evicted previews automatically when a node scrolls back into view
  for (const node of graphNodes) {
    if (visibleIds.has(node.id) && (!Array.isArray(node.imgs) || node.imgs.length === 0)) {
      const cachedSrcs = state.evictedPreviewSrcs.get(node);
      if (Array.isArray(cachedSrcs) && cachedSrcs.length > 0 && typeof Image === "function") {
        node.imgs = cachedSrcs.map((src) => {
          const img = new Image();
          img.src = src;
          return img;
        });
        state.evictedPreviewSrcs.delete(node);
      }
    }
  }

  for (const node of graphNodes) {
    const imgs = node?.imgs;
    if (!Array.isArray(imgs) || imgs.length === 0) continue;
    const isExec =
      state.executingNodeId !== null &&
      state.executingNodeId !== undefined &&
      String(node.id) === String(state.executingNodeId);
    if (visibleIds.has(node.id) || isExec) {
      state.lastSeenByNodeId.set(node.id, state.tick);
    }
    const first = imgs[0];
    const w = Number(first?.naturalWidth || first?.width || 512);
    const h = Number(first?.naturalHeight || first?.height || 512);
    totalBitmaps += imgs.length;
    totalPixels += w * h * imgs.length;
    entries.push({
      nodeId: node.id,
      visible: visibleIds.has(node.id),
      pinned: Boolean(node.flags?.pinned),
      executing: isExec,
      lastSeenTick: state.lastSeenByNodeId.get(node.id) ?? 0,
      width: w,
      height: h,
      count: imgs.length,
    });
  }
  const maxPixels = state.maxPreviewMegapixels * 1_000_000;
  if (totalBitmaps <= state.maxPreviewBitmaps && totalPixels <= maxPixels) return 0;

  const plan = planPreviewEviction(entries, {
    maxPreviewBitmaps: state.maxPreviewBitmaps,
    maxPreviewMegapixels: state.maxPreviewMegapixels,
  });
  const evictSet = new Set(plan.evictIds);
  let evicted = 0;
  for (const node of graphNodes) {
    if (evictSet.has(node.id) && Array.isArray(node.imgs) && node.imgs.length > 0) {
      const srcs = node.imgs.map((img) => img?.src).filter(Boolean);
      if (srcs.length > 0) {
        state.evictedPreviewSrcs.set(node, srcs);
      }
      node.imgs = [];
      node.imageIndex = null;
      evicted += 1;
    }
  }
  return evicted;
}

function runFrameOptimizationPass() {
  state.rafScheduled = false;
  const canvas = app?.canvas;
  const graph = app?.graph;
  if (!canvas || !graph) return;

  const nodes = Array.isArray(graph._nodes) ? graph._nodes : [];
  const ds = canvas.ds;
  const cw = canvas.canvas?.clientWidth || window.innerWidth || 1280;
  const ch = canvas.canvas?.clientHeight || window.innerHeight || 720;

  const viewport = computeWorldViewport(ds, cw, ch, DEFAULT_CONFIG.viewportMarginPx);
  state.currentLod = state.enabled && state.lodEnabled
    ? selectLodTier(viewport.scale, state.currentLod, DEFAULT_CONFIG)
    : "full";

  const selectedIds = new Set();
  for (const k of Object.keys(canvas.selected_nodes || {})) {
    selectedIds.add(k);
    const nk = Number(k);
    if (!Number.isNaN(nk)) selectedIds.add(nk);
  }
  const vis = computeVisibleSet(nodes, viewport, {
    selectedIds,
    executingId: state.executingNodeId,
  });
  state.visibleIds = vis.visibleIds;
  state.offscreenIds = vis.offscreenIds;
  state.tick += 1;

  // Coalesce DOM mutations only when viewport/LOD/node count actually changed
  const sig = `${state.enabled}:${state.vueDomCullEnabled}:${state.currentLod}:${vis.visibleCount}:${vis.offscreenCount}:${Math.round(viewport.minX / 64)}:${Math.round(viewport.minY / 64)}`;
  if (sig !== state.lastCullSignature) {
    state.lastCullSignature = sig;
    applyVueDomCulling(vis.visibleIds, vis.offscreenIds, state.currentLod);
  }
  // Always check preview texture budget (O(k log k) over preview nodes only) so newly arrived
  // images after queue completion are capped immediately without waiting for pan/zoom.
  enforcePreviewBudget(nodes, vis.visibleIds);
}

function scheduleOptimizationPass() {
  if (state.rafScheduled) return;
  state.rafScheduled = true;
  requestAnimationFrame(runFrameOptimizationPass);
}

function injectStyles() {
  if (typeof document === "undefined" || document.getElementById("canvas-turbo-style")) return;
  const style = document.createElement("style");
  style.id = "canvas-turbo-style";
  style.textContent = `
    .ct-lod-overview textarea,
    .ct-lod-overview select,
    .ct-lod-overview input[type="range"] {
      visibility: hidden !important;
      pointer-events: none !important;
    }
    #canvas-turbo-hud {
      position: fixed;
      right: 16px;
      bottom: 16px;
      z-index: 9990;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 10px;
      background: rgba(16, 22, 31, 0.9);
      border: 1px solid rgba(88, 166, 255, 0.35);
      color: #e6edf3;
      font: 600 12px/1.3 Inter, system-ui, sans-serif;
      backdrop-filter: blur(8px);
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
      user-select: none;
    }
    #canvas-turbo-hud button {
      background: #1f334a;
      color: #c9d1d9;
      border: 1px solid #304966;
      border-radius: 6px;
      padding: 3px 7px;
      font: 600 11px Inter, system-ui, sans-serif;
      cursor: pointer;
    }
    #canvas-turbo-hud button:hover {
      background: #2b496b;
      color: #ffffff;
    }
    #canvas-turbo-modal {
      position: fixed;
      right: 16px;
      bottom: 62px;
      z-index: 9991;
      width: 420px;
      max-height: 60vh;
      overflow-y: auto;
      padding: 14px;
      border-radius: 12px;
      background: rgba(15, 20, 28, 0.96);
      border: 1px solid #2f4b6e;
      color: #e6edf3;
      font: 12px/1.45 Inter, system-ui, sans-serif;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
    }
  `;
  document.head.appendChild(style);
}

function openAuditModal() {
  if (typeof document === "undefined") return;
  if (state.modalEl) {
    state.modalEl.remove();
    state.modalEl = null;
    return;
  }
  const serialized = app?.graph?.serialize?.() || { nodes: [], links: [] };
  const report = auditWorkflowGraph(serialized);

  const modal = document.createElement("div");
  modal.id = "canvas-turbo-modal";

  const title = document.createElement("div");
  title.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-weight:700;font-size:13px;";
  const heading = document.createElement("span");
  heading.textContent = `Canvas Turbo Audit — Score ${report.score}/100 (Grade ${report.grade})`;
  const closeBtn = document.createElement("button");
  closeBtn.textContent = "Close";
  closeBtn.onclick = () => {
    modal.remove();
    state.modalEl = null;
  };
  title.append(heading, closeBtn);

  const summary = document.createElement("div");
  summary.style.cssText = "color:#8b949e;margin-bottom:10px;";
  summary.textContent =
    `Root: ${report.metrics.rootNodes} nodes | Subgraphs: ${report.metrics.subgraphCount} ` +
    `(${report.metrics.internalNodes} internal, ${report.metrics.domReductionPct}% DOM saved) | ` +
    `UE nodes: ${report.metrics.ueCount} | Active previews: ${report.metrics.rootPreviews}`;

  const list = document.createElement("div");
  if (report.findings.length === 0) {
    const ok = document.createElement("div");
    ok.style.color = "#7ee787";
    ok.textContent = "No anti-lag anti-patterns detected. Canvas is running at peak efficiency.";
    list.appendChild(ok);
  } else {
    for (const f of report.findings) {
      const row = document.createElement("div");
      row.style.cssText = "padding:6px 8px;margin-bottom:6px;border-radius:6px;background:#1a2230;border-left:3px solid #f85149;";
      row.textContent = `[${f.severity.toUpperCase()}] ${f.code}: ${f.message}`;
      list.appendChild(row);
    }
  }

  modal.append(title, summary, list);
  document.body.appendChild(modal);
  state.modalEl = modal;
}

async function purgeCaches(unloadModels) {
  const nodes = Array.isArray(app?.graph?._nodes) ? app.graph._nodes : [];
  for (const node of nodes) {
    if (Array.isArray(node.imgs) && node.imgs.length > 0 && !state.visibleIds.has(node.id)) {
      node.imgs = [];
      node.imageIndex = null;
    }
  }
  try {
    await api.fetchApi("/free", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unload_models: Boolean(unloadModels), free_memory: true }),
    });
  } catch {
    // Ignore when backend /free endpoint is unavailable
  }
  app?.canvas?.setDirty?.(true, true);
}

function mountHud() {
  if (typeof document === "undefined" || state.hudEl) return;
  injectStyles();
  const hud = document.createElement("div");
  hud.id = "canvas-turbo-hud";

  const statsSpan = document.createElement("span");
  statsSpan.id = "canvas-turbo-stats";
  statsSpan.textContent = "⚡ Turbo: 60 FPS | LOD: full";

  const auditBtn = document.createElement("button");
  auditBtn.textContent = "Audit";
  auditBtn.title = "Inspect Anti-Lag Score & culprits";
  auditBtn.onclick = openAuditModal;

  const cacheBtn = document.createElement("button");
  cacheBtn.textContent = "Purge UI";
  cacheBtn.title = "Evict offscreen preview textures & free temporary cache";
  cacheBtn.onclick = () => purgeCaches(false);

  const vramBtn = document.createElement("button");
  vramBtn.textContent = "Flush VRAM";
  vramBtn.title = "Unload cached GPU models & free VRAM cleanly";
  vramBtn.onclick = () => purgeCaches(true);

  hud.append(statsSpan, auditBtn, cacheBtn, vramBtn);
  document.body.appendChild(hud);
  state.hudEl = hud;
  syncSettings();
}

function updateHud(nowMs) {
  if (!state.hudEl || !state.enabled || !state.hudVisible) return;
  if (nowMs - state.lastHudUpdateMs < 400) return;
  state.lastHudUpdateMs = nowMs;

  const snap = state.tracker.snapshot();
  const total = state.visibleIds.size + state.offscreenIds.size;
  const statsEl = state.hudEl.querySelector("#canvas-turbo-stats");
  if (statsEl) {
    statsEl.textContent =
      `⚡ ${snap.fps} FPS (${snap.p95Ms}ms) | Visible ${state.visibleIds.size}/${total} | LOD: ${state.currentLod}`;
  }
}

function patchCanvasNonDestructively(canvas) {
  const proto = Object.getPrototypeOf(canvas);
  if (!proto || proto[PATCH_GUARD]) return;
  proto[PATCH_GUARD] = true;

  // 1. Hook draw() to track frame times & trigger zoom/cull passes cleanly
  if (typeof proto.draw === "function") {
    const origDraw = proto.draw;
    proto.draw = function patchedDraw(...args) {
      const now = performance.now();
      state.tracker.recordTimestamp(now);
      if (state.enabled) {
        scheduleOptimizationPass();
        updateHud(now);
      }
      // Temporarily force linear links during medium/overview zoom LOD
      const savedLinkMode = this.links_render_mode;
      const savedShadows = this.render_shadows;
      if (state.enabled && state.lodEnabled && state.currentLod !== "full") {
        this.links_render_mode = 1; // LiteGraph.LINEAR_LINK
        this.render_shadows = false;
      }
      try {
        return origDraw.apply(this, args);
      } finally {
        this.links_render_mode = savedLinkMode;
        this.render_shadows = savedShadows;
      }
    };
  }

  // 2. Hook drawNode() to skip full widget painting in overview LOD for offscreen/unselected cards
  if (typeof proto.drawNode === "function") {
    const origDrawNode = proto.drawNode;
    proto.drawNode = function patchedDrawNode(node, ctx, ...rest) {
      if (state.enabled && state.lodEnabled && state.currentLod === "overview" && node && !node.is_selected) {
        const savedWidgets = node.widgets;
        node.widgets = null;
        try {
          return origDrawNode.call(this, node, ctx, ...rest);
        } finally {
          node.widgets = savedWidgets;
        }
      }
      return origDrawNode.call(this, node, ctx, ...rest);
    };
  }
}

app.registerExtension({
  name: "OmniStudio.CanvasTurbo",
  settings: [
    {
      id: "CanvasTurbo.Enabled",
      name: "Enable Canvas Turbo Anti-Lag Engine",
      type: "boolean",
      defaultValue: true,
      onChange: () => {
        syncSettings();
        scheduleOptimizationPass();
      },
    },
    {
      id: "CanvasTurbo.ZoomLOD",
      name: "Enable Zoom-Adaptive LOD (linear links & simplified widgets when zoomed out)",
      type: "boolean",
      defaultValue: true,
      onChange: () => {
        syncSettings();
        scheduleOptimizationPass();
      },
    },
    {
      id: "CanvasTurbo.VueDomCulling",
      name: "Freeze Offscreen Vue Nodes 2.0 DOM Elements",
      type: "boolean",
      defaultValue: true,
      onChange: () => {
        syncSettings();
        scheduleOptimizationPass();
      },
    },
    {
      id: "CanvasTurbo.PreviewCap",
      name: "Cap Active Preview Bitmaps (Evict Offscreen Previews)",
      type: "boolean",
      defaultValue: true,
      onChange: () => syncSettings(),
    },
    {
      id: "CanvasTurbo.MaxPreviews",
      name: "Maximum Live Preview Bitmaps in Memory",
      type: "number",
      defaultValue: DEFAULT_CONFIG.maxPreviewBitmaps,
      attrs: { min: 1, max: 24, step: 1 },
      onChange: () => syncSettings(),
    },
    {
      id: "CanvasTurbo.ShowHUD",
      name: "Show Live FPS / Anti-Lag HUD Overlay",
      type: "boolean",
      defaultValue: true,
      onChange: () => syncSettings(),
    },
  ],

  setup() {
    mountHud();
    const attachWhenReady = (attempts = 0) => {
      if (app?.canvas) {
        patchCanvasNonDestructively(app.canvas);
        return;
      }
      if (attempts < 40) {
        requestAnimationFrame(() => attachWhenReady(attempts + 1));
      }
    };
    attachWhenReady();
    api.addEventListener("executing", (event) => {
      const nid = event?.detail;
      state.executingNodeId = nid == null ? null : Number(nid);
      state.isGenerating = nid != null;
      scheduleOptimizationPass();
    });
    api.addEventListener("executed", () => {
      scheduleOptimizationPass();
    });
  },
});
