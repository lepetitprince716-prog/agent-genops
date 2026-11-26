"""Unit tests for ``tools/safetensors_prot_read.py`` and ``tools/comfy_ab_harness.py``."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import comfy_ab_harness  # noqa: E402
import safetensors_prot_read  # noqa: E402


def build_synthetic_safetensors(
    tensors: dict[str, tuple[str, list[int], bytes]],
    metadata: dict[str, str] | None = None,
) -> bytes:
    """Pack a synthetic ``.safetensors`` binary from ``{name: (dtype, shape, raw_bytes)}``."""
    header: dict[str, object] = {}
    if metadata is not None:
        header["__metadata__"] = metadata
    chunks: list[bytes] = []
    offset = 0
    for name, (dtype, shape, payload) in tensors.items():
        end = offset + len(payload)
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, end]}
        chunks.append(payload)
        offset = end
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return struct.pack("<Q", len(header_bytes)) + header_bytes + b"".join(chunks)


def sample_workflow(tag: str) -> dict[str, object]:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": f"model_{tag}.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "test scene", "clip": ["1", 0]}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 1, "steps": 8, "cfg": 1.0, "model": ["1", 0], "positive": ["2", 0]},
        },
    }


@dataclass
class _FakeAliasInfo:
    is_write: bool


@dataclass
class _FakeArgSchema:
    name: str
    alias_info: _FakeAliasInfo | None = None


@dataclass
class _FakeSchema:
    name: str
    is_mutable: bool
    arguments: list[_FakeArgSchema]


class SafetensorsProtReadTests(unittest.TestCase):
    def test_synthetic_header_parse_and_readonly_mmap_immutability(self) -> None:
        w0 = bytes(range(16))
        w1 = b"\x01\x02" * 6
        raw = build_synthetic_safetensors(
            {
                "blocks.0.weight": ("I8", [4, 4], w0),
                "blocks.0.bias": ("BF16", [6], w1),
                "blocks.0.scale": ("F8_E4M3", [4], b"\x38\x38\x38\x38"),
            },
            metadata={"format": "pt", "quant": "int8"},
        )
        expected_sha = hashlib.sha256(raw).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic.safetensors"
            path.write_bytes(raw)

            with safetensors_prot_read.inspect_safetensors(path) as handle:
                self.assertEqual(handle.metadata, {"format": "pt", "quant": "int8"})
                self.assertEqual(set(handle.tensors), {"blocks.0.weight", "blocks.0.bias", "blocks.0.scale"})
                self.assertEqual(handle.tensors["blocks.0.weight"]["shape"], [4, 4])
                self.assertEqual(handle.tensors["blocks.0.weight"]["nbytes"], 16)

                mv = handle.tensor_view("blocks.0.weight")
                self.assertTrue(mv.readonly)
                self.assertEqual(bytes(mv), w0)
                with self.assertRaises(TypeError):
                    mv[0] = 0xFF
                with self.assertRaises(TypeError):
                    handle.mm[8] = 0x41

                checksum = handle.touch_pages(page_size=8)
                self.assertIsInstance(checksum, int)

            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_sha)

    def test_corrupt_headers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "tiny.safetensors"
            small.write_bytes(b"short")
            with self.assertRaisesRegex(ValueError, "too small"):
                safetensors_prot_read.inspect_safetensors(small)

        # Oversized header_len
        bad_len = struct.pack("<Q", 9999) + b"{}"
        with self.assertRaisesRegex(ValueError, "Invalid safetensors header length"):
            safetensors_prot_read.parse_safetensors_header(bad_len)

        # Zero header_len
        zero_len = struct.pack("<Q", 0) + b"{}"
        with self.assertRaisesRegex(ValueError, "Invalid safetensors header length"):
            safetensors_prot_read.parse_safetensors_header(zero_len)

        # Invalid JSON
        bad_json = struct.pack("<Q", 4) + b"{bad"
        with self.assertRaisesRegex(ValueError, "Corrupt safetensors JSON header"):
            safetensors_prot_read.parse_safetensors_header(bad_json)

        # Unsupported dtype
        bad_dtype_hdr = json.dumps(
            {"t": {"dtype": "COMPLEX128", "shape": [1], "data_offsets": [0, 16]}}
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported safetensors dtype"):
            safetensors_prot_read.parse_safetensors_header(
                struct.pack("<Q", len(bad_dtype_hdr)) + bad_dtype_hdr + b"\x00" * 16
            )

        # Negative dimension
        neg_dim_hdr = json.dumps(
            {"t": {"dtype": "I8", "shape": [-2, 4], "data_offsets": [0, 8]}}
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid tensor dimension"):
            safetensors_prot_read.parse_safetensors_header(
                struct.pack("<Q", len(neg_dim_hdr)) + neg_dim_hdr + b"\x00" * 8
            )

        # Out-of-bounds data_offsets
        oob_hdr = json.dumps(
            {"t": {"dtype": "F16", "shape": [4], "data_offsets": [0, 8]}}
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "Out-of-bounds data_offsets"):
            safetensors_prot_read.parse_safetensors_header(
                struct.pack("<Q", len(oob_hdr)) + oob_hdr + b"\x00" * 4
            )

        # Byte-length mismatch
        mismatch_hdr = json.dumps(
            {"t": {"dtype": "F32", "shape": [2, 2], "data_offsets": [0, 8]}}
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "Byte length mismatch"):
            safetensors_prot_read.parse_safetensors_header(
                struct.pack("<Q", len(mismatch_hdr)) + mismatch_hdr + b"\x00" * 16
            )

    def test_proc_maps_and_rss_verifiers(self) -> None:
        status_text = (
            "Name:\tpython3\n"
            "VmRSS:\t   65536 kB\n"
            "RssAnon:\t   12288 kB\n"
            "RssFile:\t   53248 kB\n"
            "RssShmem:\t       0 kB\n"
        )
        rss = safetensors_prot_read.parse_proc_status_rss(status_text)
        self.assertEqual(rss["RssAnon"], 12288 * 1024)
        self.assertEqual(rss["RssFile"], 53248 * 1024)
        self.assertEqual(rss["VmRSS"], 65536 * 1024)

        target = "/models/checkpoint.safetensors"
        safe_maps = (
            f"ffff80000000-ffff84000000 r--s 00000000 08:01 42  {target}\n"
            "ffff84000000-ffff84010000 rw-p 00000000 00:00 0   [heap]\n"
        )
        res_ok = safetensors_prot_read.verify_proc_maps_prot_read(safe_maps, target)
        self.assertTrue(res_ok["found"])
        self.assertTrue(res_ok["all_prot_read_shared"])
        self.assertEqual(res_ok["perms"], ["r--s"])

        # Writable MAP_SHARED (silent disk corruption hazard) must fail
        writable_shared = f"ffff80000000-ffff84000000 rw-s 00000000 08:01 42  {target}\n"
        res_rw = safetensors_prot_read.verify_proc_maps_prot_read(writable_shared, target)
        self.assertFalse(res_rw["all_prot_read_shared"])

        # Private MAP_PRIVATE (copy-on-write RssAnon hazard on UMA) must fail
        private_cow = f"ffff80000000-ffff84000000 r--p 00000000 08:01 42  {target}\n"
        res_priv = safetensors_prot_read.verify_proc_maps_prot_read(private_cow, target)
        self.assertFalse(res_priv["all_prot_read_shared"])

    def test_write_guard_schema_and_torch_contract(self) -> None:
        sentinel = object()
        mut_schema = _FakeSchema(
            name="aten::add_",
            is_mutable=True,
            arguments=[
                _FakeArgSchema("self", _FakeAliasInfo(is_write=True)),
                _FakeArgSchema("other", _FakeAliasInfo(is_write=False)),
            ],
        )
        with self.assertRaises(safetensors_prot_read.ProtReadWriteError):
            safetensors_prot_read.check_mutable_schema_targets(
                mut_schema, (sentinel, 1), {}, lambda x: x is sentinel
            )

        out_schema = _FakeSchema(
            name="aten::add.out",
            is_mutable=True,
            arguments=[
                _FakeArgSchema("self", _FakeAliasInfo(is_write=False)),
                _FakeArgSchema("other", _FakeAliasInfo(is_write=False)),
                _FakeArgSchema("out", _FakeAliasInfo(is_write=True)),
            ],
        )
        with self.assertRaises(safetensors_prot_read.ProtReadWriteError):
            safetensors_prot_read.check_mutable_schema_targets(
                out_schema, (1, 2), {"out": sentinel}, lambda x: x is sentinel
            )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weights.safetensors"
            payload = struct.pack("<4f", 1.0, 2.0, 3.0, 4.0)
            path.write_bytes(build_synthetic_safetensors({"w": ("F32", [2, 2], payload)}))
            expected_sha = hashlib.sha256(path.read_bytes()).hexdigest()

            if safetensors_prot_read.torch is None:
                self.assertIsNone(safetensors_prot_read.ReadOnlyMmapTensor)
                with self.assertRaisesRegex(RuntimeError, "torch is not installed"):
                    safetensors_prot_read.load_safetensors_prot_read(path)
            else:
                sd = safetensors_prot_read.load_safetensors_prot_read(path)
                w = sd["w"]
                self.assertIsInstance(w, safetensors_prot_read.ReadOnlyMmapTensor)
                with self.assertRaises(safetensors_prot_read.ProtReadWriteError):
                    w.add_(1.0)
                with self.assertRaises(safetensors_prot_read.ProtReadWriteError):
                    w.view(-1)[0] = 9.0
                cloned = safetensors_prot_read.copy_on_patch(w)
                self.assertNotIsInstance(cloned, safetensors_prot_read.ReadOnlyMmapTensor)
                cloned.add_(10.0)
                self.assertAlmostEqual(float(w[0, 0]), 1.0)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected_sha)

            proc = subprocess.run(
                [sys.executable, "-B", str(TOOLS_DIR / "safetensors_prot_read.py"), "--touch", "--json", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report["tensor_count"], 1)
            self.assertEqual(report["payload_bytes"], 16)


class ComfyAbHarnessTests(unittest.TestCase):
    def test_aba_and_abba_interleaving_schedules(self) -> None:
        aba = comfy_ab_harness.build_interleaved_schedule(
            ["A", "B"], [1001, 1002, 1003], order="aba", warmup=1, a2_seed_offset=100000
        )
        self.assertEqual([r["slot"] for r in aba[:2]], ["A_warmup_1", "B_warmup_1"])
        self.assertTrue(all(r["warmup"] for r in aba[:2]))
        timed_aba = [r for r in aba if not r["warmup"]]
        self.assertEqual(
            [r["slot"] for r in timed_aba],
            ["A_1", "B", "A_2", "A_1", "B", "A_2", "A_1", "B", "A_2"],
        )
        self.assertEqual(timed_aba[0]["seed"], 1001)
        self.assertEqual(timed_aba[1]["seed"], 1001)
        self.assertEqual(timed_aba[2]["seed"], 101001)
        self.assertEqual(timed_aba[2]["base_seed"], 1001)

        abba = comfy_ab_harness.build_interleaved_schedule(
            ["A", "B"], [10, 20, 30, 40], order="abba", warmup=1
        )
        timed_abba = [r for r in abba if not r["warmup"]]
        self.assertEqual(
            [(r["arm"], r["seed"]) for r in timed_abba],
            [
                ("A", 10),
                ("B", 10),
                ("B", 20),
                ("A", 20),
                ("A", 30),
                ("B", 30),
                ("B", 40),
                ("A", 40),
            ],
        )

    def test_strict_cache_rejects_cached_sampler_and_asymmetric_encoder(self) -> None:
        wf = sample_workflow("ctl")
        # ctl_2 hits ComfyUI's execution cache on KSampler ("3") -> 0.07 s distortion
        cached_sampler_hist = {
            "status": {
                "status_str": "success",
                "completed": True,
                "messages": [
                    ["execution_start", {"timestamp": 1000}],
                    ["execution_cached", {"nodes": ["1", "2", "3"]}],
                    ["execution_success", {"timestamp": 1070}],
                ],
            }
        }
        tel_bad_sampler = comfy_ab_harness.parse_execution_telemetry(wf, cached_sampler_hist)
        self.assertTrue(tel_bad_sampler["sampler_cached"])
        self.assertAlmostEqual(tel_bad_sampler["exec_s"], 0.07)

        clean_cached_enc_hist = {
            "status": {
                "status_str": "success",
                "completed": True,
                "messages": [
                    ["execution_start", {"timestamp": 2000}],
                    ["execution_cached", {"nodes": ["1", "2"]}],
                    ["executing", {"node": "3"}],
                    ["executing", {"node": None}],
                    ["execution_success", {"timestamp": 3520}],
                ],
            }
        }
        tel_clean = comfy_ab_harness.parse_execution_telemetry(wf, clean_cached_enc_hist)
        self.assertFalse(tel_clean["sampler_cached"])
        self.assertEqual(tel_clean["encoder_cache_state"], "all_cached")

        with self.assertRaisesRegex(comfy_ab_harness.CacheIntegrityError, "Sampler cache hit"):
            comfy_ab_harness.verify_strict_cache(
                [
                    {"arm": "A", "slot": "A_1", "seed": 1001, "base_seed": 1001, "warmup": False, **tel_clean},
                    {"arm": "B", "slot": "B", "seed": 1001, "base_seed": 1001, "warmup": False, **tel_clean},
                    {"arm": "A", "slot": "A_2", "seed": 1001, "base_seed": 1001, "warmup": False, **tel_bad_sampler},
                ]
            )

        # Asymmetric encoder: A_1 runs CLIPTextEncode cold while B hits CLIPTextEncode cache
        uncached_enc_hist = {
            "status": {
                "status_str": "success",
                "completed": True,
                "messages": [
                    ["execution_start", {"timestamp": 5000}],
                    ["execution_cached", {"nodes": ["1"]}],
                    ["executing", {"node": "2"}],
                    ["executing", {"node": "3"}],
                    ["executing", {"node": None}],
                    ["execution_success", {"timestamp": 7900}],
                ],
            }
        }
        tel_uncached_enc = comfy_ab_harness.parse_execution_telemetry(wf, uncached_enc_hist)
        self.assertEqual(tel_uncached_enc["encoder_cache_state"], "none_cached")

        with self.assertRaisesRegex(
            comfy_ab_harness.CacheIntegrityError, "Asymmetric text-encoder cache state"
        ):
            comfy_ab_harness.verify_strict_cache(
                [
                    {"arm": "A", "slot": "A_1", "seed": 1001, "base_seed": 1001, "warmup": False, **tel_uncached_enc},
                    {"arm": "B", "slot": "B", "seed": 1001, "base_seed": 1001, "warmup": False, **tel_clean},
                ]
            )

        # Symmetric cached encoders and zero cached samplers pass cleanly
        comfy_ab_harness.verify_strict_cache(
            [
                {"arm": "A", "slot": "A_1", "seed": 1001, "base_seed": 1001, "warmup": False, **tel_clean},
                {"arm": "B", "slot": "B", "seed": 1001, "base_seed": 1001, "warmup": False, **tel_clean},
                {"arm": "A", "slot": "A_2", "seed": 101001, "base_seed": 1001, "warmup": False, **tel_clean},
            ]
        )

    def test_median_iqr_and_power_cap_share(self) -> None:
        smi_lines = [
            "2865, 395.7, 99, 69, 0x0000000000000004",
            "2850, 395.4, 98, 70, 0x0000000000000004",
            "2880, 340.1, 95, 68, 0x0000000000000000",
            "2857, 392.0, 97, 70, 0x0000000000000004",
            "420,  52.0,  2,  44, 0x0000000000000001",  # idle sample filtered out
        ]
        parsed = [r for line in smi_lines if (r := comfy_ab_harness.parse_smi_line(line)) is not None]
        smi = comfy_ab_harness.summarize_smi_samples(parsed)
        self.assertEqual(smi["samples"], 5)
        self.assertEqual(smi["busy_samples"], 4)
        self.assertEqual(smi["clock_mhz"], 2861.0)
        self.assertEqual(smi["power_w"], 393.7)
        self.assertEqual(smi["power_capped_share"], 0.75)

        records = [
            {"arm": "A", "slot": "A_warmup_1", "exec_s": 9.9, "wall_s": 10.1, "warmup": True},
            {"arm": "B", "slot": "B_warmup_1", "exec_s": 5.5, "wall_s": 5.7, "warmup": True},
            {"arm": "A", "slot": "A_1", "exec_s": 6.48, "wall_s": 6.55, "warmup": False},
            {"arm": "B", "slot": "B", "exec_s": 2.60, "wall_s": 2.68, "warmup": False},
            {"arm": "A", "slot": "A_2", "exec_s": 6.50, "wall_s": 6.58, "warmup": False},
            {"arm": "A", "slot": "A_1", "exec_s": 6.52, "wall_s": 6.60, "warmup": False},
            {"arm": "B", "slot": "B", "exec_s": 2.62, "wall_s": 2.70, "warmup": False},
            {"arm": "A", "slot": "A_2", "exec_s": 6.46, "wall_s": 6.53, "warmup": False},
        ]
        summary = comfy_ab_harness.summarize_timings(records, control_arm="A")
        self.assertEqual(summary["discarded_warmups"], 2)
        self.assertEqual(summary["timed_runs"], 6)
        self.assertAlmostEqual(summary["arms"]["A"]["median_s"], 6.49, places=4)
        self.assertAlmostEqual(summary["arms"]["A"]["iqr_s"], 0.03, places=4)
        self.assertAlmostEqual(summary["arms"]["B"]["median_s"], 2.61, places=4)
        self.assertAlmostEqual(summary["arms"]["B"]["speedup_vs_control"], 6.49 / 2.61, places=3)
        self.assertAlmostEqual(summary["control_bracket_drift_pct"], 0.31, places=2)

    def test_end_to_end_cli_against_mock_comfy_server(self) -> None:
        seen_signatures: set[str] = set()
        histories: dict[str, dict[str, object]] = {}
        counter = 0

        class MockComfyHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                return

            def do_POST(self) -> None:
                nonlocal counter
                if self.path != "/prompt":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                self.assertNotIn_client_id = "client_id" not in body
                wf = body["prompt"]
                sig = json.dumps(wf, sort_keys=True)
                counter += 1
                pid = f"pid-{counter}"
                is_dup = sig in seen_signatures
                seen_signatures.add(sig)
                if is_dup:
                    messages = [
                        ["execution_start", {"timestamp": 1000}],
                        ["execution_cached", {"nodes": ["1", "2", "3"]}],
                        ["execution_success", {"timestamp": 1070}],
                    ]
                else:
                    dur_ms = 2600 if "cand" in sig else 6480
                    messages = [
                        ["execution_start", {"timestamp": 1000}],
                        ["execution_cached", {"nodes": ["1", "2"]}],
                        ["executing", {"node": "3"}],
                        ["executing", {"node": None}],
                        ["execution_success", {"timestamp": 1000 + dur_ms}],
                    ]
                histories[pid] = {
                    "status": {"status_str": "success", "completed": True, "messages": messages},
                    "outputs": {},
                }
                raw = json.dumps({"prompt_id": pid}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if not self.path.startswith("/history/"):
                    self.send_error(404)
                    return
                pid = self.path.rsplit("/", 1)[-1]
                payload = {pid: histories[pid]} if pid in histories else {}
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), MockComfyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"

        try:
            with tempfile.TemporaryDirectory() as tmp:
                ctl_file = Path(tmp) / "ctl.json"
                cand_file = Path(tmp) / "cand.json"
                jsonl_ok = Path(tmp) / "ok.jsonl"
                jsonl_fail = Path(tmp) / "fail.jsonl"
                ctl_file.write_text(json.dumps(sample_workflow("ctl")), encoding="utf-8")
                cand_file.write_text(json.dumps(sample_workflow("cand")), encoding="utf-8")

                # 1. With --a2-seed-offset 100000, A_2 executes cleanly -> exit 0
                rc_ok = comfy_ab_harness.main(
                    [
                        "--url",
                        base_url,
                        "--control",
                        str(ctl_file),
                        "--candidate",
                        str(cand_file),
                        "--order",
                        "aba",
                        "--a2-seed-offset",
                        "100000",
                        "--strict-cache",
                        "--no-smi",
                        "--poll-ms",
                        "10",
                        "--out",
                        str(jsonl_ok),
                    ]
                )
                self.assertEqual(rc_ok, 0)
                lines = [json.loads(ln) for ln in jsonl_ok.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(lines[-1]["event"], "summary")
                self.assertAlmostEqual(lines[-1]["arms"]["A"]["median_s"], 6.48, places=2)
                self.assertAlmostEqual(lines[-1]["arms"]["B"]["median_s"], 2.60, places=2)

                # 2. Without --a2-seed-offset, A_2 repeats A_1 seed and hits sampler cache -> exit 1
                seen_signatures.clear()
                rc_fail = comfy_ab_harness.main(
                    [
                        "--url",
                        base_url,
                        "--control",
                        str(ctl_file),
                        "--candidate",
                        str(cand_file),
                        "--order",
                        "aba",
                        "--strict-cache",
                        "--no-smi",
                        "--poll-ms",
                        "10",
                        "--out",
                        str(jsonl_fail),
                    ]
                )
                self.assertEqual(rc_fail, 1)
                fail_lines = [
                    json.loads(ln) for ln in jsonl_fail.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(fail_lines[-1]["event"], "strict_cache_error")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
