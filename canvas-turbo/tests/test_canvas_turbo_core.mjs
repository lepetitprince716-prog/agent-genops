import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_CONFIG,
  FrameMetricsTracker,
  auditWorkflowGraph,
  computeVisibleSet,
  computeWorldViewport,
  planPreviewEviction,
  selectLodTier,
} from "../web/canvas_turbo_core.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKBENCH_JSON = path.resolve(__dirname, "../../workbench/dist/omni_ubisoft_workbench.ui.json");

test("computeWorldViewport and computeVisibleSet cull offscreen nodes accurately", () => {
  const viewport = computeWorldViewport({ scale: 1.0, offset: [0, 0] }, 1000, 800, 100);
  const nodes = [
    { id: 1, pos: [100, 100], size: [200, 120], flags: {} }, // visible
    { id: 2, pos: [2400, 100], size: [200, 120], flags: {} }, // offscreen
    { id: 3, pos: [2400, 100], size: [200, 120], flags: { pinned: true } }, // pinned -> keep live
    { id: 4, pos: [2600, 2600], size: [200, 120], flags: {} }, // selected -> keep live
    { id: 5, pos: [3000, 3000], size: [200, 120], flags: {} }, // executing -> keep live
  ];
  const res = computeVisibleSet(nodes, viewport, { selectedIds: new Set([4]), executingId: 5 });
  assert.equal(res.visibleCount, 4);
  assert.equal(res.offscreenCount, 1);
  assert.ok(res.offscreenIds.has(2));
  assert.ok(res.visibleIds.has(1));
  assert.ok(res.visibleIds.has(3));
  assert.ok(res.visibleIds.has(4));
  assert.ok(res.visibleIds.has(5));
});

test("selectLodTier enforces hysteresis across zoom boundaries", () => {
  // Starting in full: crosses down below 0.55 -> medium, below 0.28 -> overview
  assert.equal(selectLodTier(0.8, "full", DEFAULT_CONFIG), "full");
  assert.equal(selectLodTier(0.5, "full", DEFAULT_CONFIG), "medium");
  assert.equal(selectLodTier(0.2, "full", DEFAULT_CONFIG), "overview");

  // Starting in medium: requires scale >= 0.59 (0.55 + 0.04) to jump back to full
  assert.equal(selectLodTier(0.56, "medium", DEFAULT_CONFIG), "medium");
  assert.equal(selectLodTier(0.6, "medium", DEFAULT_CONFIG), "full");
  // Requires < 0.24 (0.28 - 0.04) to drop to overview
  assert.equal(selectLodTier(0.26, "medium", DEFAULT_CONFIG), "medium");
  assert.equal(selectLodTier(0.23, "medium", DEFAULT_CONFIG), "overview");

  // Starting in overview: requires >= 0.32 (0.28 + 0.04) to climb to medium
  assert.equal(selectLodTier(0.3, "overview", DEFAULT_CONFIG), "overview");
  assert.equal(selectLodTier(0.33, "overview", DEFAULT_CONFIG), "medium");
});

test("planPreviewEviction keeps executing, pinned & visible newest previews and evicts offscreen stale ones", () => {
  const entries = [
    { nodeId: 10, visible: false, pinned: false, executing: false, lastSeenTick: 1, width: 2048, height: 2048, count: 1 },
    { nodeId: 11, visible: false, pinned: false, executing: false, lastSeenTick: 5, width: 1024, height: 1024, count: 1 },
    { nodeId: 12, visible: true, pinned: false, executing: false, lastSeenTick: 10, width: 1024, height: 1024, count: 1 },
    { nodeId: 13, visible: false, pinned: true, executing: false, lastSeenTick: 2, width: 1024, height: 1024, count: 1 },
    { nodeId: 14, visible: false, pinned: false, executing: true, lastSeenTick: 3, width: 1024, height: 1024, count: 1 },
  ];
  const plan = planPreviewEviction(entries, { maxPreviewBitmaps: 3, maxPreviewMegapixels: 16 });
  assert.deepEqual(plan.keepIds, [14, 13, 12]);
  assert.deepEqual(plan.evictIds, [11, 10]);
});

test("auditWorkflowGraph flags UE nodes, nested subgraphs, and root DOM bloat, while scoring OmniStudio >= 95", () => {
  const badGraph = {
    nodes: [
      ...Array.from({ length: 120 }, (_, i) => ({
        id: i + 1,
        type: i === 0 ? "Anything Everywhere" : i < 5 ? "PreviewImage" : "KSampler",
        mode: 0,
      })),
    ],
    links: [],
    definitions: {
      subgraphs: [
        { id: "sg-inner", name: "Inner", nodes: [{ id: 1, type: "KSampler", mode: 0 }], links: [] },
        { id: "sg-outer", name: "Outer", nodes: [{ id: 1, type: "sg-inner", mode: 0 }], links: [] },
      ],
    },
  };
  const badReport = auditWorkflowGraph(badGraph);
  assert.ok(badReport.score < 50, `Expected low score for bad graph, got ${badReport.score}`);
  const codes = new Set(badReport.findings.map((f) => f.code));
  assert.ok(codes.has("LAG_UE_BROADCAST"));
  assert.ok(codes.has("LAG_NESTED_SUBGRAPH"));
  assert.ok(codes.has("LAG_ROOT_DOM_BLOAT"));
  assert.ok(codes.has("LAG_PREVIEW_BLOAT"));

  // Cross-check against Phase 1 OmniStudio Ubisoft Workbench!
  if (fs.existsSync(WORKBENCH_JSON)) {
    const omni = JSON.parse(fs.readFileSync(WORKBENCH_JSON, "utf-8"));
    const omniReport = auditWorkflowGraph(omni);
    assert.equal(omniReport.score, 100, `Expected OmniStudio score 100, findings: ${JSON.stringify(omniReport.findings)}`);
    assert.equal(omniReport.grade, "S");
    assert.equal(omniReport.metrics.ueCount, 0);
    assert.equal(omniReport.metrics.nestedSubgraphs, 0);
  }
});

test("FrameMetricsTracker computes FPS, p95, and ignores background tab pause jumps", () => {
  const tracker = new FrameMetricsTracker(10, 33.33);
  let t = 1000;
  tracker.recordTimestamp(t);
  for (let i = 0; i < 8; i++) {
    t += 16.67;
    tracker.recordTimestamp(t);
  }
  t += 50.0; // 1 jank frame
  tracker.recordTimestamp(t);
  t += 12000; // tab hidden for 12s -> ignored
  tracker.recordTimestamp(t);

  const snap = tracker.snapshot();
  assert.equal(snap.sampleCount, 9);
  assert.equal(snap.jankFrames, 1);
  assert.ok(snap.fps > 45 && snap.fps < 60);
  assert.equal(snap.p95Ms, 50);
});

test("computeVisibleSet matches string node IDs against numeric selected/executing IDs", () => {
  const vp = computeWorldViewport({ scale: 1.0, offset: [0, 0] }, 1000, 800, 0);
  const nodes = [
    { id: "10", pos: [5000, 5000], size: [200, 100], flags: {} },
    { id: "11", pos: [5000, 5000], size: [200, 100], flags: {} },
    { id: "12", pos: [5000, 5000], size: [200, 100], flags: {} },
  ];
  const vis = computeVisibleSet(nodes, vp, { selectedIds: new Set(["10"]), executingId: 11 });
  assert.ok(vis.visibleIds.has("10"));
  assert.ok(vis.visibleIds.has("11"));
  assert.ok(vis.offscreenIds.has("12"));
});
