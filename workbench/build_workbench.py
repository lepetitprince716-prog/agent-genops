#!/usr/bin/env python3
"""Deterministic builder for the OmniStudio Ubisoft All-in-One Super Workbench.

Generates a ComfyUI v0.4 UI workflow (``omni_ubisoft_workbench.ui.json``) that packs
18 self-contained multi-architecture model engines (hot + niche 2025-2026 models) and
6 full-featured pre/post-production stations (~340+ real nodes total) while keeping the
root canvas ultra-light (~48 visible items, >85% DOM reduction) through:

1. Strict 1-level flat native ComfyUI v0.4 Subgraphs (depth == 1, avoiding multi-level
   subgraph double-configure / O(N*S) traversal cold-load lag).
2. Root-level ``Fast Groups Muter (rgthree)`` in radio mode (``toggleRestriction: "max one"``)
   so inactive model engines are muted (``mode: 2``) and stripped during ``graphToPrompt``,
   preventing missing-model errors and backend serialization overhead.
3. Self-contained Engine Capsules + Pixel-Space Bridge (``IMAGE`` + ``BASIC_PIPE``), making
   cross-architecture switching (SDXL / NoobAI v-pred / Pony / SD1.5 / Anima / Flux 1-3 /
   Kontext / Chroma / MOSS / Qwen 2.1 / Krea-2 / MiniMax-H3 / SD3.5 / HiDream / Lumina-2 /
   14 niche DiTs) immune to VAE channel, CLIP type, clip-skip, and CFG mismatches.
4. Zero ``Use Everywhere`` (UE) wildcard broadcast nodes (eliminating O(N^2) canvas lag).
5. Single centralized ``Image Comparer (rgthree)`` gallery tower + toggleable VRAM auto-flush
   gate (``easy cleanGpuUsed``) between base generation and heavy detailer/upscale stages.

Standard library only; deterministic UUIDv5 IDs so repeated builds produce byte-identical JSON.
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NAMESPACE = uuid.UUID("7f3b5c1a-4b92-4e8d-9d21-00a1b2c3d4e5")

# Clean, public-safe color palette (dark tactical HUD theme)
PALETTE = {
    "cockpit": "#1e3246",
    "prompt": "#1f4e46",
    "control": "#2b3d63",
    "bank_a": "#254b6e",  # Anime & SD Classic
    "bank_b": "#4d3069",  # Flux & Flow Flagships
    "bank_c": "#1d5c48",  # Frontier Asian & Mega DiT
    "bank_d": "#6e4720",  # Experimental & Niche Vault
    "bridge": "#2f3e4e",
    "post_segs": "#692d44",
    "post_upscale": "#46386e",
    "post_darkroom": "#634824",
    "post_video": "#452957",
    "gallery": "#1c4a38",
    "vram": "#703030",
    "node_bg": "#232830",
    "node_hdr_active": "#244866",
    "node_hdr_muted": "#2d323b",
    "node_hdr_station": "#2c4a43",
    "node_hdr_bridge": "#354454",
    "node_hdr_vram": "#5e2a2a",
    "node_hdr_gallery": "#214f3d",
}

NODE_MODE_ALWAYS = 0
NODE_MODE_NEVER = 2  # Muted
NODE_MODE_BYPASS = 4  # Bypassed


def stable_uuid(tag: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"omnistudio-ubisoft-v1:{tag}"))


@dataclass
class SubgraphBuilder:
    """Builds one strict 1-level flat ComfyUI v0.4 Subgraph definition (version 1)."""

    key: str
    name: str
    inputs_spec: list[tuple[str, str, str]] = field(default_factory=list)  # (name, type, label)
    outputs_spec: list[tuple[str, str, str]] = field(default_factory=list)  # (name, type, label)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    proxy_widgets: list[list[str]] = field(default_factory=list)
    proxy_defaults: list[Any] = field(default_factory=list)
    _next_node_id: int = 1
    _next_link_id: int = 1
    _input_link_ids: dict[int, list[int]] = field(default_factory=dict)
    _output_link_ids: dict[int, list[int]] = field(default_factory=dict)

    @property
    def subgraph_id(self) -> str:
        return stable_uuid(f"sg:{self.key}")

    def add_input(self, name: str, slot_type: str, label: str | None = None) -> int:
        idx = len(self.inputs_spec)
        self.inputs_spec.append((name, slot_type, label or name))
        self._input_link_ids[idx] = []
        return idx

    def add_output(self, name: str, slot_type: str, label: str | None = None) -> int:
        idx = len(self.outputs_spec)
        self.outputs_spec.append((name, slot_type, label or name))
        self._output_link_ids[idx] = []
        return idx

    def add_node(
        self,
        class_type: str,
        *,
        title: str | None = None,
        inputs: list[tuple[str, str]] | None = None,
        outputs: list[tuple[str, str]] | None = None,
        widgets_values: list[Any] | dict[str, Any] | None = None,
        col: int = 0,
        row: int = 0,
        size: tuple[int, int] = (280, 140),
        mode: int = NODE_MODE_ALWAYS,
        properties: dict[str, Any] | None = None,
        color: str | None = None,
        bgcolor: str | None = None,
    ) -> int:
        nid = self._next_node_id
        self._next_node_id += 1
        x = 220 + col * 360
        y = 100 + row * 220
        node_inputs = [{"name": n, "type": t, "link": None} for n, t in (inputs or [])]
        node_outputs = [{"name": n, "type": t, "links": []} for n, t in (outputs or [])]
        raw: dict[str, Any] = {
            "id": nid,
            "type": class_type,
            "pos": [x, y],
            "size": [size[0], size[1]],
            "flags": {},
            "order": nid - 1,
            "mode": mode,
            "inputs": node_inputs,
            "outputs": node_outputs,
            "properties": {"Node name for S&R": class_type, **(properties or {})},
            "widgets_values": widgets_values if widgets_values is not None else [],
        }
        if title:
            raw["title"] = title
        if color:
            raw["color"] = color
        if bgcolor:
            raw["bgcolor"] = bgcolor
        self.nodes.append(raw)
        return nid

    def expose_widget(self, node_id: int, widget_name: str, default_value: Any = None) -> None:
        self.proxy_widgets.append([str(node_id), widget_name])
        if default_value is None:
            node = self._find_node(node_id)
            vals = node.get("widgets_values")
            if isinstance(vals, list) and vals:
                default_value = vals[0]
        self.proxy_defaults.append(default_value)

    def _find_node(self, nid: int) -> dict[str, Any]:
        for n in self.nodes:
            if n["id"] == nid:
                return n
        raise KeyError(f"Subgraph {self.key}: unknown node {nid}")

    def connect(
        self,
        origin_id: int,
        origin_slot: int,
        target_id: int,
        target_slot: int,
        slot_type: str,
    ) -> int:
        lid = self._next_link_id
        self._next_link_id += 1
        self.links.append(
            {
                "id": lid,
                "origin_id": origin_id,
                "origin_slot": origin_slot,
                "target_id": target_id,
                "target_slot": target_slot,
                "type": slot_type,
            }
        )
        if origin_id == -10:
            self._input_link_ids[origin_slot].append(lid)
        else:
            src = self._find_node(origin_id)
            src["outputs"][origin_slot]["links"].append(lid)

        if target_id == -20:
            self._output_link_ids[target_slot].append(lid)
        else:
            dst = self._find_node(target_id)
            dst["inputs"][target_slot]["link"] = lid
        return lid

    def build_definition(self) -> dict[str, Any]:
        max_x = max((n["pos"][0] + n["size"][0] for n in self.nodes), default=600)
        inp_h = max(80, 34 + len(self.inputs_spec) * 28)
        out_h = max(80, 34 + len(self.outputs_spec) * 28)

        inputs = []
        for idx, (iname, itype, ilabel) in enumerate(self.inputs_spec):
            inputs.append(
                {
                    "id": stable_uuid(f"sg:{self.key}:in:{idx}:{iname}"),
                    "name": iname,
                    "type": itype,
                    "linkIds": list(self._input_link_ids.get(idx, [])),
                    "label": ilabel,
                    "pos": [40, 120 + idx * 28],
                }
            )
        outputs = []
        for idx, (oname, otype, olabel) in enumerate(self.outputs_spec):
            outputs.append(
                {
                    "id": stable_uuid(f"sg:{self.key}:out:{idx}:{oname}"),
                    "name": oname,
                    "type": otype,
                    "linkIds": list(self._output_link_ids.get(idx, [])),
                    "label": olabel,
                    "pos": [max_x + 120, 120 + idx * 28],
                }
            )

        return {
            "id": self.subgraph_id,
            "version": 1,
            "name": self.name,
            "state": {
                "lastGroupId": len(self.groups),
                "lastNodeId": self._next_node_id - 1,
                "lastLinkId": self._next_link_id - 1,
                "lastRerouteId": 0,
            },
            "revision": 0,
            "config": {},
            "extra": {"omnistudio_capsule": self.key},
            "inputNode": {"id": -10, "bounding": [-60, 100, 140, inp_h]},
            "outputNode": {"id": -20, "bounding": [max_x + 100, 100, 140, out_h]},
            "inputs": inputs,
            "outputs": outputs,
            "nodes": self.nodes,
            "links": self.links,
            "groups": self.groups,
            "widgets": [],
        }


# ---------------------------------------------------------------------------
# Engine Capsule Factories (18 Self-Contained Model Architectures)
# ---------------------------------------------------------------------------


def _setup_standard_engine_io(sg: SubgraphBuilder, *, with_ref_image: bool = False) -> dict[str, int]:
    ports = {
        "pos": sg.add_input("positive_prompt", "STRING", "Positive"),
        "neg": sg.add_input("negative_prompt", "STRING", "Negative"),
        "width": sg.add_input("width", "INT", "Width"),
        "height": sg.add_input("height", "INT", "Height"),
        "seed": sg.add_input("seed", "INT", "Seed"),
    }
    if with_ref_image:
        ports["ref_image"] = sg.add_input("ref_image", "IMAGE", "Ref Image")
        ports["control_net"] = sg.add_input("control_net", "CONTROL_NET", "ControlNet")
        ports["cn_image"] = sg.add_input("cn_image", "IMAGE", "CN Map")
    ports["out_image"] = sg.add_output("IMAGE", "IMAGE", "Image")
    ports["out_pipe"] = sg.add_output("BASIC_PIPE", "BASIC_PIPE", "BasicPipe")
    return ports


def _wire_tail_decode_pipe(
    sg: SubgraphBuilder,
    *,
    model_src: tuple[int, int],
    clip_src: tuple[int, int],
    vae_src: tuple[int, int],
    pos_src: tuple[int, int],
    neg_src: tuple[int, int],
    latent_src: tuple[int, int],
    out_image_slot: int,
    out_pipe_slot: int,
    col: int,
    tiled_vae: bool = False,
) -> None:
    if tiled_vae:
        dec = sg.add_node(
            "VAEDecodeTiled",
            title="Tiled VAE Decode (Low-VRAM)",
            inputs=[("samples", "LATENT"), ("vae", "VAE")],
            outputs=[("IMAGE", "IMAGE")],
            widgets_values=[512, 64, 64, 8],
            col=col,
            row=0,
        )
    else:
        dec = sg.add_node(
            "VAEDecode",
            title="Local Arch VAE Decode",
            inputs=[("samples", "LATENT"), ("vae", "VAE")],
            outputs=[("IMAGE", "IMAGE")],
            col=col,
            row=0,
        )
    sg.connect(latent_src[0], latent_src[1], dec, 0, "LATENT")
    sg.connect(vae_src[0], vae_src[1], dec, 1, "VAE")
    sg.connect(dec, 0, -20, out_image_slot, "IMAGE")

    pipe = sg.add_node(
        "ToBasicPipe",
        title="Pack Matched BasicPipe",
        inputs=[
            ("model", "MODEL"),
            ("clip", "CLIP"),
            ("vae", "VAE"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
        ],
        outputs=[("basic_pipe", "BASIC_PIPE")],
        col=col,
        row=1,
    )
    sg.connect(model_src[0], model_src[1], pipe, 0, "MODEL")
    sg.connect(clip_src[0], clip_src[1], pipe, 1, "CLIP")
    sg.connect(vae_src[0], vae_src[1], pipe, 2, "VAE")
    sg.connect(pos_src[0], pos_src[1], pipe, 3, "CONDITIONING")
    sg.connect(neg_src[0], neg_src[1], pipe, 4, "CONDITIONING")
    sg.connect(pipe, 0, -20, out_pipe_slot, "BASIC_PIPE")


def build_engine_sdxl_illustrious() -> SubgraphBuilder:
    sg = SubgraphBuilder("e01_sdxl_illustrious", "E01 · SDXL / Illustrious / iLustMix")
    io = _setup_standard_engine_io(sg, with_ref_image=True)

    ckpt = sg.add_node(
        "CheckpointLoaderSimple",
        title="SDXL / Illustrious Checkpoint",
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")],
        widgets_values=["illustrious_xl_v2.safetensors"],
        col=0,
        row=0,
    )
    vae = sg.add_node(
        "VAELoader",
        title="SDXL FP16-Fix VAE (4-ch)",
        outputs=[("VAE", "VAE")],
        widgets_values=["sdxl_vae_fp16_fix.safetensors"],
        col=0,
        row=1,
    )
    clip_skip = sg.add_node(
        "CLIPSetLastLayer",
        title="Clip Skip -2 (SDXL Anime)",
        inputs=[("clip", "CLIP")],
        outputs=[("CLIP", "CLIP")],
        widgets_values=[-2],
        col=1,
        row=1,
    )
    lora_mgr = sg.add_node(
        "Lora Loader (LoraManager)",
        title="LoRA Manager Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("trigger_words", "STRING"), ("loaded_loras", "STRING")],
        widgets_values=[""],
        col=1,
        row=0,
    )
    power_lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Power LoRA Stack (Style/Char)",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    freeu = sg.add_node(
        "FreeU_V2",
        title="FreeU V2 (Optional)",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[1.3, 1.4, 0.9, 0.2],
        col=2,
        row=1,
        mode=NODE_MODE_BYPASS,
    )
    ipa = sg.add_node(
        "IPAdapterAdvanced",
        title="IPAdapter Style/Face (Optional)",
        inputs=[("model", "MODEL"), ("image", "IMAGE")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[0.85, "linear", "concat", 0.0, 0.55, "K+V"],
        col=3,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=2,
    )
    cn = sg.add_node(
        "ControlNetApplyAdvanced",
        title="SDXL ControlNet Union (Optional)",
        inputs=[
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("control_net", "CONTROL_NET"),
            ("image", "IMAGE"),
            ("vae", "VAE"),
        ],
        outputs=[("positive", "CONDITIONING"), ("negative", "CONDITIONING")],
        widgets_values=[0.75, 0.0, 0.85],
        col=4,
        row=1,
        mode=NODE_MODE_BYPASS,
    )
    lat = sg.add_node(
        "EmptyLatentImage",
        title="4-ch SDXL Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[832, 1216, 1],
        col=4,
        row=2,
    )
    sampler_sel = sg.add_node(
        "KSamplerSelect",
        title="Euler Ancestral",
        outputs=[("SAMPLER", "SAMPLER")],
        widgets_values=["euler_ancestral"],
        col=4,
        row=0,
    )
    dd = sg.add_node(
        "DetailDaemonSamplerNode",
        title="DetailDaemon Micro-Detail",
        inputs=[("sampler", "SAMPLER")],
        outputs=[("SAMPLER", "SAMPLER")],
        widgets_values=[0.18, 0.2, 0.8, 0.0, 0.0, 1.0, 0.0, 0.99, False],
        col=5,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    noise = sg.add_node(
        "RandomNoise",
        title="Seed Noise",
        inputs=[("noise_seed", "INT")],
        outputs=[("NOISE", "NOISE")],
        widgets_values=[42, "fixed"],
        col=5,
        row=2,
    )
    sched = sg.add_node(
        "BasicScheduler",
        title="Karras 28-Step Schedule",
        inputs=[("model", "MODEL")],
        outputs=[("SIGMAS", "SIGMAS")],
        widgets_values=["karras", 28, 1.0],
        col=5,
        row=1,
    )
    guider = sg.add_node(
        "CFGGuider",
        title="CFG 6.0 Guider",
        inputs=[("model", "MODEL"), ("positive", "CONDITIONING"), ("negative", "CONDITIONING")],
        outputs=[("GUIDER", "GUIDER")],
        widgets_values=[6.0],
        col=6,
        row=1,
    )
    samp = sg.add_node(
        "SamplerCustomAdvanced",
        title="SDXL Advanced Sampler",
        inputs=[
            ("noise", "NOISE"),
            ("guider", "GUIDER"),
            ("sampler", "SAMPLER"),
            ("sigmas", "SIGMAS"),
            ("latent_image", "LATENT"),
        ],
        outputs=[("output", "LATENT"), ("denoised_output", "LATENT")],
        col=6,
        row=0,
    )

    sg.connect(ckpt, 1, clip_skip, 0, "CLIP")
    sg.connect(ckpt, 0, lora_mgr, 0, "MODEL")
    sg.connect(clip_skip, 0, lora_mgr, 1, "CLIP")
    sg.connect(lora_mgr, 0, power_lora, 0, "MODEL")
    sg.connect(lora_mgr, 1, power_lora, 1, "CLIP")
    sg.connect(power_lora, 0, freeu, 0, "MODEL")
    sg.connect(freeu, 0, ipa, 0, "MODEL")
    sg.connect(-10, io["ref_image"], ipa, 1, "IMAGE")
    sg.connect(power_lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(power_lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(enc_pos, 0, cn, 0, "CONDITIONING")
    sg.connect(enc_neg, 0, cn, 1, "CONDITIONING")
    sg.connect(-10, io["control_net"], cn, 2, "CONTROL_NET")
    sg.connect(-10, io["cn_image"], cn, 3, "IMAGE")
    sg.connect(vae, 0, cn, 4, "VAE")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(sampler_sel, 0, dd, 0, "SAMPLER")
    sg.connect(-10, io["seed"], noise, 0, "INT")
    sg.connect(ipa, 0, sched, 0, "MODEL")
    sg.connect(ipa, 0, guider, 0, "MODEL")
    sg.connect(cn, 0, guider, 1, "CONDITIONING")
    sg.connect(cn, 1, guider, 2, "CONDITIONING")
    sg.connect(noise, 0, samp, 0, "NOISE")
    sg.connect(guider, 0, samp, 1, "GUIDER")
    sg.connect(dd, 0, samp, 2, "SAMPLER")
    sg.connect(sched, 0, samp, 3, "SIGMAS")
    sg.connect(lat, 0, samp, 4, "LATENT")

    _wire_tail_decode_pipe(
        sg,
        model_src=(ipa, 0),
        clip_src=(power_lora, 1),
        vae_src=(vae, 0),
        pos_src=(cn, 0),
        neg_src=(cn, 1),
        latent_src=(samp, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=7,
    )
    sg.expose_widget(ckpt, "ckpt_name")
    sg.expose_widget(sched, "steps")
    sg.expose_widget(guider, "cfg")
    return sg


def build_engine_noobai_vpred() -> SubgraphBuilder:
    sg = SubgraphBuilder("e02_noobai_vpred", "E02 · NoobAI / Illustrious V-Pred")
    io = _setup_standard_engine_io(sg)

    ckpt = sg.add_node(
        "CheckpointLoaderSimple",
        title="NoobAI V-Pred Checkpoint",
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")],
        widgets_values=["noobai_xl_vpred_1.1.safetensors"],
        col=0,
        row=0,
    )
    vae = sg.add_node(
        "VAELoader",
        title="SDXL FP16-Fix VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["sdxl_vae_fp16_fix.safetensors"],
        col=0,
        row=1,
    )
    vpred = sg.add_node(
        "ModelSamplingDiscrete",
        title="V-Prediction + ZSNR Lock",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=["v_prediction", True],
        col=1,
        row=0,
    )
    rescale = sg.add_node(
        "RescaleCFG",
        title="RescaleCFG 0.7 (Anti-Burn)",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[0.7],
        col=2,
        row=0,
    )
    clip_skip = sg.add_node(
        "CLIPSetLastLayer",
        title="Clip Skip -2",
        inputs=[("clip", "CLIP")],
        outputs=[("CLIP", "CLIP")],
        widgets_values=[-2],
        col=1,
        row=1,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="NoobAI LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=3,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=1,
    )
    lat = sg.add_node(
        "EmptyLatentImage",
        title="4-ch V-Pred Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[832, 1216, 1],
        col=4,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="V-Pred KSampler (CFG 4.5)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 28, 4.5, "euler", "simple", 1.0],
        col=5,
        row=0,
    )
    sg.connect(ckpt, 0, vpred, 0, "MODEL")
    sg.connect(vpred, 0, rescale, 0, "MODEL")
    sg.connect(ckpt, 1, clip_skip, 0, "CLIP")
    sg.connect(rescale, 0, lora, 0, "MODEL")
    sg.connect(clip_skip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=6,
    )
    sg.expose_widget(ckpt, "ckpt_name")
    sg.expose_widget(ks, "steps")
    sg.expose_widget(ks, "cfg")
    return sg


def build_engine_pony_v6() -> SubgraphBuilder:
    sg = SubgraphBuilder("e03_pony_v6", "E03 · Pony V6 XL (Auto Score Prefix)")
    io = _setup_standard_engine_io(sg)

    ckpt = sg.add_node(
        "CheckpointLoaderSimple",
        title="Pony V6 XL Checkpoint",
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")],
        widgets_values=["pony_diffusion_v6_xl.safetensors"],
        col=0,
        row=0,
    )
    vae = sg.add_node(
        "VAELoader",
        title="SDXL FP16-Fix VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["sdxl_vae_fp16_fix.safetensors"],
        col=0,
        row=1,
    )
    clip_skip = sg.add_node(
        "CLIPSetLastLayer",
        title="Clip Skip -2",
        inputs=[("clip", "CLIP")],
        outputs=[("CLIP", "CLIP")],
        widgets_values=[-2],
        col=1,
        row=1,
    )
    prefix = sg.add_node(
        "easy promptConcat",
        title="Pony Score-Tag Prefix Injector",
        inputs=[("prompt2", "STRING")],
        outputs=[("prompt", "STRING")],
        widgets_values=["score_9, score_8_up, score_7_up, source_anime", ", "],
        col=1,
        row=2,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Pony LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    lat = sg.add_node(
        "EmptyLatentImage",
        title="Pony 1024 Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Pony KSampler (CFG 7.0)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 28, 7.0, "euler_ancestral", "karras", 1.0],
        col=4,
        row=0,
    )
    sg.connect(ckpt, 1, clip_skip, 0, "CLIP")
    sg.connect(ckpt, 0, lora, 0, "MODEL")
    sg.connect(clip_skip, 0, lora, 1, "CLIP")
    sg.connect(-10, io["pos"], prefix, 0, "STRING")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(prefix, 0, enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(ckpt, "ckpt_name")
    sg.expose_widget(ks, "steps")
    sg.expose_widget(ks, "cfg")
    return sg


def build_engine_anima_dit() -> SubgraphBuilder:
    sg = SubgraphBuilder("e04_anima_dit", "E04 · Anima 2.9B / 3.8B (Cosmos DiT)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="Anima DiT Weights",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["anima_29b_base.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Qwen3-0.6B (stable_diffusion)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["qwen_3_06b_base.safetensors", "stable_diffusion", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Qwen 16-ch VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["qwen_image_vae.safetensors"],
        col=0,
        row=2,
    )
    aura = sg.add_node(
        "ModelSamplingAuraFlow",
        title="AuraFlow Shift 1.73",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[1.73],
        col=1,
        row=0,
    )
    turbo = sg.add_node(
        "LoraLoaderModelOnly",
        title="Anima Turbo LoRA (Bypass=Base)",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=["anima_turbo_8step.safetensors", 1.0],
        col=2,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Anima Style/Char LoRAs",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=3,
        row=0,
    )
    teacache = sg.add_node(
        "TeaCache",
        title="TeaCache Accel (Optional)",
        inputs=[("model", "MODEL")],
        outputs=[("model", "MODEL")],
        widgets_values=["flux", 0.25, 0.15, 0.9, 1, "main_device"],
        col=3,
        row=1,
        mode=NODE_MODE_BYPASS,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=1,
    )
    lat = sg.add_node(
        "EmptyLatentImage",
        title="Anima Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[896, 1152, 1],
        col=4,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Anima KSampler (er_sde/simple)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 32, 4.5, "er_sde", "simple", 1.0],
        col=5,
        row=0,
    )
    sg.connect(unet, 0, aura, 0, "MODEL")
    sg.connect(aura, 0, turbo, 0, "MODEL")
    sg.connect(turbo, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 0, teacache, 0, "MODEL")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(teacache, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(teacache, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=6,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(aura, "shift")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_sd15_lcm() -> SubgraphBuilder:
    sg = SubgraphBuilder("e05_sd15_lcm", "E05 · SD 1.5 Classic / LCM Turbo")
    io = _setup_standard_engine_io(sg)

    ckpt = sg.add_node(
        "CheckpointLoaderSimple",
        title="SD 1.5 Checkpoint",
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")],
        widgets_values=["sd15_anime_classic.safetensors"],
        col=0,
        row=0,
    )
    vae = sg.add_node(
        "VAELoader",
        title="kl-f8-anime2 VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["vae-ft-mse-840000-ema-pruned.safetensors"],
        col=0,
        row=1,
    )
    lcm = sg.add_node(
        "ModelSamplingDiscrete",
        title="LCM Mode (Optional Bypass)",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=["lcm", False],
        col=1,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    clip_skip = sg.add_node(
        "CLIPSetLastLayer",
        title="Clip Skip -2",
        inputs=[("clip", "CLIP")],
        outputs=[("CLIP", "CLIP")],
        widgets_values=[-2],
        col=1,
        row=1,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="SD 1.5 LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    lat = sg.add_node(
        "EmptyLatentImage",
        title="SD 1.5 Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[512, 768, 1],
        col=3,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="SD 1.5 KSampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 24, 7.0, "dpmpp_2m", "karras", 1.0],
        col=4,
        row=0,
    )
    sg.connect(ckpt, 0, lcm, 0, "MODEL")
    sg.connect(ckpt, 1, clip_skip, 0, "CLIP")
    sg.connect(lcm, 0, lora, 0, "MODEL")
    sg.connect(clip_skip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(ckpt, "ckpt_name")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_flux1_dev() -> SubgraphBuilder:
    sg = SubgraphBuilder("e06_flux1_dev", "E06 · Flux.1 Dev / Schnell (GGUF + TeaCache)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UnetLoaderGGUF",
        title="Flux.1 GGUF/FP8 UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["flux1-dev-Q6_K.gguf"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "DualCLIPLoader",
        title="DualCLIP (CLIP-L + T5-XXL)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors", "flux", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Flux 16-ch AE VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["ae.safetensors"],
        col=0,
        row=2,
    )
    ms_flux = sg.add_node(
        "ModelSamplingFlux",
        title="Flux Resolution Shift",
        inputs=[("model", "MODEL"), ("width", "INT"), ("height", "INT")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[1.15, 0.5, 1024, 1024],
        col=1,
        row=0,
    )
    teacache = sg.add_node(
        "TeaCache",
        title="TeaCache Flux 2x Speed",
        inputs=[("model", "MODEL")],
        outputs=[("model", "MODEL")],
        widgets_values=["flux", 0.4, 0.0, 1.0, 1, "main_device"],
        col=2,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Flux LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=3,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Flux Prompt Encode",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    guidance = sg.add_node(
        "FluxGuidance",
        title="Flux Guidance 3.5",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[3.5],
        col=4,
        row=1,
    )
    neg_zero = sg.add_node(
        "ConditioningZeroOut",
        title="Inert Negative (CFG 1.0)",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=4,
        row=2,
    )
    lat = sg.add_node(
        "EmptySD3LatentImage",
        title="Flux 16-ch Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=4,
        row=0,
    )
    noise = sg.add_node(
        "RandomNoise",
        title="Seed Noise",
        inputs=[("noise_seed", "INT")],
        outputs=[("NOISE", "NOISE")],
        widgets_values=[42, "fixed"],
        col=5,
        row=2,
    )
    sel = sg.add_node(
        "KSamplerSelect",
        title="Euler Sampler",
        outputs=[("SAMPLER", "SAMPLER")],
        widgets_values=["euler"],
        col=5,
        row=0,
    )
    dd = sg.add_node(
        "DetailDaemonSamplerNode",
        title="DetailDaemon (Flux Texture)",
        inputs=[("sampler", "SAMPLER")],
        outputs=[("SAMPLER", "SAMPLER")],
        widgets_values=[0.2, 0.2, 0.8, 0.0, 0.0, 1.0, 0.0, 0.99, False],
        col=6,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    sched = sg.add_node(
        "BasicScheduler",
        title="Simple 24-Step",
        inputs=[("model", "MODEL")],
        outputs=[("SIGMAS", "SIGMAS")],
        widgets_values=["simple", 24, 1.0],
        col=5,
        row=1,
    )
    guider = sg.add_node(
        "BasicGuider",
        title="Flux BasicGuider",
        inputs=[("model", "MODEL"), ("conditioning", "CONDITIONING")],
        outputs=[("GUIDER", "GUIDER")],
        col=6,
        row=1,
    )
    samp = sg.add_node(
        "SamplerCustomAdvanced",
        title="Flux SamplerCustomAdvanced",
        inputs=[
            ("noise", "NOISE"),
            ("guider", "GUIDER"),
            ("sampler", "SAMPLER"),
            ("sigmas", "SIGMAS"),
            ("latent_image", "LATENT"),
        ],
        outputs=[("output", "LATENT"), ("denoised_output", "LATENT")],
        col=7,
        row=0,
    )

    sg.connect(unet, 0, ms_flux, 0, "MODEL")
    sg.connect(-10, io["width"], ms_flux, 1, "INT")
    sg.connect(-10, io["height"], ms_flux, 2, "INT")
    sg.connect(ms_flux, 0, teacache, 0, "MODEL")
    sg.connect(teacache, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(enc_pos, 0, guidance, 0, "CONDITIONING")
    sg.connect(enc_pos, 0, neg_zero, 0, "CONDITIONING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(-10, io["seed"], noise, 0, "INT")
    sg.connect(sel, 0, dd, 0, "SAMPLER")
    sg.connect(lora, 0, sched, 0, "MODEL")
    sg.connect(lora, 0, guider, 0, "MODEL")
    sg.connect(guidance, 0, guider, 1, "CONDITIONING")
    sg.connect(noise, 0, samp, 0, "NOISE")
    sg.connect(guider, 0, samp, 1, "GUIDER")
    sg.connect(dd, 0, samp, 2, "SAMPLER")
    sg.connect(sched, 0, samp, 3, "SIGMAS")
    sg.connect(lat, 0, samp, 4, "LATENT")

    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(guidance, 0),
        neg_src=(neg_zero, 0),
        latent_src=(samp, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=8,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(guidance, "guidance")
    sg.expose_widget(sched, "steps")
    return sg


def build_engine_flux1_kontext() -> SubgraphBuilder:
    sg = SubgraphBuilder("e07_flux1_kontext", "E07 · Flux.1 Kontext (Reference Edit)")
    io = _setup_standard_engine_io(sg, with_ref_image=True)

    unet = sg.add_node(
        "UNETLoader",
        title="Flux.1 Kontext Dev",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["flux1-kontext-dev-fp8.safetensors", "fp8_e4m3fn"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "DualCLIPLoader",
        title="DualCLIP (Flux)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors", "flux", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Flux AE VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["ae.safetensors"],
        col=0,
        row=2,
    )
    ref_fallback = sg.add_node(
        "LoadImage",
        title="Kontext Local Ref Image Fallback",
        outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
        widgets_values=["example.png", "image"],
        col=0,
        row=3,
    )
    ref_sw = sg.add_node(
        "Any Switch (rgthree)",
        title="Ref Source (S02 Armory or Local Fallback)",
        inputs=[("any_01", "*"), ("any_02", "*")],
        outputs=[("*", "*")],
        col=1,
        row=3,
    )
    kscale = sg.add_node(
        "FluxKontextImageScale",
        title="Kontext Optimal Scale",
        inputs=[("image", "IMAGE")],
        outputs=[("IMAGE", "IMAGE")],
        col=1,
        row=2,
    )
    v_enc = sg.add_node(
        "VAEEncode",
        title="Encode Ref Latent",
        inputs=[("pixels", "IMAGE"), ("vae", "VAE")],
        outputs=[("LATENT", "LATENT")],
        col=2,
        row=2,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Kontext LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=1,
        row=0,
    )
    teacache = sg.add_node(
        "TeaCache",
        title="TeaCache Accel",
        inputs=[("model", "MODEL")],
        outputs=[("model", "MODEL")],
        widgets_values=["flux", 0.35, 0.1, 0.95, 1, "main_device"],
        col=2,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Edit Instruction Prompt",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=2,
        row=1,
    )
    ref_lat = sg.add_node(
        "ReferenceLatent",
        title="Bind Reference Latent",
        inputs=[("conditioning", "CONDITIONING"), ("latent", "LATENT")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=3,
        row=1,
    )
    guidance = sg.add_node(
        "FluxGuidance",
        title="Kontext Guidance 2.5",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[2.5],
        col=4,
        row=1,
    )
    neg_zero = sg.add_node(
        "ConditioningZeroOut",
        title="Inert Negative",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=4,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Kontext Edit Sampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 20, 1.0, "euler", "simple", 1.0],
        col=5,
        row=0,
    )

    sg.connect(-10, io["ref_image"], ref_sw, 0, "IMAGE")
    sg.connect(ref_fallback, 0, ref_sw, 1, "IMAGE")
    sg.connect(ref_sw, 0, kscale, 0, "IMAGE")
    sg.connect(kscale, 0, v_enc, 0, "IMAGE")
    sg.connect(vae, 0, v_enc, 1, "VAE")
    sg.connect(unet, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 0, teacache, 0, "MODEL")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(enc_pos, 0, ref_lat, 0, "CONDITIONING")
    sg.connect(v_enc, 0, ref_lat, 1, "LATENT")
    sg.connect(ref_lat, 0, guidance, 0, "CONDITIONING")
    sg.connect(enc_pos, 0, neg_zero, 0, "CONDITIONING")
    sg.connect(teacache, 0, ks, 0, "MODEL")
    sg.connect(guidance, 0, ks, 1, "CONDITIONING")
    sg.connect(neg_zero, 0, ks, 2, "CONDITIONING")
    sg.connect(v_enc, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(teacache, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(guidance, 0),
        neg_src=(neg_zero, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=6,
    )
    sg.expose_widget(unet, "unet_name", "flux1-kontext-dev-fp8.safetensors")
    sg.expose_widget(ref_fallback, "image", "example.png")
    sg.expose_widget(guidance, "guidance", 2.5)
    sg.expose_widget(ks, "steps", 20)
    return sg


def build_engine_flux2_klein() -> SubgraphBuilder:
    sg = SubgraphBuilder("e08_flux2_klein", "E08 · Flux.2 Klein / Dev (GGUF)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UnetLoaderGGUF",
        title="Flux.2 Klein GGUF",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["flux2-klein-9b-Q6_K.gguf"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Qwen3-8B (flux2)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["qwen_3_8b_fp4mixed.safetensors", "flux2", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Flux.2 VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["flux2-vae.safetensors"],
        col=0,
        row=2,
    )
    ms = sg.add_node(
        "ModelSamplingFlux",
        title="Flux.2 Shift",
        inputs=[("model", "MODEL"), ("width", "INT"), ("height", "INT")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[1.15, 0.5, 1024, 1024],
        col=1,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Flux.2 LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc = sg.add_node(
        "CLIPTextEncode",
        title="Encode Prompt",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    neg_zero = sg.add_node(
        "ConditioningZeroOut",
        title="Inert Negative",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=3,
        row=2,
    )
    lat = sg.add_node(
        "EmptyFlux2LatentImage",
        title="Flux.2 Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=0,
    )
    sched = sg.add_node(
        "Flux2Scheduler",
        title="Flux.2 Scheduler",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("SIGMAS", "SIGMAS")],
        widgets_values=[20, 1024, 1024],
        col=4,
        row=1,
    )
    noise = sg.add_node(
        "RandomNoise",
        title="Seed Noise",
        inputs=[("noise_seed", "INT")],
        outputs=[("NOISE", "NOISE")],
        widgets_values=[42, "fixed"],
        col=4,
        row=2,
    )
    sel = sg.add_node(
        "KSamplerSelect",
        title="Euler",
        outputs=[("SAMPLER", "SAMPLER")],
        widgets_values=["euler"],
        col=4,
        row=0,
    )
    guider = sg.add_node(
        "BasicGuider",
        title="BasicGuider",
        inputs=[("model", "MODEL"), ("conditioning", "CONDITIONING")],
        outputs=[("GUIDER", "GUIDER")],
        col=5,
        row=1,
    )
    samp = sg.add_node(
        "SamplerCustomAdvanced",
        title="Flux.2 Sampler",
        inputs=[
            ("noise", "NOISE"),
            ("guider", "GUIDER"),
            ("sampler", "SAMPLER"),
            ("sigmas", "SIGMAS"),
            ("latent_image", "LATENT"),
        ],
        outputs=[("output", "LATENT"), ("denoised_output", "LATENT")],
        col=5,
        row=0,
    )

    sg.connect(unet, 0, ms, 0, "MODEL")
    sg.connect(-10, io["width"], ms, 1, "INT")
    sg.connect(-10, io["height"], ms, 2, "INT")
    sg.connect(ms, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc, 0, "CLIP")
    sg.connect(-10, io["pos"], enc, 1, "STRING")
    sg.connect(enc, 0, neg_zero, 0, "CONDITIONING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(-10, io["width"], sched, 0, "INT")
    sg.connect(-10, io["height"], sched, 1, "INT")
    sg.connect(-10, io["seed"], noise, 0, "INT")
    sg.connect(lora, 0, guider, 0, "MODEL")
    sg.connect(enc, 0, guider, 1, "CONDITIONING")
    sg.connect(noise, 0, samp, 0, "NOISE")
    sg.connect(guider, 0, samp, 1, "GUIDER")
    sg.connect(sel, 0, samp, 2, "SAMPLER")
    sg.connect(sched, 0, samp, 3, "SIGMAS")
    sg.connect(lat, 0, samp, 4, "LATENT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc, 0),
        neg_src=(neg_zero, 0),
        latent_src=(samp, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=6,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(sched, "steps")
    return sg


def build_engine_flux3_kv() -> SubgraphBuilder:
    sg = SubgraphBuilder("e09_flux3_kv", "E09 · Flux.3 (KVCache + Layout)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="Flux.3 UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["flux3-dev-fp8.safetensors", "fp8_e4m3fn"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Flux.3 Text Encoder (flux3)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["flux3_text_encoder_fp8.safetensors", "flux3", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Flux.3 VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["flux2-vae.safetensors"],
        col=0,
        row=2,
    )
    kv = sg.add_node(
        "FluxKVCache",
        title="Flux KVCache Accel",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        col=1,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Flux.3 LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc = sg.add_node(
        "CLIPTextEncode",
        title="Flux.3 Prompt Encode",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    neg_zero = sg.add_node(
        "ConditioningZeroOut",
        title="Inert Negative",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=3,
        row=2,
    )
    lat = sg.add_node(
        "EmptyFlux2LatentImage",
        title="Flux.3 Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=0,
    )
    ks = sg.add_node(
        "KSampler",
        title="Flux.3 Sampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 24, 1.0, "euler", "simple", 1.0],
        col=4,
        row=0,
    )
    sg.connect(unet, 0, kv, 0, "MODEL")
    sg.connect(kv, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc, 0, "CLIP")
    sg.connect(-10, io["pos"], enc, 1, "STRING")
    sg.connect(enc, 0, neg_zero, 0, "CONDITIONING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc, 0, ks, 1, "CONDITIONING")
    sg.connect(neg_zero, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc, 0),
        neg_src=(neg_zero, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_chroma() -> SubgraphBuilder:
    sg = SubgraphBuilder("e10_chroma", "E10 · Chroma (Uncensored Flow DiT)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="Chroma UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["chroma-unlocked-v46.safetensors", "fp8_e4m3fn"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="T5-XXL (chroma)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["t5xxl_fp8_e4m3fn.safetensors", "chroma", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Flux AE VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["ae.safetensors"],
        col=0,
        row=2,
    )
    aura = sg.add_node(
        "ModelSamplingAuraFlow",
        title="Chroma Flow Shift",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[1.0],
        col=1,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Chroma LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    lat = sg.add_node(
        "EmptySD3LatentImage",
        title="Chroma 16-ch Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Chroma KSampler (CFG 4.0)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 26, 4.0, "euler", "beta", 1.0],
        col=4,
        row=0,
    )
    sg.connect(unet, 0, aura, 0, "MODEL")
    sg.connect(aura, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_moss_image() -> SubgraphBuilder:
    sg = SubgraphBuilder("e11_moss_image", "E11 · MOSS-Image (INT8 / DMD8 Distilled)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="MOSS-Image SFT INT8",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["moss_image_sft_int8.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Qwen3.5-9B (moss_image)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["qwen3.5_9b_w4a8.safetensors", "moss_image", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="MOSS Flux2-Small VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["flux2-vae_small.safetensors"],
        col=0,
        row=2,
    )
    aura = sg.add_node(
        "ModelSamplingAuraFlow",
        title="MOSS Shift 5.0",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[5.0],
        col=1,
        row=0,
    )
    dmd8 = sg.add_node(
        "LoraLoaderModelOnly",
        title="DMD8 8-Step Accel (Optional)",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=["moss_dmd8_accel.safetensors", 1.0],
        col=2,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="MOSS Style/LoHA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=3,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=1,
    )
    lat = sg.add_node(
        "EmptyFlux2LatentImage",
        title="MOSS Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=4,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="MOSS KSampler (er_sde, CFG 2.5)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 25, 2.5, "er_sde", "simple", 1.0],
        col=5,
        row=0,
    )
    sg.connect(unet, 0, aura, 0, "MODEL")
    sg.connect(aura, 0, dmd8, 0, "MODEL")
    sg.connect(dmd8, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=6,
        tiled_vae=True,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(aura, "shift")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_qwen21() -> SubgraphBuilder:
    sg = SubgraphBuilder("e12_qwen21", "E12 · Qwen-Image 2.1 (CJK Typography)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="Qwen-Image 2.1 UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["qwen_image_2.1_int8.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Qwen3-VL-8B (qwen_image)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["qwen3vl_8b_w4a8.safetensors", "qwen_image", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Qwen-Image 2.1 VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["qwen_image_2.1_vae_bf16.safetensors"],
        col=0,
        row=2,
    )
    aura = sg.add_node(
        "ModelSamplingAuraFlow",
        title="Qwen Shift 3.1",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[3.1],
        col=1,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Qwen-Image LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc = sg.add_node(
        "TextEncodeQwenImage21",
        title="Qwen 2.1 Dual Prompt Encode",
        inputs=[("clip", "CLIP"), ("prompt", "STRING"), ("negative_prompt", "STRING")],
        outputs=[("positive", "CONDITIONING"), ("negative", "CONDITIONING")],
        widgets_values=["", "", 1024],
        col=3,
        row=1,
    )
    lat = sg.add_node(
        "EmptyLatentImage",
        title="Qwen Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Qwen 2.1 Sampler (16-step CFG 1)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 16, 1.0, "euler", "simple", 1.0],
        col=4,
        row=0,
    )
    sg.connect(unet, 0, aura, 0, "MODEL")
    sg.connect(aura, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc, 0, "CLIP")
    sg.connect(-10, io["pos"], enc, 1, "STRING")
    sg.connect(-10, io["neg"], enc, 2, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc, 0, ks, 1, "CONDITIONING")
    sg.connect(enc, 1, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc, 0),
        neg_src=(enc, 1),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_krea2() -> SubgraphBuilder:
    sg = SubgraphBuilder("e13_krea2", "E13 · Krea-2 (8-Step Photoreal)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="Krea-2 INT8 UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["krea2_base_int8.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Qwen3-VL-4B (krea2)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["qwen3vl_4b_fp8_scaled.safetensors", "krea2", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Qwen 16-ch VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["qwen_image_vae.safetensors"],
        col=0,
        row=2,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Krea-2 LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=1,
        row=0,
    )
    enc = sg.add_node(
        "CLIPTextEncode",
        title="Encode Prompt",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=2,
        row=0,
    )
    neg_zero = sg.add_node(
        "ConditioningZeroOut",
        title="Zero Negative (CFG 1.0)",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=2,
        row=1,
    )
    lat = sg.add_node(
        "EmptyLatentImage",
        title="Krea-2 Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=2,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Krea-2 8-Step Sampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 8, 1.0, "euler", "simple", 1.0],
        col=3,
        row=0,
    )
    sg.connect(unet, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc, 0, "CLIP")
    sg.connect(-10, io["pos"], enc, 1, "STRING")
    sg.connect(enc, 0, neg_zero, 0, "CONDITIONING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc, 0, ks, 1, "CONDITIONING")
    sg.connect(neg_zero, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc, 0),
        neg_src=(neg_zero, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=4,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_minimax_h3() -> SubgraphBuilder:
    sg = SubgraphBuilder("e14_minimax_h3", "E14 · MiniMax-H3-Image (Split-Sigma 4MP)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="MiniMax-H3 UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["minimax_h3_image_fp8.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Qwen3-VL-32B (minimax)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["qwen3vl_32b_minimax_h3_bf16.safetensors", "minimax", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="MiniMax-H3 VAE FP32",
        outputs=[("VAE", "VAE")],
        widgets_values=["minimax_h3_image_vae_fp32.safetensors"],
        col=0,
        row=2,
    )
    cond = sg.add_node(
        "MiniMaxH3ImageConditioning",
        title="MiniMax-H3 Conditioning",
        inputs=[("clip", "CLIP"), ("vae", "VAE"), ("prompt", "STRING"), ("width", "INT"), ("height", "INT")],
        outputs=[("CONDITIONING", "CONDITIONING"), ("LATENT", "LATENT")],
        widgets_values=["", 1664, 2432],
        col=1,
        row=1,
    )
    neg_zero = sg.add_node(
        "ConditioningZeroOut",
        title="Inert Negative",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=2,
        row=2,
    )
    g1 = sg.add_node(
        "BasicGuider",
        title="Stage-1 High-Sigma Guider",
        inputs=[("model", "MODEL"), ("conditioning", "CONDITIONING")],
        outputs=[("GUIDER", "GUIDER")],
        col=2,
        row=0,
    )
    noise = sg.add_node(
        "RandomNoise",
        title="Seed Noise",
        inputs=[("noise_seed", "INT")],
        outputs=[("NOISE", "NOISE")],
        widgets_values=[42, "fixed"],
        col=2,
        row=1,
    )
    sel = sg.add_node(
        "KSamplerSelect",
        title="Euler",
        outputs=[("SAMPLER", "SAMPLER")],
        widgets_values=["euler"],
        col=3,
        row=2,
    )
    sig1 = sg.add_node(
        "ManualSigmas",
        title="High-Sigma Composition Pass",
        outputs=[("SIGMAS", "SIGMAS")],
        widgets_values=["1.0, 0.9675"],
        col=3,
        row=1,
    )
    s1 = sg.add_node(
        "SamplerCustomAdvanced",
        title="Stage-1 Composition Sampler",
        inputs=[
            ("noise", "NOISE"),
            ("guider", "GUIDER"),
            ("sampler", "SAMPLER"),
            ("sigmas", "SIGMAS"),
            ("latent_image", "LATENT"),
        ],
        outputs=[("output", "LATENT"), ("denoised_output", "LATENT")],
        col=3,
        row=0,
    )
    lora_s2 = sg.add_node(
        "LoraLoaderModelOnly",
        title="Stage-2 Detail LoRA (Optional)",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=["h3_style_detail_lora.safetensors", 0.0],
        col=4,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    no_noise = sg.add_node("DisableNoise", title="Disable Noise", outputs=[("NOISE", "NOISE")], col=4, row=2)
    sig2 = sg.add_node(
        "ManualSigmas",
        title="Low-Sigma Detail Pass",
        outputs=[("SIGMAS", "SIGMAS")],
        widgets_values=["0.9675, 0.8875, 0.75, 0.5327, 0.30, 0.12, 0.0"],
        col=4,
        row=1,
    )
    g2 = sg.add_node(
        "BasicGuider",
        title="Stage-2 Detail Guider",
        inputs=[("model", "MODEL"), ("conditioning", "CONDITIONING")],
        outputs=[("GUIDER", "GUIDER")],
        col=5,
        row=1,
    )
    s2 = sg.add_node(
        "SamplerCustomAdvanced",
        title="Stage-2 Detail Sampler",
        inputs=[
            ("noise", "NOISE"),
            ("guider", "GUIDER"),
            ("sampler", "SAMPLER"),
            ("sigmas", "SIGMAS"),
            ("latent_image", "LATENT"),
        ],
        outputs=[("output", "LATENT"), ("denoised_output", "LATENT")],
        col=5,
        row=0,
    )

    sg.connect(clip, 0, cond, 0, "CLIP")
    sg.connect(vae, 0, cond, 1, "VAE")
    sg.connect(-10, io["pos"], cond, 2, "STRING")
    sg.connect(-10, io["width"], cond, 3, "INT")
    sg.connect(-10, io["height"], cond, 4, "INT")
    sg.connect(cond, 0, neg_zero, 0, "CONDITIONING")
    sg.connect(unet, 0, g1, 0, "MODEL")
    sg.connect(cond, 0, g1, 1, "CONDITIONING")
    sg.connect(-10, io["seed"], noise, 0, "INT")
    sg.connect(noise, 0, s1, 0, "NOISE")
    sg.connect(g1, 0, s1, 1, "GUIDER")
    sg.connect(sel, 0, s1, 2, "SAMPLER")
    sg.connect(sig1, 0, s1, 3, "SIGMAS")
    sg.connect(cond, 1, s1, 4, "LATENT")
    sg.connect(unet, 0, lora_s2, 0, "MODEL")
    sg.connect(lora_s2, 0, g2, 0, "MODEL")
    sg.connect(cond, 0, g2, 1, "CONDITIONING")
    sg.connect(no_noise, 0, s2, 0, "NOISE")
    sg.connect(g2, 0, s2, 1, "GUIDER")
    sg.connect(sel, 0, s2, 2, "SAMPLER")
    sg.connect(sig2, 0, s2, 3, "SIGMAS")
    sg.connect(s1, 0, s2, 4, "LATENT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora_s2, 0),
        clip_src=(clip, 0),
        vae_src=(vae, 0),
        pos_src=(cond, 0),
        neg_src=(neg_zero, 0),
        latent_src=(s2, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=6,
        tiled_vae=True,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(sig2, "sigmas")
    return sg


def build_engine_sd35() -> SubgraphBuilder:
    sg = SubgraphBuilder("e15_sd35", "E15 · SD 3.5 Large / Medium (TripleCLIP)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="SD 3.5 UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["sd3.5_large_fp8_scaled.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "TripleCLIPLoader",
        title="TripleCLIP (L + G + T5)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["clip_l.safetensors", "clip_g.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="SD 3.5 16-ch VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["sd3_vae.safetensors"],
        col=0,
        row=2,
    )
    ms = sg.add_node(
        "ModelSamplingSD3",
        title="SD3 Shift 3.0",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[3.0],
        col=1,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="SD 3.5 LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    lat = sg.add_node(
        "EmptySD3LatentImage",
        title="SD3 16-ch Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="SD 3.5 KSampler (CFG 4.5)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 28, 4.5, "dpmpp_2m", "sgm_uniform", 1.0],
        col=4,
        row=0,
    )
    sg.connect(unet, 0, ms, 0, "MODEL")
    sg.connect(ms, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_hidream() -> SubgraphBuilder:
    sg = SubgraphBuilder("e16_hidream", "E16 · HiDream-I1 / O1 (QuadCLIP)")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="HiDream-I1 Full FP8",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["hidream_i1_full_fp8.safetensors", "fp8_e4m3fn"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "QuadrupleCLIPLoader",
        title="QuadCLIP (L + G + T5 + Llama3)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=[
            "clip_l_hidream.safetensors",
            "clip_g_hidream.safetensors",
            "t5xxl_fp8_e4m3fn.safetensors",
            "llama_3.1_8b_instruct_fp8_scaled.safetensors",
        ],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="HiDream AE VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["ae.safetensors"],
        col=0,
        row=2,
    )
    ms = sg.add_node(
        "ModelSamplingSD3",
        title="HiDream Shift 3.0",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[3.0],
        col=1,
        row=0,
    )
    teacache = sg.add_node(
        "TeaCache",
        title="TeaCache HiDream",
        inputs=[("model", "MODEL")],
        outputs=[("model", "MODEL")],
        widgets_values=["hidream_i1_full", 0.35, 0.1, 0.9, 1, "main_device"],
        col=2,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="HiDream LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=3,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="HiDream Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="HiDream Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=4,
        row=1,
    )
    lat = sg.add_node(
        "EmptyHiDreamO1LatentImage",
        title="HiDream Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=4,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="HiDream KSampler (uni_pc)",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 28, 5.0, "uni_pc", "simple", 1.0],
        col=5,
        row=0,
    )
    sg.connect(unet, 0, ms, 0, "MODEL")
    sg.connect(ms, 0, teacache, 0, "MODEL")
    sg.connect(teacache, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=6,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_lumina2_zimage() -> SubgraphBuilder:
    sg = SubgraphBuilder("e17_lumina2_zimage", "E17 · Lumina-2 / Z-Image / NewBie")
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="Lumina-2 / Z-Image UNet",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["lumina_image_2.0_bf16.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Gemma-2-2B / Qwen (lumina2)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["gemma_2_2b_fp16.safetensors", "lumina2", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Flux AE VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["ae.safetensors"],
        col=0,
        row=2,
    )
    aura = sg.add_node(
        "ModelSamplingAuraFlow",
        title="Lumina2 Shift 6.0",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[6.0],
        col=1,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Lumina-2 LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncodeLumina2",
        title="Lumina-2 System+User Prompt",
        inputs=[("clip", "CLIP"), ("user_prompt", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=["superior", ""],
        col=3,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    lat = sg.add_node(
        "EmptySD3LatentImage",
        title="16-ch Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Lumina-2 KSampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 30, 4.0, "res_multistep", "simple", 1.0],
        col=4,
        row=0,
    )
    sg.connect(unet, 0, aura, 0, "MODEL")
    sg.connect(aura, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(aura, "shift")
    sg.expose_widget(ks, "steps")
    return sg


def build_engine_niche_universal() -> SubgraphBuilder:
    """Universal Frontier Vault covering ALL 14 remaining niche CLIPLoader DiT architectures."""
    sg = SubgraphBuilder(
        "e18_niche_vault",
        "E18 · Niche Frontier Vault (OmniGen2/Hunyuan/LongCat/PixArt/Ovis/Fibo2/Pan2+)",
    )
    io = _setup_standard_engine_io(sg)

    unet = sg.add_node(
        "UNETLoader",
        title="Niche DiT UNet (Any Arch)",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["omnigen2_fp16.safetensors", "default"],
        col=0,
        row=0,
    )
    clip = sg.add_node(
        "CLIPLoader",
        title="Niche CLIP Type Selector (14 Arches)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["qwen2.5_vl_3b_fp16.safetensors", "omnigen2", "default"],
        col=0,
        row=1,
    )
    vae = sg.add_node(
        "VAELoader",
        title="Niche Matching VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["ae.safetensors"],
        col=0,
        row=2,
    )
    aura = sg.add_node(
        "ModelSamplingAuraFlow",
        title="Universal Flow Shift (Bypass=SD/Eps)",
        inputs=[("model", "MODEL")],
        outputs=[("MODEL", "MODEL")],
        widgets_values=[3.0],
        col=1,
        row=0,
    )
    lora = sg.add_node(
        "Power Lora Loader (rgthree)",
        title="Niche LoRA Stack",
        inputs=[("model", "MODEL"), ("clip", "CLIP")],
        outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
        widgets_values=[{}, {"type": "PowerLoraLoaderHeaderWidget"}, {}],
        col=2,
        row=0,
    )
    enc_pos = sg.add_node(
        "CLIPTextEncode",
        title="Encode Positive",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=0,
    )
    enc_neg = sg.add_node(
        "CLIPTextEncode",
        title="Encode Negative",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=3,
        row=1,
    )
    lat = sg.add_node(
        "EmptySD3LatentImage",
        title="16-ch Universal Latent",
        inputs=[("width", "INT"), ("height", "INT")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[1024, 1024, 1],
        col=3,
        row=2,
    )
    ks = sg.add_node(
        "KSampler",
        title="Universal Niche KSampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 28, 4.0, "euler", "simple", 1.0],
        col=4,
        row=0,
    )
    guide = sg.add_node(
        "MarkdownNote",
        title="Supported Niche CLIPLoader Types",
        widgets_values=[
            "Switch `CLIPLoader.type` for: `omnigen2`, `hunyuan_image`, `longcat_image`, `ovis`, "
            "`pixeldit`, `ideogram4`, `boogu`, `joyimage`, `mage`, `fibo2`, `pan2`, `pixart`, "
            "`cosmos`, `stable_cascade`."
        ],
        col=1,
        row=2,
        size=(300, 110),
    )
    _ = guide

    sg.connect(unet, 0, aura, 0, "MODEL")
    sg.connect(aura, 0, lora, 0, "MODEL")
    sg.connect(clip, 0, lora, 1, "CLIP")
    sg.connect(lora, 1, enc_pos, 0, "CLIP")
    sg.connect(-10, io["pos"], enc_pos, 1, "STRING")
    sg.connect(lora, 1, enc_neg, 0, "CLIP")
    sg.connect(-10, io["neg"], enc_neg, 1, "STRING")
    sg.connect(-10, io["width"], lat, 0, "INT")
    sg.connect(-10, io["height"], lat, 1, "INT")
    sg.connect(lora, 0, ks, 0, "MODEL")
    sg.connect(enc_pos, 0, ks, 1, "CONDITIONING")
    sg.connect(enc_neg, 0, ks, 2, "CONDITIONING")
    sg.connect(lat, 0, ks, 3, "LATENT")
    sg.connect(-10, io["seed"], ks, 4, "INT")
    _wire_tail_decode_pipe(
        sg,
        model_src=(lora, 0),
        clip_src=(lora, 1),
        vae_src=(vae, 0),
        pos_src=(enc_pos, 0),
        neg_src=(enc_neg, 0),
        latent_src=(ks, 0),
        out_image_slot=io["out_image"],
        out_pipe_slot=io["out_pipe"],
        col=5,
    )
    sg.expose_widget(unet, "unet_name")
    sg.expose_widget(clip, "type")
    sg.expose_widget(ks, "steps")
    return sg


# ---------------------------------------------------------------------------
# 6 Ubisoft Pre- & Post-Production Station Subgraphs
# ---------------------------------------------------------------------------


def build_station_s01_prompt_vlm() -> SubgraphBuilder:
    """Strictly 1 STRING in -> 1 STRING out so mode=4 (BYPASS) is 100% lossless."""
    sg = SubgraphBuilder("s01_prompt_vlm", "S01 · Prompt, Wildcards & VLM Intelligence Lab")
    in_pos = sg.add_input("positive_prompt", "STRING", "Raw Prompt")
    in_seed = sg.add_input("seed", "INT", "Seed")
    out_pos = sg.add_output("STRING", "STRING", "Enhanced Prompt")

    ref_img = sg.add_node(
        "LoadImage",
        title="VLM Reverse-Caption Source",
        outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
        widgets_values=["example.png", "image"],
        col=0,
        row=1,
        mode=NODE_MODE_BYPASS,
    )
    florence_dl = sg.add_node(
        "DownloadAndLoadFlorence2Model",
        title="Florence-2 Large VLM",
        outputs=[("florence2_model", "FL2MODEL")],
        widgets_values=["microsoft/Florence-2-large", "fp16", "sdpa"],
        col=0,
        row=2,
        mode=NODE_MODE_BYPASS,
    )
    florence = sg.add_node(
        "Florence2Run",
        title="VLM Image-to-Prompt Reverse",
        inputs=[("image", "IMAGE"), ("florence2_model", "FL2MODEL")],
        outputs=[("image", "IMAGE"), ("mask", "MASK"), ("caption", "STRING"), ("data", "JSON")],
        widgets_values=["", "more_detailed_caption", True, False, 1024, 3, True, "", 42],
        col=1,
        row=1,
        mode=NODE_MODE_BYPASS,
    )
    empty_cap = sg.add_node(
        "PrimitiveString",
        title="Empty Caption Fallback (When VLM Bypassed)",
        outputs=[("STRING", "STRING")],
        widgets_values=[""],
        col=1,
        row=2,
    )
    cap_sw = sg.add_node(
        "Any Switch (rgthree)",
        title="VLM Caption Fallback Switch",
        inputs=[("any_01", "*"), ("any_02", "*")],
        outputs=[("*", "*")],
        col=2,
        row=1,
    )
    wild = sg.add_node(
        "easy wildcards",
        title="Dynamic Wildcard & Style Bank",
        inputs=[("text", "STRING"), ("seed", "INT")],
        outputs=[("text", "STRING"), ("populated_text", "STRING")],
        widgets_values=["", "None", "None", 42, True],
        col=1,
        row=0,
    )
    trig = sg.add_node(
        "TriggerWord Toggle (LoraManager)",
        title="LoRA Manager Trigger Words",
        outputs=[("filtered_trigger_words", "STRING")],
        widgets_values=[True, True, False],
        col=3,
        row=2,
    )
    concat1 = sg.add_node(
        "easy promptConcat",
        title="Merge Prompt + VLM Caption",
        inputs=[("prompt1", "STRING"), ("prompt2", "STRING")],
        outputs=[("prompt", "STRING")],
        widgets_values=[", "],
        col=2,
        row=0,
    )
    concat2 = sg.add_node(
        "easy promptConcat",
        title="Inject Trigger Words",
        inputs=[("prompt1", "STRING"), ("prompt2", "STRING")],
        outputs=[("prompt", "STRING")],
        widgets_values=[", "],
        col=3,
        row=0,
    )
    llm = sg.add_node(
        "PromptAssistantNode",
        title="LLM Prompt Enhancer (Optional)",
        inputs=[("prompt", "STRING")],
        outputs=[("prompt", "STRING")],
        widgets_values=["expand_cinematic", "en", 0.7],
        col=4,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    show = sg.add_node(
        "easy showAnything",
        title="Final Compiled Prompt Readout",
        inputs=[("anything", "*")],
        outputs=[("output", "*")],
        col=5,
        row=0,
    )

    sg.connect(-10, in_pos, wild, 0, "STRING")
    sg.connect(-10, in_seed, wild, 1, "INT")
    sg.connect(ref_img, 0, florence, 0, "IMAGE")
    sg.connect(florence_dl, 0, florence, 1, "FL2MODEL")
    sg.connect(florence, 2, cap_sw, 0, "STRING")
    sg.connect(empty_cap, 0, cap_sw, 1, "STRING")
    sg.connect(wild, 1, concat1, 0, "STRING")
    sg.connect(cap_sw, 0, concat1, 1, "STRING")
    sg.connect(concat1, 0, concat2, 0, "STRING")
    sg.connect(trig, 0, concat2, 1, "STRING")
    sg.connect(concat2, 0, llm, 0, "STRING")
    sg.connect(llm, 0, show, 0, "STRING")
    sg.connect(show, 0, -20, out_pos, "STRING")

    sg.expose_widget(wild, "Select to add Wildcard")
    sg.expose_widget(florence, "task")
    return sg


def build_station_s02_controlnet_armory() -> SubgraphBuilder:
    sg = SubgraphBuilder("s02_controlnet_armory", "S02 · ControlNet Union & IPAdapter Armory")
    in_w = sg.add_input("width", "INT", "Width")
    in_h = sg.add_input("height", "INT", "Height")
    out_ref = sg.add_output("IMAGE", "IMAGE", "Ref Image")
    out_cn = sg.add_output("CONTROL_NET", "CONTROL_NET", "ControlNet")
    out_map = sg.add_output("IMAGE", "IMAGE", "CN Map")

    ref_src = sg.add_node(
        "LoadImage",
        title="Reference / Structure / Edit Image",
        outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
        widgets_values=["example.png", "image"],
        col=0,
        row=0,
    )
    resize = sg.add_node(
        "ImageResizeKJv2",
        title="Aspect-Safe Ref Resize",
        inputs=[("image", "IMAGE"), ("width", "INT"), ("height", "INT")],
        outputs=[("IMAGE", "IMAGE"), ("width", "INT"), ("height", "INT"), ("mask", "MASK")],
        widgets_values=[1024, 1024, "lanczos", "crop", "0, 0, 0", "center", 16, "cpu"],
        col=1,
        row=0,
    )
    aio = sg.add_node(
        "AIO_Preprocessor",
        title="AIO Preprocessor (Lineart/Canny/HED)",
        inputs=[("image", "IMAGE")],
        outputs=[("IMAGE", "IMAGE")],
        widgets_values=["AnyLineArtPreprocessor_aux", 1024],
        col=2,
        row=0,
    )
    dwpose = sg.add_node(
        "DWPreprocessor",
        title="DWPose Body+Hand+Face",
        inputs=[("image", "IMAGE")],
        outputs=[("IMAGE", "IMAGE"), ("POSE_KEYPOINT", "POSE_KEYPOINT")],
        widgets_values=["enable", "enable", "enable", 1024, "yolox_l.onnx", "dw-ll_ucoco_384_bs5.torchscript.pt", "disable"],
        col=2,
        row=1,
    )
    depth = sg.add_node(
        "DepthAnythingV2Preprocessor",
        title="Depth Anything V2 Large",
        inputs=[("image", "IMAGE")],
        outputs=[("IMAGE", "IMAGE")],
        widgets_values=["depth_anything_v2_vitl.pth", 1024],
        col=2,
        row=2,
    )
    sw = sg.add_node(
        "easy anythingIndexSwitch",
        title="CN Map Selector (0=AIO 1=Pose 2=Depth)",
        inputs=[("value0", "*"), ("value1", "*"), ("value2", "*")],
        outputs=[("value", "*")],
        widgets_values=[0],
        col=3,
        row=1,
    )
    cn_load = sg.add_node(
        "ControlNetLoader",
        title="ControlNet Union ProMax",
        outputs=[("CONTROL_NET", "CONTROL_NET")],
        widgets_values=["controlnet_union_promax_sdxl.safetensors"],
        col=3,
        row=0,
    )

    sg.connect(ref_src, 0, resize, 0, "IMAGE")
    sg.connect(-10, in_w, resize, 1, "INT")
    sg.connect(-10, in_h, resize, 2, "INT")
    sg.connect(resize, 0, aio, 0, "IMAGE")
    sg.connect(resize, 0, dwpose, 0, "IMAGE")
    sg.connect(resize, 0, depth, 0, "IMAGE")
    sg.connect(aio, 0, sw, 0, "IMAGE")
    sg.connect(dwpose, 0, sw, 1, "IMAGE")
    sg.connect(depth, 0, sw, 2, "IMAGE")
    sg.connect(resize, 0, -20, out_ref, "IMAGE")
    sg.connect(cn_load, 0, -20, out_cn, "CONTROL_NET")
    sg.connect(sw, 0, -20, out_map, "IMAGE")

    sg.expose_widget(ref_src, "image")
    sg.expose_widget(sw, "index")
    sg.expose_widget(aio, "preprocessor")
    return sg


def build_station_s03_anatomy_segs() -> SubgraphBuilder:
    """Distinct input types (IMAGE, BASIC_PIPE, INT) -> bypass passes IMAGE & BASIC_PIPE cleanly."""
    sg = SubgraphBuilder("s03_anatomy_segs", "S03 · Anatomy SEGS Surgical Lab (Face/Eyes/Hands/Feet)")
    in_img = sg.add_input("image", "IMAGE", "Image")
    in_pipe = sg.add_input("basic_pipe", "BASIC_PIPE", "BasicPipe")
    in_seed = sg.add_input("seed", "INT", "Seed")
    out_img = sg.add_output("IMAGE", "IMAGE", "Detailed Image")
    out_pipe = sg.add_output("BASIC_PIPE", "BASIC_PIPE", "BasicPipe")

    unpack = sg.add_node(
        "FromBasicPipe",
        title="Unpack Active Engine Pipe",
        inputs=[("basic_pipe", "BASIC_PIPE")],
        outputs=[
            ("model", "MODEL"),
            ("clip", "CLIP"),
            ("vae", "VAE"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
        ],
        col=0,
        row=0,
    )
    det_face = sg.add_node(
        "UltralyticsDetectorProvider",
        title="Face Detector (YOLOv9c)",
        outputs=[("BBOX_DETECTOR", "BBOX_DETECTOR"), ("SEGM_DETECTOR", "SEGM_DETECTOR")],
        widgets_values=["bbox/face_yolov9c.pt"],
        col=0,
        row=1,
    )
    det_eye = sg.add_node(
        "UltralyticsDetectorProvider",
        title="Eye Detector (Eyeful v2)",
        outputs=[("BBOX_DETECTOR", "BBOX_DETECTOR"), ("SEGM_DETECTOR", "SEGM_DETECTOR")],
        widgets_values=["bbox/Eyeful_v2-Individual.pt"],
        col=1,
        row=2,
    )
    det_hand = sg.add_node(
        "UltralyticsDetectorProvider",
        title="Hand Detector (YOLOv9c)",
        outputs=[("BBOX_DETECTOR", "BBOX_DETECTOR"), ("SEGM_DETECTOR", "SEGM_DETECTOR")],
        widgets_values=["bbox/hand_yolov9c.pt"],
        col=2,
        row=2,
    )
    det_foot = sg.add_node(
        "UltralyticsDetectorProvider",
        title="Foot Detector (YOLOv8s)",
        outputs=[("BBOX_DETECTOR", "BBOX_DETECTOR"), ("SEGM_DETECTOR", "SEGM_DETECTOR")],
        widgets_values=["bbox/foot_yolov8s.pt"],
        col=3,
        row=2,
    )

    face_fix = sg.add_node(
        "FaceDetailer",
        title="Pass 1 · Face Detailer",
        inputs=[
            ("image", "IMAGE"),
            ("model", "MODEL"),
            ("clip", "CLIP"),
            ("vae", "VAE"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("bbox_detector", "BBOX_DETECTOR"),
            ("seed", "INT"),
        ],
        outputs=[
            ("image", "IMAGE"),
            ("cropped_refined", "IMAGE"),
            ("cropped_enhanced_alpha", "IMAGE"),
            ("mask", "MASK"),
            ("detailer_pipe", "DETAILER_PIPE"),
            ("cnet_images", "IMAGE"),
        ],
        widgets_values=[
            512, True, 1024, 42, "fixed", 18, 5.5, "euler_ancestral", "karras",
            0.38, 8, True, True, 0.5, 10, 2.5, "center-1", 0, 0.93, 0, 0.7,
            "False", 10, "", 1, False, 20, False, False,
        ],
        col=1,
        row=0,
    )

    def _add_segs_pass(col_idx: int, label: str, det_id: int, img_src: tuple[int, int], denoise: float, mode: int) -> int:
        segs = sg.add_node(
            "BboxDetectorSEGS",
            title=f"Detect {label} SEGS",
            inputs=[("bbox_detector", "BBOX_DETECTOR"), ("image", "IMAGE")],
            outputs=[("SEGS", "SEGS")],
            widgets_values=[0.45, 10, 2.5, 10, "all"],
            col=col_idx,
            row=1,
            mode=mode,
        )
        detail = sg.add_node(
            "DetailerForEach",
            title=f"Refine {label}",
            inputs=[
                ("image", "IMAGE"),
                ("segs", "SEGS"),
                ("model", "MODEL"),
                ("clip", "CLIP"),
                ("vae", "VAE"),
                ("positive", "CONDITIONING"),
                ("negative", "CONDITIONING"),
                ("seed", "INT"),
            ],
            outputs=[("image", "IMAGE")],
            widgets_values=[
                512, True, 1024, 42, "fixed", 16, 5.0, "euler_ancestral", "karras",
                denoise, 8, True, True, "", 1, False, 20, False, False,
            ],
            col=col_idx,
            row=0,
            mode=mode,
        )
        sg.connect(det_id, 0, segs, 0, "BBOX_DETECTOR")
        sg.connect(img_src[0], img_src[1], segs, 1, "IMAGE")
        sg.connect(img_src[0], img_src[1], detail, 0, "IMAGE")
        sg.connect(segs, 0, detail, 1, "SEGS")
        sg.connect(unpack, 0, detail, 2, "MODEL")
        sg.connect(unpack, 1, detail, 3, "CLIP")
        sg.connect(unpack, 2, detail, 4, "VAE")
        sg.connect(unpack, 3, detail, 5, "CONDITIONING")
        sg.connect(unpack, 4, detail, 6, "CONDITIONING")
        sg.connect(-10, in_seed, detail, 7, "INT")
        return detail

    sg.connect(-10, in_pipe, unpack, 0, "BASIC_PIPE")
    sg.connect(-10, in_img, face_fix, 0, "IMAGE")
    sg.connect(unpack, 0, face_fix, 1, "MODEL")
    sg.connect(unpack, 1, face_fix, 2, "CLIP")
    sg.connect(unpack, 2, face_fix, 3, "VAE")
    sg.connect(unpack, 3, face_fix, 4, "CONDITIONING")
    sg.connect(unpack, 4, face_fix, 5, "CONDITIONING")
    sg.connect(det_face, 0, face_fix, 6, "BBOX_DETECTOR")
    sg.connect(-10, in_seed, face_fix, 7, "INT")

    eye_fix = _add_segs_pass(2, "Eyes", det_eye, (face_fix, 0), 0.30, NODE_MODE_ALWAYS)
    hand_fix = _add_segs_pass(3, "Hands", det_hand, (eye_fix, 0), 0.42, NODE_MODE_ALWAYS)
    foot_fix = _add_segs_pass(4, "Feet", det_foot, (hand_fix, 0), 0.40, NODE_MODE_BYPASS)

    sg.connect(foot_fix, 0, -20, out_img, "IMAGE")
    sg.connect(-10, in_pipe, -20, out_pipe, "BASIC_PIPE")
    sg.expose_widget(face_fix, "denoise")
    sg.expose_widget(det_face, "model_name")
    return sg


def build_station_s04_hires_upscale() -> SubgraphBuilder:
    sg = SubgraphBuilder("s04_hires_upscale", "S04 · Dual-Track 4x GAN & Tiled HiRes Upscale Forge")
    in_img = sg.add_input("image", "IMAGE", "Image")
    in_pipe = sg.add_input("basic_pipe", "BASIC_PIPE", "BasicPipe")
    in_seed = sg.add_input("seed", "INT", "Seed")
    out_img = sg.add_output("IMAGE", "IMAGE", "Upscaled Image")
    out_pipe = sg.add_output("BASIC_PIPE", "BASIC_PIPE", "BasicPipe")

    up_model = sg.add_node(
        "UpscaleModelLoader",
        title="4x GAN Upscaler (Arch-Agnostic)",
        outputs=[("UPSCALE_MODEL", "UPSCALE_MODEL")],
        widgets_values=["4x-UltraSharp.pth"],
        col=0,
        row=0,
    )
    gan_up = sg.add_node(
        "ImageUpscaleWithModel",
        title="Fast Pixel-Space 4x GAN Pass",
        inputs=[("upscale_model", "UPSCALE_MODEL"), ("image", "IMAGE")],
        outputs=[("IMAGE", "IMAGE")],
        col=1,
        row=0,
    )
    clamp = sg.add_node(
        "ImageResizeKJv2",
        title="Target Resolution Clamp (2K/4K)",
        inputs=[("image", "IMAGE")],
        outputs=[("IMAGE", "IMAGE"), ("width", "INT"), ("height", "INT"), ("mask", "MASK")],
        widgets_values=[2048, 2048, "lanczos", "keep proportion", "0, 0, 0", "center", 16, "cpu"],
        col=2,
        row=0,
    )
    vram_mid = sg.add_node(
        "easy cleanGpuUsed",
        title="Pre-Tiled VRAM Flush",
        inputs=[("anything", "*")],
        outputs=[("output", "*")],
        col=2,
        row=1,
    )
    unpack = sg.add_node(
        "FromBasicPipe",
        title="Unpack Pipe for Tiled Refiner",
        inputs=[("basic_pipe", "BASIC_PIPE")],
        outputs=[
            ("model", "MODEL"),
            ("clip", "CLIP"),
            ("vae", "VAE"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
        ],
        col=1,
        row=1,
    )
    tiled = sg.add_node(
        "UltimateSDUpscale",
        title="Ultimate SD Tiled Refiner (Optional)",
        inputs=[
            ("image", "IMAGE"),
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("vae", "VAE"),
            ("upscale_model", "UPSCALE_MODEL"),
            ("seed", "INT"),
        ],
        outputs=[("IMAGE", "IMAGE")],
        widgets_values=[
            1.5, 42, "fixed", 16, 5.0, "euler", "simple", 0.25, "Linear",
            1024, 1024, 32, 64, "None", 1, 64, 8, 16, True, False, 1,
        ],
        col=3,
        row=0,
        mode=NODE_MODE_BYPASS,
    )

    sg.connect(up_model, 0, gan_up, 0, "UPSCALE_MODEL")
    sg.connect(-10, in_img, gan_up, 1, "IMAGE")
    sg.connect(gan_up, 0, clamp, 0, "IMAGE")
    sg.connect(clamp, 0, vram_mid, 0, "IMAGE")
    sg.connect(-10, in_pipe, unpack, 0, "BASIC_PIPE")
    sg.connect(vram_mid, 0, tiled, 0, "IMAGE")
    sg.connect(unpack, 0, tiled, 1, "MODEL")
    sg.connect(unpack, 3, tiled, 2, "CONDITIONING")
    sg.connect(unpack, 4, tiled, 3, "CONDITIONING")
    sg.connect(unpack, 2, tiled, 4, "VAE")
    sg.connect(up_model, 0, tiled, 5, "UPSCALE_MODEL")
    sg.connect(-10, in_seed, tiled, 6, "INT")
    sg.connect(tiled, 0, -20, out_img, "IMAGE")
    sg.connect(-10, in_pipe, -20, out_pipe, "BASIC_PIPE")

    sg.expose_widget(up_model, "model_name")
    sg.expose_widget(clamp, "width")
    sg.expose_widget(tiled, "denoise")
    return sg


def build_station_s05_film_darkroom() -> SubgraphBuilder:
    sg = SubgraphBuilder("s05_film_darkroom", "S05 · Film, Relight, De-AI Grading & Cutout Darkroom")
    in_img = sg.add_input("image", "IMAGE", "Image")
    out_img = sg.add_output("IMAGE", "IMAGE", "Graded Image")
    out_cut = sg.add_output("MASK", "MASK", "Alpha Matte")

    bal = sg.add_node(
        "LayerColor: ColorBalance",
        title="Color Balance (Shadows/Highlights)",
        inputs=[("image", "IMAGE")],
        outputs=[("image", "IMAGE")],
        widgets_values=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        col=0,
        row=0,
    )
    lvls = sg.add_node(
        "LayerColor: Levels",
        title="Levels & Contrast Curve",
        inputs=[("image", "IMAGE")],
        outputs=[("image", "IMAGE")],
        widgets_values=["RGB", 4, 250, 1.02, 0, 255],
        col=1,
        row=0,
    )
    bc = sg.add_node(
        "LayerColor: Brightness & Contrast",
        title="Micro Exposure Trim",
        inputs=[("image", "IMAGE")],
        outputs=[("image", "IMAGE")],
        widgets_values=[1.0, 1.03, 1.0],
        col=2,
        row=0,
    )
    film = sg.add_node(
        "LayerFilter: FilmPost",
        title="35mm Film Grain + Halation + Vignette",
        inputs=[("image", "IMAGE")],
        outputs=[("image", "IMAGE")],
        widgets_values=[0.35, 1.2, 0.18, 0.25, 0.15, 0.12],
        col=3,
        row=0,
    )
    ca = sg.add_node(
        "LayerFilter: ChromaticAberration",
        title="Subtle Lens Chromatic Aberration",
        inputs=[("image", "IMAGE")],
        outputs=[("image", "IMAGE")],
        widgets_values=[1, 0, -1],
        col=4,
        row=0,
        mode=NODE_MODE_BYPASS,
    )
    sharp = sg.add_node(
        "ImageSharpen",
        title="Final Print Crispness",
        inputs=[("image", "IMAGE")],
        outputs=[("IMAGE", "IMAGE")],
        widgets_values=[1, 0.25, 0.4],
        col=5,
        row=0,
    )
    rmbg = sg.add_node(
        "BiRefNetUltraV2",
        title="BiRefNet Character Alpha Cutout (Optional)",
        inputs=[("image", "IMAGE")],
        outputs=[("image", "IMAGE"), ("mask", "MASK")],
        widgets_values=["BiRefNet-general", "VITMatte", 6, 6, 0.01, 0.99, "cuda", 2.0, True],
        col=5,
        row=1,
        mode=NODE_MODE_BYPASS,
    )

    sg.connect(-10, in_img, bal, 0, "IMAGE")
    sg.connect(bal, 0, lvls, 0, "IMAGE")
    sg.connect(lvls, 0, bc, 0, "IMAGE")
    sg.connect(bc, 0, film, 0, "IMAGE")
    sg.connect(film, 0, ca, 0, "IMAGE")
    sg.connect(ca, 0, sharp, 0, "IMAGE")
    sg.connect(sharp, 0, rmbg, 0, "IMAGE")
    sg.connect(sharp, 0, -20, out_img, "IMAGE")
    sg.connect(rmbg, 1, -20, out_cut, "MASK")

    sg.expose_widget(film, "grain_power")
    sg.expose_widget(sharp, "sharpen_alpha")
    return sg


def build_station_s06_video_tail() -> SubgraphBuilder:
    sg = SubgraphBuilder("s06_video_tail", "S06 · Keyframe-to-Video Tail (Wan 2.2 / LTX-V 2)")
    in_img = sg.add_input("image", "IMAGE", "Keyframe Image")
    in_pos = sg.add_input("positive_prompt", "STRING", "Motion Prompt")
    in_seed = sg.add_input("seed", "INT", "Seed")
    out_frames = sg.add_output("IMAGE", "IMAGE", "Video Frames")

    flush = sg.add_node(
        "easy cleanGpuUsed",
        title="Flush Image Engine VRAM Before Video",
        inputs=[("anything", "*")],
        outputs=[("output", "*")],
        col=0,
        row=0,
    )
    # Branch 0: Wan 2.2 I2V
    wan_unet = sg.add_node(
        "UNETLoader",
        title="Wan 2.2 I2V 14B FP8",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["wan2.2_i2v_14b_fp8.safetensors", "fp8_e4m3fn"],
        col=1,
        row=0,
    )
    wan_clip = sg.add_node(
        "CLIPLoader",
        title="UMT5-XXL (wan)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["umt5_xxl_fp8_e4m3fn_scaled.safetensors", "wan", "default"],
        col=1,
        row=1,
    )
    wan_vae = sg.add_node(
        "VAELoader",
        title="Wan 2.2 Video VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["wan_2.1_vae.safetensors"],
        col=1,
        row=2,
    )
    wan_enc = sg.add_node(
        "CLIPTextEncode",
        title="Wan Motion Prompt",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=2,
        row=1,
    )
    wan_neg = sg.add_node(
        "ConditioningZeroOut",
        title="Wan Neg",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=2,
        row=2,
    )
    wan_lat = sg.add_node(
        "Wan22ImageToVideoLatent",
        title="Wan 2.2 I2V Latent (81f)",
        inputs=[("vae", "VAE"), ("start_image", "IMAGE")],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[832, 480, 81, 1],
        col=2,
        row=0,
    )
    wan_ks = sg.add_node(
        "KSampler",
        title="Wan 2.2 Video Sampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 20, 3.5, "uni_pc", "simple", 1.0],
        col=3,
        row=0,
    )
    wan_dec = sg.add_node(
        "VAEDecodeTiled",
        title="Wan Tiled Video Decode",
        inputs=[("samples", "LATENT"), ("vae", "VAE")],
        outputs=[("IMAGE", "IMAGE")],
        widgets_values=[512, 64, 64, 8],
        col=4,
        row=0,
    )
    # Branch 1: LTX-V 2 Fast Previz
    ltx_unet = sg.add_node(
        "UNETLoader",
        title="LTX-V 2 Fast Previz",
        outputs=[("MODEL", "MODEL")],
        widgets_values=["ltxv_2_13b_fp8.safetensors", "fp8_e4m3fn"],
        col=1,
        row=3,
    )
    ltx_clip = sg.add_node(
        "CLIPLoader",
        title="T5-XXL (ltxv)",
        outputs=[("CLIP", "CLIP")],
        widgets_values=["t5xxl_fp8_e4m3fn.safetensors", "ltxv", "default"],
        col=1,
        row=4,
    )
    ltx_vae = sg.add_node(
        "VAELoader",
        title="LTX-V VAE",
        outputs=[("VAE", "VAE")],
        widgets_values=["ltxv_vae.safetensors"],
        col=2,
        row=4,
    )
    ltx_enc = sg.add_node(
        "CLIPTextEncode",
        title="LTX Motion Prompt",
        inputs=[("clip", "CLIP"), ("text", "STRING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        widgets_values=[""],
        col=2,
        row=3,
    )
    ltx_neg = sg.add_node(
        "ConditioningZeroOut",
        title="LTX Neg",
        inputs=[("conditioning", "CONDITIONING")],
        outputs=[("CONDITIONING", "CONDITIONING")],
        col=3,
        row=4,
    )
    ltx_lat = sg.add_node(
        "EmptyLTXVLatentVideo",
        title="LTX Latent Video",
        outputs=[("LATENT", "LATENT")],
        widgets_values=[768, 512, 97, 1],
        col=2,
        row=5,
    )
    ltx_guide = sg.add_node(
        "LTXVAddGuide",
        title="Bind Keyframe Image to LTX-V 2",
        inputs=[
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("vae", "VAE"),
            ("latent", "LATENT"),
            ("image", "IMAGE"),
        ],
        outputs=[("positive", "CONDITIONING"), ("negative", "CONDITIONING"), ("latent", "LATENT")],
        widgets_values=[0, 1.0],
        col=3,
        row=3,
    )
    ltx_ks = sg.add_node(
        "KSampler",
        title="LTX-V Keyframe Video Sampler",
        inputs=[
            ("model", "MODEL"),
            ("positive", "CONDITIONING"),
            ("negative", "CONDITIONING"),
            ("latent_image", "LATENT"),
            ("seed", "INT"),
        ],
        outputs=[("LATENT", "LATENT")],
        widgets_values=[42, "fixed", 16, 3.0, "euler", "simple", 1.0],
        col=4,
        row=3,
    )
    ltx_dec = sg.add_node(
        "VAEDecode",
        title="LTX Video Decode",
        inputs=[("samples", "LATENT"), ("vae", "VAE")],
        outputs=[("IMAGE", "IMAGE")],
        col=5,
        row=3,
    )
    vid_sw = sg.add_node(
        "easy anythingIndexSwitch",
        title="Video Engine Switch (0=Wan2.2 1=LTX2)",
        inputs=[("value0", "*"), ("value1", "*")],
        outputs=[("value", "*")],
        widgets_values=[0],
        col=6,
        row=1,
    )

    sg.connect(-10, in_img, flush, 0, "IMAGE")
    sg.connect(wan_clip, 0, wan_enc, 0, "CLIP")
    sg.connect(-10, in_pos, wan_enc, 1, "STRING")
    sg.connect(wan_enc, 0, wan_neg, 0, "CONDITIONING")
    sg.connect(wan_vae, 0, wan_lat, 0, "VAE")
    sg.connect(flush, 0, wan_lat, 1, "IMAGE")
    sg.connect(wan_unet, 0, wan_ks, 0, "MODEL")
    sg.connect(wan_enc, 0, wan_ks, 1, "CONDITIONING")
    sg.connect(wan_neg, 0, wan_ks, 2, "CONDITIONING")
    sg.connect(wan_lat, 0, wan_ks, 3, "LATENT")
    sg.connect(-10, in_seed, wan_ks, 4, "INT")
    sg.connect(wan_ks, 0, wan_dec, 0, "LATENT")
    sg.connect(wan_vae, 0, wan_dec, 1, "VAE")

    sg.connect(ltx_clip, 0, ltx_enc, 0, "CLIP")
    sg.connect(-10, in_pos, ltx_enc, 1, "STRING")
    sg.connect(ltx_enc, 0, ltx_neg, 0, "CONDITIONING")
    sg.connect(ltx_enc, 0, ltx_guide, 0, "CONDITIONING")
    sg.connect(ltx_neg, 0, ltx_guide, 1, "CONDITIONING")
    sg.connect(ltx_vae, 0, ltx_guide, 2, "VAE")
    sg.connect(ltx_lat, 0, ltx_guide, 3, "LATENT")
    sg.connect(flush, 0, ltx_guide, 4, "IMAGE")
    sg.connect(ltx_unet, 0, ltx_ks, 0, "MODEL")
    sg.connect(ltx_guide, 0, ltx_ks, 1, "CONDITIONING")
    sg.connect(ltx_guide, 1, ltx_ks, 2, "CONDITIONING")
    sg.connect(ltx_guide, 2, ltx_ks, 3, "LATENT")
    sg.connect(-10, in_seed, ltx_ks, 4, "INT")
    sg.connect(ltx_ks, 0, ltx_dec, 0, "LATENT")
    sg.connect(ltx_vae, 0, ltx_dec, 1, "VAE")

    sg.connect(wan_dec, 0, vid_sw, 0, "IMAGE")
    sg.connect(ltx_dec, 0, vid_sw, 1, "IMAGE")
    sg.connect(vid_sw, 0, -20, out_frames, "IMAGE")

    sg.expose_widget(vid_sw, "index")
    sg.expose_widget(wan_unet, "unet_name")
    return sg


# ---------------------------------------------------------------------------
# Root Canvas Assembler (Ubisoft Tactical HUD + Anti-Lag Architecture)
# ---------------------------------------------------------------------------


@dataclass
class RootBuilder:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    links: list[list[Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    subgraphs: list[dict[str, Any]] = field(default_factory=list)
    reroutes: list[dict[str, Any]] = field(default_factory=list)
    link_extensions: list[dict[str, Any]] = field(default_factory=list)
    _next_node_id: int = 1
    _next_link_id: int = 1
    _next_reroute_id: int = 1

    def register_subgraph(self, sg: SubgraphBuilder) -> dict[str, Any]:
        defn = sg.build_definition()
        self.subgraphs.append(defn)
        return defn

    def add_node(
        self,
        class_type: str,
        *,
        title: str,
        pos: tuple[int, int],
        size: tuple[int, int],
        inputs: list[tuple[str, str]] | None = None,
        outputs: list[tuple[str, str]] | None = None,
        widgets_values: list[Any] | dict[str, Any] | None = None,
        mode: int = NODE_MODE_ALWAYS,
        properties: dict[str, Any] | None = None,
        color: str | None = None,
        bgcolor: str | None = None,
    ) -> int:
        nid = self._next_node_id
        self._next_node_id += 1
        raw: dict[str, Any] = {
            "id": nid,
            "type": class_type,
            "pos": [pos[0], pos[1]],
            "size": [size[0], size[1]],
            "flags": {},
            "order": nid - 1,
            "mode": mode,
            "title": title,
            "inputs": [{"name": n, "type": t, "link": None} for n, t in (inputs or [])],
            "outputs": [{"name": n, "type": t, "links": []} for n, t in (outputs or [])],
            "properties": {"Node name for S&R": class_type, **(properties or {})},
            "widgets_values": widgets_values if widgets_values is not None else [],
        }
        if color:
            raw["color"] = color
        if bgcolor:
            raw["bgcolor"] = bgcolor
        self.nodes.append(raw)
        return nid

    def add_subgraph_instance(
        self,
        sg: SubgraphBuilder,
        *,
        title: str,
        pos: tuple[int, int],
        size: tuple[int, int],
        mode: int = NODE_MODE_ALWAYS,
        color: str | None = None,
        bgcolor: str | None = None,
    ) -> int:
        self.register_subgraph(sg)
        nid = self._next_node_id
        self._next_node_id += 1
        raw: dict[str, Any] = {
            "id": nid,
            "type": sg.subgraph_id,
            "pos": [pos[0], pos[1]],
            "size": [size[0], size[1]],
            "flags": {},
            "order": nid - 1,
            "mode": mode,
            "title": title,
            "inputs": [{"name": n, "type": t, "link": None} for n, t, _ in sg.inputs_spec],
            "outputs": [{"name": n, "type": t, "links": []} for n, t, _ in sg.outputs_spec],
            "properties": {
                "proxyWidgets": list(sg.proxy_widgets),
                "omnistudio_internal_nodes": len(sg.nodes),
            },
            "widgets_values": list(sg.proxy_defaults),
        }
        if color:
            raw["color"] = color
        if bgcolor:
            raw["bgcolor"] = bgcolor
        self.nodes.append(raw)
        return nid

    def add_group(self, title: str, bounding: tuple[int, int, int, int], color: str, font_size: int = 22) -> None:
        self.groups.append(
            {
                "id": len(self.groups) + 1,
                "title": title,
                "bounding": [bounding[0], bounding[1], bounding[2], bounding[3]],
                "color": color,
                "font_size": font_size,
                "flags": {},
            }
        )

    def _find_node(self, nid: int) -> dict[str, Any]:
        for n in self.nodes:
            if n["id"] == nid:
                return n
        raise KeyError(f"Root: unknown node {nid}")

    def connect(
        self,
        origin_id: int,
        origin_slot: int,
        target_id: int,
        target_slot: int,
        slot_type: str,
        *,
        waypoints: list[tuple[int, int]] | None = None,
    ) -> int:
        lid = self._next_link_id
        self._next_link_id += 1
        self.links.append([lid, origin_id, origin_slot, target_id, target_slot, slot_type])
        src = self._find_node(origin_id)
        dst = self._find_node(target_id)
        src["outputs"][origin_slot]["links"].append(lid)
        dst["inputs"][target_slot]["link"] = lid

        if waypoints:
            parent_rid: int | None = None
            for wx, wy in waypoints:
                rid = self._next_reroute_id
                self._next_reroute_id += 1
                entry: dict[str, Any] = {"id": rid, "pos": [wx, wy], "linkIds": [lid]}
                if parent_rid is not None:
                    entry["parentId"] = parent_rid
                self.reroutes.append(entry)
                parent_rid = rid
            self.link_extensions.append({"id": lid, "parentId": parent_rid})
        return lid

    def to_document(self) -> dict[str, Any]:
        return {
            "id": stable_uuid("root:omni-ubisoft-workbench-v1"),
            "revision": 0,
            "last_node_id": self._next_node_id - 1,
            "last_link_id": self._next_link_id - 1,
            "nodes": self.nodes,
            "links": self.links,
            "groups": self.groups,
            "config": {},
            "extra": {
                "ds": {"scale": 0.42, "offset": [80, 120]},
                "frontendVersion": "1.59.1",
                "reroutes": self.reroutes,
                "linkExtensions": self.link_extensions,
                "omnistudio": {
                    "name": "OmniStudio Ubisoft All-in-One Super Workbench",
                    "version": "1.0.0",
                    "anti_lag_architecture": [
                        "1-level-flat-native-subgraphs",
                        "zero-use-everywhere-broadcast",
                        "radio-fast-groups-muter-stripping",
                        "self-contained-engine-capsules-pixel-bridge",
                        "single-centralized-preview-tower",
                        "explicit-vram-flush-checkpoint",
                    ],
                },
            },
            "definitions": {"subgraphs": self.subgraphs},
            "version": 0.4,
        }


CUSTOM_NODE_MANIFEST: list[dict[str, Any]] = [
    {
        "pack": "rgthree-comfy",
        "repo": "https://github.com/rgthree/rgthree-comfy",
        "role": "Radio Fast Groups Muter/Bypasser, Any Switch, Power Lora Loader, Centralized Image Comparer",
        "anti_lag_role": "Strips 17 muted engines at graphToPrompt(); replaces scattered previews with 1 comparer",
    },
    {
        "pack": "ComfyUI-Easy-Use",
        "repo": "https://github.com/yolain/ComfyUI-Easy-Use",
        "role": "easy cleanGpuUsed VRAM Flush Gate, easy anythingIndexSwitch (lazy), wildcards, promptConcat",
        "anti_lag_role": "Forces GPU weight eviction between heavy DiT engines and Detailer/Upscaler/Video",
    },
    {
        "pack": "ComfyUI-KJNodes",
        "repo": "https://github.com/kijai/ComfyUI-KJNodes",
        "role": "Aspect-safe ImageResizeKJv2 and modern layout helpers",
        "anti_lag_role": "Replaces legacy multi-node resize chains",
    },
    {
        "pack": "ComfyUI-Impact-Pack",
        "repo": "https://github.com/ltdrdata/ComfyUI-Impact-Pack",
        "role": "ToBasicPipe/FromBasicPipe, FaceDetailer, DetailerForEach, BboxDetectorSEGS, UltralyticsDetectorProvider",
        "anti_lag_role": "Bundles 5 engine streams into 1 BASIC_PIPE wire (-80% cross-canvas link spline math)",
    },
    {
        "pack": "ComfyUI-Lora-Manager",
        "repo": "https://github.com/willmiao/ComfyUI-Lora-Manager",
        "role": "Lora Loader (LoraManager), TriggerWord Toggle, Civitai-metadata Save Image (LoraManager)",
        "anti_lag_role": "Zero manual trigger copy-paste; clean recipe metadata on export",
    },
    {
        "pack": "comfyui_controlnet_aux",
        "repo": "https://github.com/Fannovel16/comfyui_controlnet_aux",
        "role": "AIO_Preprocessor, DWPreprocessor, DepthAnythingV2Preprocessor",
        "anti_lag_role": "Isolated inside S02 Subgraph; bypassed when not using structure control",
    },
    {
        "pack": "ComfyUI_IPAdapter_plus",
        "repo": "https://github.com/cubiq/ComfyUI_IPAdapter_plus",
        "role": "IPAdapterAdvanced style & identity transfer",
        "anti_lag_role": "Scoped cleanly inside SDXL capsule; never leaks into incompatible DiT engines",
    },
    {
        "pack": "ComfyUI_UltimateSDUpscale",
        "repo": "https://github.com/ssitu/ComfyUI_UltimateSDUpscale",
        "role": "Tiled 2nd-pass diffusion upscaler inside S04",
        "anti_lag_role": "Bypassable by default so fast 4x GAN runs immediately",
    },
    {
        "pack": "ComfyUI-Detail-Daemon",
        "repo": "https://github.com/Jonseed/ComfyUI-Detail-Daemon",
        "role": "DetailDaemonSamplerNode micro-texture injection on SDXL & Flux",
        "anti_lag_role": "Zero extra sampling passes",
    },
    {
        "pack": "ComfyUI-TeaCache",
        "repo": "https://github.com/welltop-cn/ComfyUI-TeaCache",
        "role": "Step-skip diffusion acceleration for Flux, Anima, HiDream",
        "anti_lag_role": "1.5x-2.2x faster DiT inference",
    },
    {
        "pack": "ComfyUI_LayerStyle",
        "repo": "https://github.com/chflame163/ComfyUI_LayerStyle",
        "role": "ColorBalance, Levels, Brightness & Contrast, FilmPost 35mm Grain/Halation, ChromaticAberration, BiRefNetUltraV2",
        "anti_lag_role": "All color-grading filters encapsulated inside S05 Subgraph",
    },
    {
        "pack": "ComfyUI-Florence2",
        "repo": "https://github.com/kijai/ComfyUI-Florence2",
        "role": "VLM reverse-image-to-prompt captioning inside S01",
        "anti_lag_role": "Bypassed by default until artist toggles VLM reverse-captioning ON",
    },
    {
        "pack": "ComfyUI-GGUF",
        "repo": "https://github.com/city96/ComfyUI-GGUF",
        "role": "UnetLoaderGGUF for Q4/Q6/Q8 Flux.1 & Flux.2 Klein on 8-16GB cards",
        "anti_lag_role": "Prevents RAM swap thrashing on consumer GPUs",
    },
    {
        "pack": "ComfyUI-Crystools",
        "repo": "https://github.com/crystian/ComfyUI-Crystools",
        "role": "Get resolution [Crystools] + live GPU/VRAM telemetry bar",
        "anti_lag_role": "Real-time bottleneck diagnostics",
    },
    {
        "pack": "ComfyUI-Prompt-Assistant",
        "repo": "https://github.com/yawiii/ComfyUI-Prompt-Assistant",
        "role": "PromptAssistantNode LLM prompt expansion inside S01",
        "anti_lag_role": "Encapsulated inside S01 with optional bypass",
    },
]


def build_workbench() -> tuple[dict[str, Any], dict[str, Any]]:
    root = RootBuilder()

    # =========================================================================
    # ZONE 0: COMMAND COCKPIT (Far Left, X = 0..560)
    # =========================================================================
    root.add_group("00 · COMMAND COCKPIT (1-Click Controls & Anti-Lag HUD)", (0, 0, 580, 1740), PALETTE["cockpit"], 24)

    n_engine_radio = root.add_node(
        "Fast Groups Muter (rgthree)",
        title="⚡ ENGINE RADIO SWITCH (Click 1 of 18)",
        pos=(30, 60),
        size=(520, 440),
        properties={
            "matchColors": "",
            "matchTitle": "^⚡",
            "showNav": True,
            "sort": "alphanumeric",
            "customSortAlphabet": "",
            "toggleRestriction": "max one",
        },
        color="#1b3a57",
        bgcolor=PALETTE["node_bg"],
    )
    n_station_matrix = root.add_node(
        "Fast Groups Bypasser (rgthree)",
        title="🛠 UBISOFT STATION MATRIX (Toggle Modules)",
        pos=(30, 540),
        size=(520, 250),
        properties={
            "matchColors": "",
            "matchTitle": "^🛠",
            "showNav": True,
            "sort": "alphanumeric",
            "customSortAlphabet": "",
            "toggleRestriction": "default",
        },
        color="#1d4d44",
        bgcolor=PALETTE["node_bg"],
    )
    n_pos = root.add_node(
        "PrimitiveStringMultiline",
        title="Positive Prompt (Global)",
        pos=(30, 830),
        size=(520, 160),
        outputs=[("STRING", "STRING")],
        widgets_values=[
            "cinematic anime illustration, warm afternoon sunbeam through tall studio windows, "
            "painterly gouache brushwork, crisp linework, atmospheric depth, rich shadow tones"
        ],
        color="#234f3c",
        bgcolor=PALETTE["node_bg"],
    )
    n_neg = root.add_node(
        "PrimitiveStringMultiline",
        title="Negative Prompt (Global)",
        pos=(30, 1030),
        size=(520, 110),
        outputs=[("STRING", "STRING")],
        widgets_values=["worst quality, lowres, blurry, deformed anatomy, extra fingers, watermark, text"],
        color="#5c2828",
        bgcolor=PALETTE["node_bg"],
    )
    n_width = root.add_node(
        "PrimitiveInt",
        title="Canvas Width",
        pos=(30, 1180),
        size=(245, 82),
        outputs=[("INT", "INT")],
        widgets_values=[1024, "fixed"],
        color="#2c445c",
        bgcolor=PALETTE["node_bg"],
    )
    n_height = root.add_node(
        "PrimitiveInt",
        title="Canvas Height",
        pos=(305, 1180),
        size=(245, 82),
        outputs=[("INT", "INT")],
        widgets_values=[1280, "fixed"],
        color="#2c445c",
        bgcolor=PALETTE["node_bg"],
    )
    n_seed = root.add_node(
        "PrimitiveInt",
        title="Global Master Seed",
        pos=(30, 1300),
        size=(520, 82),
        outputs=[("INT", "INT")],
        widgets_values=[20261125, "randomize"],
        color="#3b3663",
        bgcolor=PALETTE["node_bg"],
    )
    n_guide = root.add_node(
        "MarkdownNote",
        title="📖 Quick Start & Anti-Lag Guide (Read First)",
        pos=(30, 1420),
        size=(520, 290),
        widgets_values=[
            "### OmniStudio Ubisoft Super Workbench (v1.0)\n"
            "1. **Switch Models in 1 Click**: Use `⚡ ENGINE RADIO SWITCH` above — picking any of the **18 architectures** auto-mutes the other 17 (zero missing-model errors, zero CFG/VAE conflicts).\n"
            "2. **Toggle Post-FX**: Use `🛠 UBISOFT STATION MATRIX` to enable Prompt/VLM Lab, ControlNet, Face/Eye/Hand SEGS, 4x HiRes, Film Darkroom, Video Tail, or Low-VRAM Auto-Flush.\n"
            "3. **Zero Canvas Lag**: All 380+ nodes are sealed inside **1-level flat Subgraphs** (no deep nesting, zero `Use Everywhere`, 1 centralized comparer). Double-click any station to inspect internals, or switch ComfyUI to **App Mode** for zero-node form UI."
        ],
        color="#303846",
        bgcolor="#1b2028",
    )
    _ = (n_engine_radio, n_station_matrix)

    # =========================================================================
    # ZONE 1: PRE-PROCESSING STATIONS (X = 660..1120)
    # =========================================================================
    s01 = build_station_s01_prompt_vlm()
    root.add_group("🛠 S01 · Prompt, Wildcards & VLM Lab", (660, 120, 440, 280), PALETTE["prompt"], 20)
    n_s01 = root.add_subgraph_instance(
        s01,
        title=f"S01 · Prompt & VLM Lab [{len(s01.nodes)} nodes]",
        pos=(690, 190),
        size=(380, 180),
        mode=NODE_MODE_BYPASS,  # Bypassed by default for instant clean start
        color=PALETTE["node_hdr_station"],
        bgcolor=PALETTE["node_bg"],
    )

    s02 = build_station_s02_controlnet_armory()
    root.add_group("🛠 S02 · ControlNet & IPAdapter Armory", (660, 460, 440, 280), PALETTE["control"], 20)
    n_s02 = root.add_subgraph_instance(
        s02,
        title=f"S02 · ControlNet & Ref Armory [{len(s02.nodes)} nodes]",
        pos=(690, 530),
        size=(380, 180),
        mode=NODE_MODE_BYPASS,
        color="#2a3e66",
        bgcolor=PALETTE["node_bg"],
    )

    # Wire Cockpit -> S01 & S02 (through clean vertical trunk at X=620)
    root.connect(n_pos, 0, n_s01, 0, "STRING", waypoints=[(610, 890), (610, 240)])
    root.connect(n_seed, 0, n_s01, 1, "INT", waypoints=[(625, 1340), (625, 270)])
    root.connect(n_width, 0, n_s02, 0, "INT", waypoints=[(615, 1220), (615, 580)])
    root.connect(n_height, 0, n_s02, 1, "INT", waypoints=[(630, 1220), (630, 610)])

    # =========================================================================
    # ZONE 2: 18 ALL-IN-ONE MODEL ENGINE CAPSULES (4 Color-Coded Banks, X = 1220..3080)
    # =========================================================================
    banks: list[tuple[str, str, list[tuple[str, SubgraphBuilder, bool]]]] = [
        (
            "BANK A · ANIME & SD CLASSIC",
            PALETTE["bank_a"],
            [
                ("⚡ E01 · SDXL / Illustrious", build_engine_sdxl_illustrious(), True),
                ("⚡ E02 · NoobAI V-Pred", build_engine_noobai_vpred(), False),
                ("⚡ E03 · Pony V6 XL", build_engine_pony_v6(), False),
                ("⚡ E04 · Anima 2.9B / 3.8B", build_engine_anima_dit(), False),
                ("⚡ E05 · SD 1.5 / LCM", build_engine_sd15_lcm(), False),
            ],
        ),
        (
            "BANK B · FLUX & FLOW FLAGSHIPS",
            PALETTE["bank_b"],
            [
                ("⚡ E06 · Flux.1 Dev / Schnell", build_engine_flux1_dev(), False),
                ("⚡ E07 · Flux.1 Kontext Edit", build_engine_flux1_kontext(), True),
                ("⚡ E08 · Flux.2 Klein / Dev", build_engine_flux2_klein(), False),
                ("⚡ E09 · Flux.3 Layout + KV", build_engine_flux3_kv(), False),
                ("⚡ E10 · Chroma Uncensored", build_engine_chroma(), False),
            ],
        ),
        (
            "BANK C · FRONTIER ASIAN & MEGA DiT",
            PALETTE["bank_c"],
            [
                ("⚡ E11 · MOSS-Image INT8/DMD8", build_engine_moss_image(), False),
                ("⚡ E12 · Qwen-Image 2.1 CJK", build_engine_qwen21(), False),
                ("⚡ E13 · Krea-2 Photoreal", build_engine_krea2(), False),
                ("⚡ E14 · MiniMax-H3 SplitSigma", build_engine_minimax_h3(), False),
                ("⚡ E15 · SD 3.5 Large / Med", build_engine_sd35(), False),
            ],
        ),
        (
            "BANK D · QUAD-CLIP & NICHE VAULT (16+ ARCHES)",
            PALETTE["bank_d"],
            [
                ("⚡ E16 · HiDream-I1 / O1", build_engine_hidream(), False),
                ("⚡ E17 · Lumina-2 / Z-Image", build_engine_lumina2_zimage(), False),
                ("⚡ E18 · Niche 14-Arch Vault", build_engine_niche_universal(), False),
            ],
        ),
    ]

    bank_engine_ids: list[list[int]] = []
    engine_x0 = 1240
    engine_dx = 380
    bank_y0 = 60
    bank_dy = 430

    for b_idx, (_bank_label, bank_color, engines) in enumerate(banks):
        by = bank_y0 + b_idx * bank_dy
        ids_in_bank: list[int] = []
        for e_idx, (etitle, sg, needs_ref) in enumerate(engines):
            ex = engine_x0 + e_idx * engine_dx
            # Only E01 active by default; all other 17 muted (mode=2) so zero missing-model errors on import!
            is_default_active = b_idx == 0 and e_idx == 0
            mode = NODE_MODE_ALWAYS if is_default_active else NODE_MODE_NEVER
            hdr_color = PALETTE["node_hdr_active"] if is_default_active else PALETTE["node_hdr_muted"]

            # Dedicated titled group per engine so Fast Groups Muter radio switch targets each individually
            root.add_group(etitle, (ex - 20, by, 350, 340), bank_color, 18)
            nid = root.add_subgraph_instance(
                sg,
                title=f"{sg.name} [{len(sg.nodes)} nodes]",
                pos=(ex, by + 64),
                size=(310, 250),
                mode=mode,
                color=hdr_color,
                bgcolor=PALETTE["node_bg"],
            )
            ids_in_bank.append(nid)

            # Route global inputs through clean horizontal bus corridor above each bank row
            corridor_y = by - 16
            root.connect(n_s01, 0, nid, 0, "STRING", waypoints=[(1160, 240), (1160, corridor_y), (ex - 10, corridor_y)])
            root.connect(n_neg, 0, nid, 1, "STRING", waypoints=[(1170, 1085), (1170, corridor_y + 4), (ex - 10, corridor_y + 4)])
            root.connect(n_width, 0, nid, 2, "INT", waypoints=[(1180, 1220), (1180, corridor_y + 8), (ex - 10, corridor_y + 8)])
            root.connect(n_height, 0, nid, 3, "INT", waypoints=[(1190, 1220), (1190, corridor_y + 12), (ex - 10, corridor_y + 12)])
            root.connect(n_seed, 0, nid, 4, "INT", waypoints=[(1200, 1340), (1200, corridor_y + 16), (ex - 10, corridor_y + 16)])
            if needs_ref:
                root.connect(n_s02, 0, nid, 5, "IMAGE", waypoints=[(1145, 580), (1145, by + 230)])
                root.connect(n_s02, 1, nid, 6, "CONTROL_NET", waypoints=[(1150, 610), (1150, by + 255)])
                root.connect(n_s02, 2, nid, 7, "IMAGE", waypoints=[(1155, 640), (1155, by + 280)])

        bank_engine_ids.append(ids_in_bank)

    # =========================================================================
    # ZONE 3: PIXEL BRIDGE & VRAM CHECKPOINT GATE (X = 3200..3960)
    # =========================================================================
    root.add_group("03 · PIXEL BRIDGE (4-Bank Lazy Any Switch Bus)", (3200, 40, 740, 1680), PALETTE["bridge"], 22)

    bank_img_switches: list[int] = []
    bank_pipe_switches: list[int] = []
    for b_idx, ids_in_bank in enumerate(bank_engine_ids):
        by = bank_y0 + b_idx * bank_dy + 40
        slots_img = [(f"any_0{i + 1}", "*") for i in range(5)]
        slots_pipe = [(f"any_0{i + 1}", "*") for i in range(5)]

        sw_img = root.add_node(
            "Any Switch (rgthree)",
            title=f"Bank {chr(65 + b_idx)} · Pixel Bus Switch",
            pos=(3240, by),
            size=(280, 150),
            inputs=slots_img,
            outputs=[("*", "*")],
            color=PALETTE["node_hdr_bridge"],
            bgcolor=PALETTE["node_bg"],
        )
        sw_pipe = root.add_node(
            "Any Switch (rgthree)",
            title=f"Bank {chr(65 + b_idx)} · Pipe Bus Switch",
            pos=(3240, by + 180),
            size=(280, 150),
            inputs=slots_pipe,
            outputs=[("*", "*")],
            color=PALETTE["node_hdr_bridge"],
            bgcolor=PALETTE["node_bg"],
        )
        for slot_i, eid in enumerate(ids_in_bank):
            root.connect(eid, 0, sw_img, slot_i, "IMAGE")
            root.connect(eid, 1, sw_pipe, slot_i, "BASIC_PIPE")
        bank_img_switches.append(sw_img)
        bank_pipe_switches.append(sw_pipe)

    master_img_sw = root.add_node(
        "Any Switch (rgthree)",
        title="MASTER PIXEL BRIDGE (Active Engine -> Image)",
        pos=(3600, 520),
        size=(310, 170),
        inputs=[(f"any_0{i + 1}", "*") for i in range(5)],
        outputs=[("*", "*")],
        color="#25597a",
        bgcolor=PALETTE["node_bg"],
    )
    master_pipe_sw = root.add_node(
        "Any Switch (rgthree)",
        title="MASTER PIPE BRIDGE (Active Engine -> Pipe)",
        pos=(3600, 760),
        size=(310, 170),
        inputs=[(f"any_0{i + 1}", "*") for i in range(5)],
        outputs=[("*", "*")],
        color="#25597a",
        bgcolor=PALETTE["node_bg"],
    )
    for b_idx in range(len(bank_img_switches)):
        root.connect(bank_img_switches[b_idx], 0, master_img_sw, b_idx, "IMAGE")
        root.connect(bank_pipe_switches[b_idx], 0, master_pipe_sw, b_idx, "BASIC_PIPE")

    # Toggleable Low-VRAM Auto-Flush Gate (placed AFTER model-sharing S03/S04, BEFORE Darkroom/BiRefNet/Video)
    root.add_group("🛠 S07 · Low-VRAM Auto-Flush Gate (Post-Detail -> FX/Video)", (4000, 840, 340, 260), PALETTE["vram"], 17)
    n_vram_flush = root.add_node(
        "easy cleanGpuUsed",
        title="VRAM Flush Checkpoint (Model Stage -> FX/Video)",
        pos=(4030, 915),
        size=(280, 120),
        inputs=[("anything", "*")],
        outputs=[("output", "*")],
        mode=NODE_MODE_ALWAYS,
        color=PALETTE["node_hdr_vram"],
        bgcolor=PALETTE["node_bg"],
    )

    # =========================================================================
    # ZONE 4: UBISOFT POST-PRODUCTION FACTORY (4 Modular Subgraphs, X = 4420..5260)
    # =========================================================================
    s03 = build_station_s03_anatomy_segs()
    root.add_group("🛠 S03 · Anatomy SEGS Surgical Lab", (4420, 120, 400, 300), PALETTE["post_segs"], 19)
    n_s03 = root.add_subgraph_instance(
        s03,
        title=f"S03 · Face/Eye/Hand/Foot SEGS [{len(s03.nodes)} nodes]",
        pos=(4450, 190),
        size=(340, 200),
        mode=NODE_MODE_BYPASS,
        color="#6e2c44",
        bgcolor=PALETTE["node_bg"],
    )

    s04 = build_station_s04_hires_upscale()
    root.add_group("🛠 S04 · 4x GAN & Tiled HiRes Forge", (4420, 480, 400, 300), PALETTE["post_upscale"], 19)
    n_s04 = root.add_subgraph_instance(
        s04,
        title=f"S04 · 4x GAN + Tiled HiRes [{len(s04.nodes)} nodes]",
        pos=(4450, 550),
        size=(340, 200),
        mode=NODE_MODE_BYPASS,
        color="#473873",
        bgcolor=PALETTE["node_bg"],
    )

    s05 = build_station_s05_film_darkroom()
    root.add_group("🛠 S05 · Film, Relight & De-AI Darkroom", (4420, 840, 400, 300), PALETTE["post_darkroom"], 19)
    n_s05 = root.add_subgraph_instance(
        s05,
        title=f"S05 · Film Grain / Color / Cutout [{len(s05.nodes)} nodes]",
        pos=(4450, 910),
        size=(340, 200),
        mode=NODE_MODE_BYPASS,
        color="#664823",
        bgcolor=PALETTE["node_bg"],
    )

    s06 = build_station_s06_video_tail()
    root.add_group("🛠 S06 · Motion & Video Tail (Wan 2.2 / LTX-2)", (4420, 1200, 400, 480), PALETTE["post_video"], 19)
    n_s06 = root.add_subgraph_instance(
        s06,
        title=f"S06 · Keyframe -> Video [{len(s06.nodes)} nodes]",
        pos=(4450, 1270),
        size=(340, 190),
        mode=NODE_MODE_BYPASS,  # Bypassed with its SaveImage together via 🛠 S06 Station Matrix
        color="#4a2b61",
        bgcolor=PALETTE["node_bg"],
    )
    n_save_vid = root.add_node(
        "SaveImage",
        title="Save Video Keyframe Sequence (Toggles with S06)",
        pos=(4450, 1500),
        size=(340, 145),
        inputs=[("images", "IMAGE")],
        outputs=[],
        widgets_values=["OmniStudio/video_frames"],
        mode=NODE_MODE_BYPASS,
        color="#4a2b61",
        bgcolor=PALETTE["node_bg"],
    )

    # Wire Post-FX Chain cleanly: S03/S04 reuse hot checkpoint in VRAM, THEN S07 flushes VRAM before Darkroom/BiRefNet/Video
    root.connect(master_img_sw, 0, n_s03, 0, "IMAGE")
    root.connect(master_pipe_sw, 0, n_s03, 1, "BASIC_PIPE")
    root.connect(n_seed, 0, n_s03, 2, "INT", waypoints=[(4380, 1340), (4380, 310)])

    root.connect(n_s03, 0, n_s04, 0, "IMAGE")
    root.connect(n_s03, 1, n_s04, 1, "BASIC_PIPE")
    root.connect(n_seed, 0, n_s04, 2, "INT", waypoints=[(4390, 1340), (4390, 670)])

    root.connect(n_s04, 0, n_vram_flush, 0, "IMAGE", waypoints=[(4365, 620), (4365, 975)])
    root.connect(n_vram_flush, 0, n_s05, 0, "IMAGE")

    root.connect(n_s05, 0, n_s06, 0, "IMAGE")
    root.connect(n_s01, 0, n_s06, 1, "STRING", waypoints=[(4370, 240), (4370, 1350)])
    root.connect(n_seed, 0, n_s06, 2, "INT", waypoints=[(4385, 1340), (4385, 1380)])
    root.connect(n_s06, 0, n_save_vid, 0, "IMAGE")

    # =========================================================================
    # ZONE 5: CENTRALIZED GALLERY, COMPARE & METADATA VAULT (X = 4920..5660)
    # =========================================================================
    root.add_group("05 · GALLERY, BEFORE/AFTER COMPARE & EXPORT VAULT", (4920, 120, 740, 1380), PALETTE["gallery"], 22)

    n_compare = root.add_node(
        "Image Comparer (rgthree)",
        title="SINGLE CENTRALIZED COMPARE (Raw Base vs Final Graded)",
        pos=(4960, 190),
        size=(660, 560),
        inputs=[("image_a", "IMAGE"), ("image_b", "IMAGE")],
        outputs=[],
        color=PALETTE["node_hdr_gallery"],
        bgcolor=PALETTE["node_bg"],
    )
    n_save_img = root.add_node(
        "Save Image (LoraManager)",
        title="Save Master Image (Full Civitai + LoRA Metadata)",
        pos=(4960, 790),
        size=(400, 260),
        inputs=[("images", "IMAGE")],
        outputs=[("images", "IMAGE")],
        widgets_values=["OmniStudio/master", "png", False, 100, True, True, True, False],
        color=PALETTE["node_hdr_gallery"],
        bgcolor=PALETTE["node_bg"],
    )
    n_res = root.add_node(
        "Get resolution [Crystools]",
        title="Output Resolution Telemetry",
        pos=(5400, 790),
        size=(220, 110),
        inputs=[("image", "IMAGE")],
        outputs=[("width", "INT"), ("height", "INT")],
        color="#2b4a5e",
        bgcolor=PALETTE["node_bg"],
    )
    n_manifest = root.add_node(
        "MarkdownNote",
        title="📦 Anti-Lag Telemetry & Custom Node Packs",
        pos=(4960, 1100),
        size=(660, 220),
        widgets_values=[
            "- **Zero `Use Everywhere` nodes** (eliminates O(N^2) wildcard scan lag)\n"
            "- **1-Level Flat Native Subgraphs** (no nested subgraph double-configure slowdown)\n"
            "- **Only 1 Active Preview/Comparer on Root** (prevents WebGL texture memory bloat)\n"
            "- **15 Curated Packs**: rgthree, Easy-Use, KJNodes, Impact-Pack, Lora-Manager, ControlNet-Aux, IPAdapter-Plus, UltimateSDUpscale, Detail-Daemon, TeaCache, LayerStyle, Florence2, GGUF, Crystools, Prompt-Assistant."
        ],
        color="#233642",
        bgcolor="#1a2229",
    )
    _ = n_manifest

    root.connect(master_img_sw, 0, n_compare, 0, "IMAGE", waypoints=[(4880, 595), (4880, 260)])
    root.connect(n_s05, 0, n_compare, 1, "IMAGE", waypoints=[(4895, 960), (4895, 290)])
    root.connect(n_s05, 0, n_save_img, 0, "IMAGE")
    root.connect(n_s05, 0, n_res, 0, "IMAGE", waypoints=[(5380, 960), (5380, 845)])

    doc = root.to_document()
    internal_nodes = sum(len(sg["nodes"]) for sg in doc["definitions"]["subgraphs"])
    total_nodes = len(doc["nodes"]) + internal_nodes
    total_links = len(doc["links"]) + sum(len(sg["links"]) for sg in doc["definitions"]["subgraphs"])
    dom_reduction_pct = round((1.0 - len(doc["nodes"]) / total_nodes) * 100, 1)

    # Sync Quick-Start MarkdownNote counts dynamically from actual graph stats (zero drift)
    guide_node = root._find_node(n_guide)
    guide_node["widgets_values"] = [
        "### OmniStudio Ubisoft Super Workbench (v1.0)\n"
        "1. **Switch Models in 1 Click**: Use `⚡ ENGINE RADIO SWITCH` above — picking any of the **18 architectures** auto-mutes the other 17 (zero missing-model errors, zero CFG/VAE conflicts).\n"
        "2. **Toggle Post-FX**: Use `🛠 UBISOFT STATION MATRIX` to enable Prompt/VLM Lab, ControlNet, Face/Eye/Hand SEGS, 4x HiRes, Film Darkroom, Video Tail, or Low-VRAM Auto-Flush.\n"
        f"3. **Zero Canvas Lag**: All **{total_nodes} real nodes** are sealed inside **24 1-level flat Subgraphs**, leaving only **{len(doc['nodes'])} root blocks ({dom_reduction_pct}% DOM reduction)**, zero `Use Everywhere`, and 1 centralized comparer. Double-click any station to inspect internals, or switch ComfyUI to **App Mode** for zero-node form UI."
    ]
    stats = {
        "workflow_name": "OmniStudio Ubisoft All-in-One Super Workbench",
        "version": doc["version"],
        "root_nodes": len(doc["nodes"]),
        "subgraph_count": len(doc["definitions"]["subgraphs"]),
        "engine_capsules": 18,
        "production_stations": 6,
        "internal_nodes": internal_nodes,
        "total_real_nodes": total_nodes,
        "root_links": len(doc["links"]),
        "total_real_links": total_links,
        "root_groups": len(doc["groups"]),
        "root_dom_reduction_pct": dom_reduction_pct,
        "custom_node_packs": len(CUSTOM_NODE_MANIFEST),
        "unique_node_types": len(
            {
                n["type"]
                for n in doc["nodes"]
                if n["type"] not in {s["id"] for s in doc["definitions"]["subgraphs"]}
            }
            | {n["type"] for s in doc["definitions"]["subgraphs"] for n in s["nodes"]}
        ),
        "engines": [
            {
                "id": s["extra"]["omnistudio_capsule"],
                "name": s["name"],
                "internal_nodes": len(s["nodes"]),
                "internal_links": len(s["links"]),
            }
            for s in doc["definitions"]["subgraphs"]
            if s["extra"]["omnistudio_capsule"].startswith("e")
        ],
        "stations": [
            {
                "id": s["extra"]["omnistudio_capsule"],
                "name": s["name"],
                "internal_nodes": len(s["nodes"]),
                "internal_links": len(s["links"]),
            }
            for s in doc["definitions"]["subgraphs"]
            if s["extra"]["omnistudio_capsule"].startswith("s")
        ],
    }
    return doc, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the OmniStudio Ubisoft All-in-One Super Workbench.")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "dist",
        help="Directory to write workflow JSON, manifest, and stats.",
    )
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    doc, stats = build_workbench()
    wf_path = args.out_dir / "omni_ubisoft_workbench.ui.json"
    manifest_path = args.out_dir / "custom_nodes_manifest.json"
    stats_path = args.out_dir / "workbench_stats.json"

    wf_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(CUSTOM_NODE_MANIFEST, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"Built {wf_path.name}: {stats['total_real_nodes']} real nodes "
        f"({stats['root_nodes']} root + {stats['internal_nodes']} across {stats['subgraph_count']} 1-level subgraphs, "
        f"{stats['root_dom_reduction_pct']}% root DOM reduction, {stats['unique_node_types']} unique node types)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
