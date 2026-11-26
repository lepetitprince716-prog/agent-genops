#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only shared mmap loader and verifier for .safetensors files on unified-memory boxes.

On unified-memory Linux machines (such as an ARM64 UMA Box where CPU and GPU share physical
LPDDR5x), loading checkpoints with ``MAP_PRIVATE`` / ``ACCESS_COPY`` triggers copy-on-write
anonymous RSS duplication during CUDA host-to-device transfers, while mapping ``MAP_SHARED``
with write permission risks silent on-disk checkpoint corruption if a node mutates weights in
place.

This module enforces two layers:
  1. OS mapping: opens ``.safetensors`` / ``.sft`` files with ``rb`` and maps them with
     ``MAP_SHARED | PROT_READ`` on POSIX (``ACCESS_READ`` on Windows). Works with the Python
     standard library alone for header inspection, read-only ``memoryview`` slicing, and Linux
     ``/proc/self/maps`` (``r--s``) plus ``/proc/self/status`` (``RssAnon``) verification.
  2. PyTorch write guard (when ``torch`` is installed): wraps file-backed CPU tensors in
     ``ReadOnlyMmapTensor``, intercepting mutating ATen ops (``add_``, ``mul_``, ``zero_``,
     ``copy_``, ``__setitem__``, ``out=``, including through views and transposes) to raise
     ``ProtReadWriteError`` instead of crashing with ``SIGSEGV`` / ``SIGBUS`` or mutating
     shared pages.

    python3 tools/safetensors_prot_read.py FILE [--touch] [--verify-maps] [--load-torch] [--json]
"""

from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
import json
import mmap
import os
from pathlib import Path
import struct
import sys
from typing import Any
import warnings

try:
    import torch
    from torch.utils._pytree import tree_map as _tree_map
except ImportError:
    torch = None  # type: ignore[assignment]
    _tree_map = None  # type: ignore[assignment]

MAX_HEADER_BYTES = 100 * 1024 * 1024

# Byte width per safetensors dtype code (stdlib-safe, independent of torch).
SAFETENSORS_ITEMSIZE: dict[str, int] = {
    "BOOL": 1,
    "U8": 1,
    "I8": 1,
    "F8_E4M3": 1,
    "F8_E5M2": 1,
    "U16": 2,
    "I16": 2,
    "F16": 2,
    "BF16": 2,
    "U32": 4,
    "I32": 4,
    "F32": 4,
    "U64": 8,
    "I64": 8,
    "F64": 8,
}

SAFETENSORS_TORCH_DTYPES: dict[str, Any] = {}
if torch is not None:
    SAFETENSORS_TORCH_DTYPES = {
        "BOOL": torch.bool,
        "U8": torch.uint8,
        "I8": torch.int8,
        "I16": torch.int16,
        "I32": torch.int32,
        "I64": torch.int64,
        "F16": torch.float16,
        "BF16": torch.bfloat16,
        "F32": torch.float32,
        "F64": torch.float64,
    }
    for _code, _attr in (
        ("U16", "uint16"),
        ("U32", "uint32"),
        ("U64", "uint64"),
        ("F8_E4M3", "float8_e4m3fn"),
        ("F8_E5M2", "float8_e5m2"),
    ):
        if hasattr(torch, _attr):
            SAFETENSORS_TORCH_DTYPES[_code] = getattr(torch, _attr)


class ProtReadWriteError(PermissionError):
    """Raised when an in-place write targets a PROT_READ mmap-backed tensor."""


def _numel(shape: list[int]) -> int:
    total = 1
    for dim in shape:
        if not isinstance(dim, int) or isinstance(dim, bool) or dim < 0:
            raise ValueError(f"Invalid tensor dimension in safetensors header: {shape!r}")
        total *= dim
    return total


def parse_safetensors_header(
    buf: bytes | bytearray | memoryview | mmap.mmap,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None, int]:
    """Parse and validate a safetensors header from ``buf``.

    Returns ``(tensors, metadata, data_start)`` where ``data_start == 8 + header_len``.
    Raises ``ValueError`` on any structural, dtype, shape, or offset error.
    """
    file_size = len(buf)
    if file_size < 8:
        raise ValueError(f"Safetensors buffer too small ({file_size} bytes; need at least 8)")

    header_len = struct.unpack("<Q", bytes(buf[:8]))[0]
    if header_len == 0 or header_len > MAX_HEADER_BYTES or 8 + header_len > file_size:
        raise ValueError(
            f"Invalid safetensors header length {header_len} for {file_size}-byte file"
        )

    try:
        raw_json = bytes(buf[8 : 8 + header_len]).decode("utf-8")
        parsed = json.loads(raw_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Corrupt safetensors JSON header: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Safetensors JSON header must be an object")

    metadata = parsed.pop("__metadata__", None)
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("Safetensors __metadata__ entry must be an object")

    data_start = 8 + header_len
    data_len = file_size - data_start
    tensors: dict[str, dict[str, Any]] = {}

    for name, info in parsed.items():
        if not isinstance(info, dict):
            raise ValueError(f"Tensor entry {name!r} must be an object")
        st_dtype = info.get("dtype")
        if not isinstance(st_dtype, str) or st_dtype not in SAFETENSORS_ITEMSIZE:
            raise ValueError(f"Unsupported safetensors dtype {st_dtype!r} for tensor {name!r}")
        raw_shape = info.get("shape")
        if not isinstance(raw_shape, list):
            raise ValueError(f"Missing or non-list shape for tensor {name!r}")
        shape = list(raw_shape)
        offsets = info.get("data_offsets")
        if (
            not isinstance(offsets, (list, tuple))
            or len(offsets) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in offsets)
        ):
            raise ValueError(f"Invalid data_offsets {offsets!r} for tensor {name!r}")
        start, end = int(offsets[0]), int(offsets[1])
        if start < 0 or end < start or end > data_len:
            raise ValueError(
                f"Out-of-bounds data_offsets [{start}, {end}] (data_len={data_len}) for {name!r}"
            )
        expected_bytes = _numel(shape) * SAFETENSORS_ITEMSIZE[st_dtype]
        if (end - start) != expected_bytes:
            raise ValueError(
                f"Byte length mismatch for {name!r}: offsets span {end - start} bytes, "
                f"shape {shape} x {st_dtype} requires {expected_bytes} bytes"
            )
        tensors[name] = {
            "dtype": st_dtype,
            "shape": shape,
            "data_offsets": [start, end],
            "nbytes": expected_bytes,
        }

    return tensors, metadata, data_start


def open_prot_read_mmap(path: str | os.PathLike[str]) -> mmap.mmap:
    """Open ``path`` as a shared read-only memory map (``MAP_SHARED | PROT_READ`` on POSIX)."""
    p = Path(path)
    file_size = p.stat().st_size
    if file_size < 8:
        raise ValueError(f"Safetensors file too small ({file_size} bytes): {p}")
    with open(p, "rb") as fp:
        if hasattr(mmap, "MAP_SHARED") and hasattr(mmap, "PROT_READ"):
            return mmap.mmap(fp.fileno(), 0, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ)
        return mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)


class ProtReadSafetensors(AbstractContextManager["ProtReadSafetensors"]):
    """Standard-library read-only safetensors handle exposing immutable ``memoryview`` slices."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.mm = open_prot_read_mmap(self.path)
        try:
            self.tensors, self.metadata, self.data_start = parse_safetensors_header(self.mm)
        except Exception:
            self.mm.close()
            raise
        self._data_view: memoryview | None = memoryview(self.mm)[self.data_start :]
        self._slice_views: list[memoryview] = []

    def tensor_view(self, name: str) -> memoryview:
        """Return a read-only ``memoryview`` for tensor ``name``."""
        if self._data_view is None:
            raise ValueError("ProtReadSafetensors mapping is closed")
        info = self.tensors[name]
        start, end = info["data_offsets"]
        view = self._data_view[start:end]
        self._slice_views.append(view)
        return view

    def touch_pages(self, page_size: int = 4096) -> int:
        """Read one byte per page across the tensor payload and return a checksum accumulator."""
        if self._data_view is None:
            raise ValueError("ProtReadSafetensors mapping is closed")
        acc = 0
        mv = self._data_view
        for offset in range(0, len(mv), max(1, page_size)):
            acc = (acc + mv[offset]) & 0xFFFFFFFF
        if len(mv) > 0:
            acc = (acc + mv[-1]) & 0xFFFFFFFF
        return acc

    def close(self) -> None:
        for view in self._slice_views:
            view.release()
        self._slice_views.clear()
        if self._data_view is not None:
            self._data_view.release()
            self._data_view = None
        if not self.mm.closed:
            self.mm.close()

    def __exit__(self, *exc: object) -> None:
        self.close()


def inspect_safetensors(path: str | os.PathLike[str]) -> ProtReadSafetensors:
    """Open ``path`` with ``ProtReadSafetensors`` (stdlib only, no ``torch`` required)."""
    return ProtReadSafetensors(path)


def check_mutable_schema_targets(
    schema: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    is_protected_fn: Any,
    op_name: Any = None,
) -> None:
    """Raise ``ProtReadWriteError`` if a mutable schema writes to any protected argument."""
    if not getattr(schema, "is_mutable", False):
        return
    label = op_name if op_name is not None else getattr(schema, "name", "op")
    for arg_schema, arg in zip(schema.arguments, args):
        alias = getattr(arg_schema, "alias_info", None)
        if alias is not None and getattr(alias, "is_write", False) and is_protected_fn(arg):
            raise ProtReadWriteError(
                f"Refusing in-place write ({label}) on PROT_READ safetensors tensor; "
                "call .clone() or copy_on_patch() first."
            )
    for arg_schema in schema.arguments:
        alias = getattr(arg_schema, "alias_info", None)
        if (
            alias is not None
            and getattr(alias, "is_write", False)
            and arg_schema.name in kwargs
            and is_protected_fn(kwargs[arg_schema.name])
        ):
            raise ProtReadWriteError(
                f"Refusing in-place kwarg write ({label}, {arg_schema.name}=) on PROT_READ "
                "safetensors tensor; call .clone() or copy_on_patch() first."
            )


if torch is not None:

    class ReadOnlyMmapTensor(torch.Tensor):
        """Zero-copy ``torch.Tensor`` wrapper blocking in-place writes on ``PROT_READ`` pages."""

        _elem: torch.Tensor

        @staticmethod
        def __new__(cls, elem: torch.Tensor) -> "ReadOnlyMmapTensor":
            if isinstance(elem, ReadOnlyMmapTensor):
                return elem
            return torch.Tensor._make_wrapper_subclass(
                cls,
                elem.size(),
                strides=elem.stride(),
                storage_offset=elem.storage_offset(),
                dtype=elem.dtype,
                layout=elem.layout,
                device=elem.device,
                requires_grad=False,
            )

        def __init__(self, elem: torch.Tensor) -> None:
            self._elem = elem._elem if isinstance(elem, ReadOnlyMmapTensor) else elem

        def __repr__(self) -> str:
            return (
                f"ReadOnlyMmapTensor(shape={tuple(self.shape)}, "
                f"dtype={self.dtype}, device={self.device})"
            )

        @property
        def is_prot_read(self) -> bool:
            return True

        def unwrap_readonly(self) -> torch.Tensor:
            """Return the underlying raw ``PROT_READ`` tensor for explicit read-only transfers."""
            return self._elem

        @classmethod
        def __torch_dispatch__(
            cls,
            func: Any,
            types: Any,
            args: tuple[Any, ...] = (),
            kwargs: dict[str, Any] | None = None,
        ) -> Any:
            kwargs = kwargs or {}
            schema = func._schema
            check_mutable_schema_targets(schema, args, kwargs, _contains_readonly, op_name=func)

            u_args = _tree_map(_unwrap_elem, args)
            u_kwargs = _tree_map(_unwrap_elem, kwargs)
            out = func(*u_args, **u_kwargs)

            if any(ret.alias_info is not None for ret in schema.returns):
                return _tree_map(_rewrap_if_same_storage(args, kwargs), out)
            return out

    def _contains_readonly(obj: Any) -> bool:
        found = False

        def _visit(x: Any) -> Any:
            nonlocal found
            if isinstance(x, ReadOnlyMmapTensor):
                found = True
            return x

        _tree_map(_visit, obj)
        return found

    def _unwrap_elem(x: Any) -> Any:
        return x._elem if isinstance(x, ReadOnlyMmapTensor) else x

    def _collect_readonly_storage_ptrs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> set[int]:
        ptrs: set[int] = set()

        def _visit(x: Any) -> Any:
            if isinstance(x, ReadOnlyMmapTensor):
                try:
                    ptrs.add(x._elem.untyped_storage().data_ptr())
                except Exception:
                    pass
            return x

        _tree_map(_visit, args)
        _tree_map(_visit, kwargs)
        return ptrs

    def _rewrap_if_same_storage(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        ro_ptrs = _collect_readonly_storage_ptrs(args, kwargs)

        def _wrap(x: Any) -> Any:
            if isinstance(x, torch.Tensor) and not isinstance(x, ReadOnlyMmapTensor):
                try:
                    if x.untyped_storage().data_ptr() in ro_ptrs:
                        return ReadOnlyMmapTensor(x)
                except Exception:
                    return ReadOnlyMmapTensor(x)
            return x

        return _wrap

else:
    ReadOnlyMmapTensor = None  # type: ignore[assignment,misc]


def copy_on_patch(tensor: Any) -> Any:
    """Return a private writable ``.clone()`` when ``tensor`` is ``ReadOnlyMmapTensor``."""
    if ReadOnlyMmapTensor is not None and isinstance(tensor, ReadOnlyMmapTensor):
        return tensor.clone()
    return tensor


def load_safetensors_prot_read(
    path: str | os.PathLike[str],
    *,
    device: Any = None,
    return_metadata: bool = False,
    protect_inplace: bool = True,
) -> Any:
    """Load a ``.safetensors`` file via ``MAP_SHARED | PROT_READ`` using ``torch.frombuffer``."""
    if torch is None:
        raise RuntimeError(
            "torch is not installed; use inspect_safetensors() for stdlib header and mmap checks"
        )

    p = Path(path)
    mm = open_prot_read_mmap(p)
    try:
        tensors, metadata, data_start = parse_safetensors_header(mm)
    except Exception:
        mm.close()
        raise

    mv = memoryview(mm)[data_start:]
    target_device = torch.device(device) if device is not None else None
    move_to_non_cpu = target_device is not None and target_device.type != "cpu"

    state_dict: dict[str, Any] = {}
    for name, info in tensors.items():
        st_dtype = info["dtype"]
        if st_dtype not in SAFETENSORS_TORCH_DTYPES:
            mv.release()
            mm.close()
            raise ValueError(
                f"Safetensors dtype {st_dtype!r} is not supported by torch {torch.__version__}"
            )
        dtype = SAFETENSORS_TORCH_DTYPES[st_dtype]
        shape = info["shape"]
        start, end = info["data_offsets"]
        if start == end:
            tensor = torch.empty(
                shape, dtype=dtype, device=target_device if move_to_non_cpu else "cpu"
            )
        else:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="The given buffer is not writable")
                raw_tensor = torch.frombuffer(mv[start:end], dtype=dtype).view(shape)
            if move_to_non_cpu:
                tensor = raw_tensor.to(target_device)
            elif protect_inplace:
                tensor = ReadOnlyMmapTensor(raw_tensor)
            else:
                tensor = raw_tensor
        state_dict[name] = tensor

    if move_to_non_cpu:
        mv.release()
        mm.close()

    return (state_dict, metadata) if return_metadata else state_dict


def parse_proc_status_rss(status_text: str) -> dict[str, int]:
    """Parse ``RssAnon``, ``RssFile``, ``RssShmem`` and ``VmRSS`` (bytes) from ``/proc/<pid>/status``."""
    out: dict[str, int] = {}
    for line in status_text.splitlines():
        for key in ("RssAnon", "RssFile", "RssShmem", "VmRSS"):
            if line.startswith(f"{key}:"):
                parts = line.split()
                if len(parts) >= 2:
                    val = int(parts[1])
                    unit = parts[2].lower() if len(parts) >= 3 else "kb"
                    mult = 1024 if unit == "kb" else (1024 * 1024 if unit == "mb" else 1)
                    out[key] = val * mult
    return out


def read_proc_rss_bytes(pid: int | None = None) -> dict[str, Any]:
    """Read RSS counters from ``/proc/<pid>/status`` when running on Linux."""
    proc_path = Path(f"/proc/{'self' if pid is None else pid}/status")
    if proc_path.is_file():
        text = proc_path.read_text(encoding="utf-8")
        return {"platform": sys.platform, "proc_status_available": True, **parse_proc_status_rss(text)}
    return {"platform": sys.platform, "proc_status_available": False}


def verify_proc_maps_prot_read(
    maps_text: str, target_path: str | os.PathLike[str]
) -> dict[str, Any]:
    """Verify every ``/proc/<pid>/maps`` entry for ``target_path`` has ``r--s`` permissions."""
    needle_resolved = str(Path(target_path).resolve())
    needle_raw = str(Path(target_path))
    matched_perms: list[str] = []
    for line in maps_text.splitlines():
        parts = line.split(None, 5)
        if len(parts) == 6 and parts[5].strip() in (needle_resolved, needle_raw):
            matched_perms.append(parts[1])
    if not matched_perms:
        return {"found": False, "all_prot_read_shared": False, "perms": []}
    all_safe = all(p.startswith("r-") and "w" not in p and p.endswith("s") for p in matched_perms)
    return {"found": True, "all_prot_read_shared": all_safe, "perms": matched_perms}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("file", help="Path to .safetensors / .sft file to inspect and map read-only")
    ap.add_argument("--touch", action="store_true", help="Touch one byte per 4 KiB page and report RSS delta")
    ap.add_argument(
        "--verify-maps",
        action="store_true",
        help="Require Linux /proc/self/maps to show strictly r--s on the mapped file",
    )
    ap.add_argument(
        "--load-torch",
        action="store_true",
        help="Also wrap tensors with ReadOnlyMmapTensor via torch and test write rejection",
    )
    ap.add_argument("--json", action="store_true", help="Print structured JSON report")
    args = ap.parse_args(argv)

    target = Path(args.file)
    if not target.is_file():
        print(f"safetensors_prot_read: file not found: {target}", file=sys.stderr)
        return 2

    rss_before = read_proc_rss_bytes()
    try:
        handle = inspect_safetensors(target)
    except (OSError, ValueError) as exc:
        print(f"safetensors_prot_read: {exc}", file=sys.stderr)
        return 2

    with handle:
        total_payload_bytes = sum(info["nbytes"] for info in handle.tensors.values())
        report: dict[str, Any] = {
            "file": str(target),
            "file_bytes": len(handle.mm),
            "tensor_count": len(handle.tensors),
            "payload_bytes": total_payload_bytes,
            "dtypes": sorted({info["dtype"] for info in handle.tensors.values()}),
            "torch_available": torch is not None,
        }

        if args.touch:
            report["touch_checksum"] = handle.touch_pages()
            rss_after = read_proc_rss_bytes()
            if rss_before.get("proc_status_available") and rss_after.get("proc_status_available"):
                report["rss_anon_delta_bytes"] = rss_after.get("RssAnon", 0) - rss_before.get(
                    "RssAnon", 0
                )
                report["rss_file_delta_bytes"] = rss_after.get("RssFile", 0) - rss_before.get(
                    "RssFile", 0
                )

        maps_path = Path("/proc/self/maps")
        if maps_path.is_file():
            maps_check = verify_proc_maps_prot_read(
                maps_path.read_text(encoding="utf-8"), target
            )
            report["proc_maps"] = maps_check
            if args.verify_maps and not maps_check["all_prot_read_shared"]:
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(
                        f"FAIL: /proc/self/maps permissions not r--s: {maps_check}",
                        file=sys.stderr,
                    )
                return 1
        elif args.verify_maps:
            print(
                "safetensors_prot_read: --verify-maps requires Linux /proc/self/maps",
                file=sys.stderr,
            )
            return 2

        if args.load_torch:
            if torch is None:
                print(
                    "safetensors_prot_read: --load-torch requested, but torch is not installed",
                    file=sys.stderr,
                )
                return 2
            sd = load_safetensors_prot_read(target, protect_inplace=True)
            guarded = 0
            for t in sd.values():
                if isinstance(t, ReadOnlyMmapTensor) and t.numel() > 0:
                    try:
                        t.zero_()
                    except ProtReadWriteError:
                        guarded += 1
                    else:
                        print("FAIL: ReadOnlyMmapTensor allowed zero_()", file=sys.stderr)
                        return 1
                    break
            report["torch_write_guard_verified"] = guarded > 0 or all(
                t.numel() == 0 for t in sd.values()
            )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        perms = report.get("proc_maps", {}).get("perms", ["n/a"])
        anon = report.get("rss_anon_delta_bytes")
        anon_note = f", RssAnon delta={anon} B" if anon is not None else ""
        print(
            f"{report['file']}: {report['tensor_count']} tensors, "
            f"{report['payload_bytes']} payload bytes, dtypes={','.join(report['dtypes'])}, "
            f"maps={','.join(perms)}{anon_note}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
