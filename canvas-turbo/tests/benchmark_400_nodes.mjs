#!/usr/bin/env node
/**
 * Quantitative stress benchmark comparing a flat 400-node mega-workflow against
 * OmniStudio 1-level Subgraphs + Canvas-Turbo Viewport Culling & Zoom LOD.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";

import {
  DEFAULT_CONFIG,
  auditWorkflowGraph,
  computeVisibleSet,
  computeWorldViewport,
  selectLodTier,
} from "../web/canvas_turbo_core.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKBENCH_JSON = path.resolve(__dirname, "../../workbench/dist/omni_ubisoft_workbench.ui.json");

function makeFlat400NodeGraph() {
  const nodes = [];
  for (let i = 0; i < 400; i++) {
    const col = i % 20;
    const row = Math.floor(i / 20);
    nodes.push({
      id: i + 1,
      type: i === 0 ? "Anything Everywhere" : i % 35 === 0 ? "PreviewImage" : "KSampler",
      pos: [col * 340, row * 220],
      size: [280, 150],
      mode: 0,
      flags: {},
    });
  }
  return { nodes, links: [], definitions: { subgraphs: [] } };
}

const flat400 = makeFlat400NodeGraph();
const omni = JSON.parse(fs.readFileSync(WORKBENCH_JSON, "utf-8"));

const viewportZoomedIn = computeWorldViewport({ scale: 0.85, offset: [-400, -100] }, 1920, 1080, 180);
const viewportZoomedOut = computeWorldViewport({ scale: 0.24, offset: [0, 0] }, 1920, 1080, 180);

// Measure 1,000 pan/cull frames on both graphs
const ITERS = 1000;
const t0 = performance.now();
let flatVisible = 0;
for (let i = 0; i < ITERS; i++) {
  flatVisible = computeVisibleSet(flat400.nodes, viewportZoomedIn).visibleCount;
}
const flatCullMs = (performance.now() - t0) / ITERS;

const t1 = performance.now();
let omniVisible = 0;
for (let i = 0; i < ITERS; i++) {
  omniVisible = computeVisibleSet(omni.nodes, viewportZoomedIn).visibleCount;
}
const omniCullMs = (performance.now() - t1) / ITERS;

const report = {
  flat_400_unoptimized: {
    total_nodes: flat400.nodes.length,
    root_dom_without_turbo: flat400.nodes.length,
    live_dom_with_turbo_cull_zoomed_in: flatVisible,
    cull_pass_ms_per_frame: Number(flatCullMs.toFixed(4)),
    zoomed_out_lod: selectLodTier(viewportZoomedOut.scale, "full", DEFAULT_CONFIG),
    audit_score: auditWorkflowGraph(flat400).score,
  },
  omnistudio_342_with_subgraphs_and_turbo: {
    total_real_nodes: auditWorkflowGraph(omni).metrics.totalRealNodes,
    root_dom_without_turbo: omni.nodes.length,
    live_dom_with_turbo_cull_zoomed_in: omniVisible,
    total_dom_reduction_vs_flat_pct: Number(((1 - omniVisible / flat400.nodes.length) * 100).toFixed(1)),
    cull_pass_ms_per_frame: Number(omniCullMs.toFixed(4)),
    zoomed_out_lod: selectLodTier(viewportZoomedOut.scale, "full", DEFAULT_CONFIG),
    audit_score: auditWorkflowGraph(omni).score,
  },
};

console.log(JSON.stringify(report, null, 2));
