/**
 * Pure, framework-agnostic core algorithms for ComfyUI-Canvas-Turbo.
 *
 * Kept strictly free of browser globals (`window`, `document`, `app`) so every
 * spatial culling, zoom-LOD hysteresis, preview-eviction, frame-metrics, and
 * workflow-auditing rule can be unit-tested and benchmarked directly in Node.js.
 */

export const DEFAULT_CONFIG = Object.freeze({
  lodMediumScale: 0.55,
  lodOverviewScale: 0.28,
  lodHysteresis: 0.04,
  viewportMarginPx: 180,
  maxPreviewBitmaps: 4,
  maxPreviewMegapixels: 16,
  jankThresholdMs: 33.33,
  metricsWindowSize: 60,
});

export const BANNED_UE_TYPES = new Set([
  "Anything Everywhere",
  "Anything Everywhere?",
  "Anything Everywhere3",
  "Seed Everywhere",
  "Prompts Everywhere",
]);

export const PREVIEW_NODE_TYPES = new Set([
  "PreviewImage",
  "Image Comparer (rgthree)",
  "PreviewAny",
  "HDRPreviewKJ",
]);

export const HEAVY_LOADER_TYPES = new Set([
  "CheckpointLoaderSimple",
  "UNETLoader",
  "UnetLoaderGGUF",
  "DiffusionModelLoaderKJ",
  "CheckpointLoaderKJ",
]);

/**
 * Compute world-space visible rectangle from LiteGraph DragAndScale state.
 * In LiteGraph: screenX = (worldX + offset[0]) * scale  =>  worldX = screenX / scale - offset[0].
 */
export function computeWorldViewport(ds, canvasWidth, canvasHeight, marginScreenPx = 180) {
  const rawScale = Number(ds?.scale);
  const scale = Number.isFinite(rawScale) && rawScale > 0.01 ? rawScale : 1.0;
  const offX = Number(ds?.offset?.[0] ?? 0);
  const offY = Number(ds?.offset?.[1] ?? 0);
  const width = Math.max(1, Number(canvasWidth || 1280));
  const height = Math.max(1, Number(canvasHeight || 720));
  const marginWorld = Math.max(0, Number(marginScreenPx || 0)) / scale;

  const minX = -offX - marginWorld;
  const minY = -offY - marginWorld;
  const maxX = width / scale - offX + marginWorld;
  const maxY = height / scale - offY + marginWorld;
  return { minX, minY, maxX, maxY, scale };
}

/**
 * Axis-aligned bounding box intersection test for a node (including 30px title bar).
 */
export function isNodeInViewport(node, viewport, titleHeight = 30) {
  const pos = node?.pos;
  const size = node?.size;
  if (!pos || !size) return true;
  const nx = Number(pos[0] ?? 0);
  const ny = Number(pos[1] ?? 0) - titleHeight;
  const nw = Math.max(1, Number(size[0] ?? 200));
  const collapsed = Boolean(node?.flags?.collapsed);
  const nh = collapsed ? titleHeight : Math.max(1, Number(size[1] ?? 100)) + titleHeight;
  return (
    nx <= viewport.maxX &&
    nx + nw >= viewport.minX &&
    ny <= viewport.maxY &&
    ny + nh >= viewport.minY
  );
}

/**
 * Partition graph nodes into visible vs offscreen sets.
 * Always keeps selected, pinned, or actively executing nodes visible to prevent UX surprises.
 */
export function computeVisibleSet(nodes, viewport, options = {}) {
  const selectedIds = options.selectedIds instanceof Set ? options.selectedIds : new Set();
  const executingId = options.executingId ?? null;
  const visibleIds = new Set();
  const offscreenIds = new Set();

  for (const node of nodes || []) {
    if (!node || node.id === undefined || node.id === null) continue;
    const pinned = Boolean(node.flags?.pinned);
    const isExec = executingId !== null && executingId !== undefined && String(node.id) === String(executingId);
    const isSel = selectedIds.has(node.id) || selectedIds.has(String(node.id));
    const keepLive = pinned || isSel || isExec;
    if (keepLive || isNodeInViewport(node, viewport)) {
      visibleIds.add(node.id);
    } else {
      offscreenIds.add(node.id);
    }
  }
  return {
    visibleIds,
    offscreenIds,
    visibleCount: visibleIds.size,
    offscreenCount: offscreenIds.size,
    totalCount: visibleIds.size + offscreenIds.size,
  };
}

/**
 * Zoom-adaptive LOD tier selector with hysteresis so zooming right across a boundary
 * never causes 60 Hz mode thrashing.
 *
 * Tiers:
 * - "full"     : full widgets, splines, live previews
 * - "medium"   : straight/linear links, simplified widget chrome, no drop shadows
 * - "overview" : solid color cards + titles only; hides heavy DOM inputs & minor wires
 */
export function selectLodTier(scale, previousTier = "full", config = DEFAULT_CONFIG) {
  const s = Number.isFinite(Number(scale)) ? Number(scale) : 1.0;
  const med = Number(config.lodMediumScale ?? DEFAULT_CONFIG.lodMediumScale);
  const ov = Number(config.lodOverviewScale ?? DEFAULT_CONFIG.lodOverviewScale);
  const h = Math.max(0, Number(config.lodHysteresis ?? DEFAULT_CONFIG.lodHysteresis));

  if (previousTier === "overview") {
    if (s >= med + h) return "full";
    if (s >= ov + h) return "medium";
    return "overview";
  }
  if (previousTier === "medium") {
    if (s >= med + h) return "full";
    if (s < ov - h) return "overview";
    return "medium";
  }
  // previousTier === "full" (or unknown)
  if (s < ov) return "overview";
  if (s < med) return "medium";
  return "full";
}

/**
 * Decide which decoded preview image arrays (`node.imgs`) should be evicted to keep
 * browser GPU texture memory within budget.
 *
 * Eviction priority (evict first):
 * 1. Offscreen nodes over visible nodes.
 * 2. Older lastSeenTick (LRU) over recently viewed nodes.
 * 3. Larger pixel area when tied.
 * Never evicts the currently executing or explicitly pinned node unless budget is 0.
 */
export function planPreviewEviction(previewEntries, config = DEFAULT_CONFIG) {
  const maxBitmaps = Math.max(0, Number(config.maxPreviewBitmaps ?? DEFAULT_CONFIG.maxPreviewBitmaps));
  const maxPixels = Math.max(0, Number(config.maxPreviewMegapixels ?? DEFAULT_CONFIG.maxPreviewMegapixels)) * 1_000_000;

  const items = (previewEntries || []).map((e) => ({
    nodeId: e.nodeId,
    visible: Boolean(e.visible),
    pinned: Boolean(e.pinned),
    executing: Boolean(e.executing),
    lastSeenTick: Number(e.lastSeenTick ?? 0),
    pixels: Math.max(0, Number(e.width ?? 0) * Number(e.height ?? 0) * Math.max(1, Number(e.count ?? 1))),
    count: Math.max(1, Number(e.count ?? 1)),
  }));

  // Sort by keep priority descending: executing/pinned -> visible -> newest tick -> smallest pixels
  items.sort((a, b) => {
    const aProt = a.executing || a.pinned;
    const bProt = b.executing || b.pinned;
    if (aProt !== bProt) return aProt ? -1 : 1;
    if (a.visible !== b.visible) return a.visible ? -1 : 1;
    if (a.lastSeenTick !== b.lastSeenTick) return b.lastSeenTick - a.lastSeenTick;
    return a.pixels - b.pixels;
  });

  const keepIds = [];
  const evictIds = [];
  let keptBitmaps = 0;
  let keptPixels = 0;

  for (const item of items) {
    const fitsCount = keptBitmaps + item.count <= maxBitmaps;
    const fitsPixels = maxPixels === 0 ? false : keptPixels + item.pixels <= maxPixels;
    if (fitsCount && fitsPixels) {
      keepIds.push(item.nodeId);
      keptBitmaps += item.count;
      keptPixels += item.pixels;
    } else if ((item.executing || item.pinned) && maxBitmaps > 0 && keptBitmaps === 0) {
      keepIds.push(item.nodeId);
      keptBitmaps += item.count;
      keptPixels += item.pixels;
    } else {
      evictIds.push(item.nodeId);
    }
  }

  return {
    keepIds,
    evictIds,
    keptBitmaps,
    keptMegapixels: Number((keptPixels / 1_000_000).toFixed(2)),
  };
}

/**
 * Audit a ComfyUI v0.4 workflow (or live LGraph-like serialized object) for known
 * large-graph lag anti-patterns and produce a 0-100 health score + concrete issues.
 */
export function auditWorkflowGraph(doc) {
  const nodes = Array.isArray(doc?.nodes) ? doc.nodes : [];
  const links = Array.isArray(doc?.links) ? doc.links : [];
  const subgraphs = Array.isArray(doc?.definitions?.subgraphs) ? doc.definitions.subgraphs : [];
  const sgById = new Map(subgraphs.filter((s) => s && s.id).map((s) => [s.id, s]));

  const findings = [];
  let ueCount = 0;
  let rootPreviews = 0;
  let nestedSubgraphs = 0;
  let activeRootLoaders = 0;
  let internalNodeCount = 0;
  let internalLinkCount = 0;

  for (const n of nodes) {
    if (!n) continue;
    const mode = Number(n.mode ?? 0);
    if (BANNED_UE_TYPES.has(n.type)) {
      ueCount += 1;
      findings.push({
        code: "LAG_UE_BROADCAST",
        severity: "critical",
        nodeId: n.id,
        message: `Use Everywhere node '${n.type}' (#${n.id}) causes O(N^2) background broadcast evaluation on large graphs.`,
      });
    }
    if (PREVIEW_NODE_TYPES.has(n.type) && mode === 0) {
      rootPreviews += 1;
    }
    if (HEAVY_LOADER_TYPES.has(n.type) && mode === 0) {
      activeRootLoaders += 1;
    }
  }

  // Check subgraph depth and internal anti-patterns
  for (const sg of subgraphs) {
    const inodes = Array.isArray(sg.nodes) ? sg.nodes : [];
    const ilinks = Array.isArray(sg.links) ? sg.links : [];
    internalNodeCount += inodes.length;
    internalLinkCount += ilinks.length;
    for (const inode of inodes) {
      if (!inode) continue;
      if (sgById.has(inode.type)) {
        nestedSubgraphs += 1;
        findings.push({
          code: "LAG_NESTED_SUBGRAPH",
          severity: "high",
          nodeId: inode.id,
          subgraphId: sg.id,
          message: `Nested subgraph inside '${sg.name || sg.id}' triggers ComfyUI double-configuration cold-load lag.`,
        });
      }
      if (BANNED_UE_TYPES.has(inode.type)) {
        ueCount += 1;
        findings.push({
          code: "LAG_UE_BROADCAST",
          severity: "critical",
          nodeId: inode.id,
          subgraphId: sg.id,
          message: `Use Everywhere node '${inode.type}' inside subgraph '${sg.name || sg.id}' degrades canvas responsiveness.`,
        });
      }
    }
  }

  // Count active unmuted engine subgraphs that contain heavy loaders
  let activeEngineSubgraphs = 0;
  for (const n of nodes) {
    if (!n || Number(n.mode ?? 0) !== 0) continue;
    const sg = sgById.get(n.type);
    if (!sg) continue;
    const hasActiveLoader = (sg.nodes || []).some(
      (inode) => Number(inode?.mode ?? 0) === 0 && HEAVY_LOADER_TYPES.has(inode?.type),
    );
    if (hasActiveLoader) activeEngineSubgraphs += 1;
  }

  if (nodes.length > 80) {
    findings.push({
      code: "LAG_ROOT_DOM_BLOAT",
      severity: nodes.length > 160 ? "critical" : "high",
      message: `${nodes.length} nodes sit directly on the root canvas (>80 threshold). Pack feature islands into 1-level flat Subgraphs.`,
    });
  }
  if (rootPreviews > 2) {
    findings.push({
      code: "LAG_PREVIEW_BLOAT",
      severity: "medium",
      message: `${rootPreviews} active preview nodes on root canvas inflate browser WebGL/Canvas texture memory. Consolidate into 1 Image Comparer.`,
    });
  }
  if (activeRootLoaders + activeEngineSubgraphs > 2) {
    findings.push({
      code: "LAG_VRAM_CONTENTION",
      severity: "medium",
      message: `${activeRootLoaders + activeEngineSubgraphs} heavy model loaders are simultaneously unmuted; mute inactive model branches to avoid OOM thrashing.`,
    });
  }

  // Deterministic 0-100 health score
  let score = 100;
  score -= Math.min(40, ueCount * 20);
  score -= Math.min(25, nestedSubgraphs * 15);
  if (nodes.length > 80) score -= Math.min(25, Math.ceil((nodes.length - 80) / 10) * 3);
  if (rootPreviews > 2) score -= Math.min(15, (rootPreviews - 2) * 5);
  if (activeRootLoaders + activeEngineSubgraphs > 2) {
    score -= Math.min(15, (activeRootLoaders + activeEngineSubgraphs - 2) * 5);
  }
  score = Math.max(0, Math.min(100, score));

  const totalRealNodes = nodes.length + internalNodeCount;
  const domReductionPct =
    totalRealNodes > 0 ? Number(((1 - nodes.length / totalRealNodes) * 100).toFixed(1)) : 0;

  return {
    score,
    grade: score >= 90 ? "S" : score >= 75 ? "A" : score >= 55 ? "B" : "C",
    metrics: {
      rootNodes: nodes.length,
      internalNodes: internalNodeCount,
      totalRealNodes,
      rootLinks: links.length,
      totalRealLinks: links.length + internalLinkCount,
      subgraphCount: subgraphs.length,
      nestedSubgraphs,
      ueCount,
      rootPreviews,
      activeHeavyLoaders: activeRootLoaders + activeEngineSubgraphs,
      domReductionPct,
    },
    findings,
  };
}

/**
 * Rolling ring buffer tracking frame times, FPS, p95 frame time, and jank counts.
 */
export class FrameMetricsTracker {
  constructor(windowSize = DEFAULT_CONFIG.metricsWindowSize, jankThresholdMs = DEFAULT_CONFIG.jankThresholdMs) {
    this.windowSize = Math.max(4, Number(windowSize));
    this.jankThresholdMs = Number(jankThresholdMs);
    this.samples = [];
    this.lastTimestamp = null;
  }

  recordTimestamp(nowMs) {
    const t = Number(nowMs);
    if (!Number.isFinite(t)) return null;
    if (this.lastTimestamp === null) {
      this.lastTimestamp = t;
      return null;
    }
    const dt = t - this.lastTimestamp;
    this.lastTimestamp = t;
    if (dt <= 0 || dt > 5000) return null; // Ignore paused tab jumps
    this.samples.push(dt);
    if (this.samples.length > this.windowSize) {
      this.samples.shift();
    }
    return dt;
  }

  reset() {
    this.samples = [];
    this.lastTimestamp = null;
  }

  snapshot() {
    if (this.samples.length === 0) {
      return { fps: 60, avgMs: 16.67, p95Ms: 16.67, jankFrames: 0, sampleCount: 0 };
    }
    const sorted = [...this.samples].sort((a, b) => a - b);
    const sum = this.samples.reduce((acc, v) => acc + v, 0);
    const avgMs = sum / this.samples.length;
    const p95Idx = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));
    const p95Ms = sorted[p95Idx];
    const jankFrames = this.samples.filter((v) => v > this.jankThresholdMs).length;
    const fps = avgMs > 0 ? Math.min(240, 1000 / avgMs) : 60;
    return {
      fps: Number(fps.toFixed(1)),
      avgMs: Number(avgMs.toFixed(2)),
      p95Ms: Number(p95Ms.toFixed(2)),
      jankFrames,
      sampleCount: this.samples.length,
    };
  }
}
