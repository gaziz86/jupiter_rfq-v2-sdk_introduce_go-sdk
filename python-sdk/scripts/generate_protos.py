#!/usr/bin/env python3
"""Generate the Python protobuf stubs from ``protos/market_maker.proto``.

Run from a clone of the repo to materialise ``src/protos/market_maker_pb2.py``
and ``src/protos/market_maker_pb2_grpc.py`` (which are intentionally **not**
checked into git — see ``.gitignore``).

Usage::

    python scripts/generate_protos.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def generate(repo_root: Path) -> None:
    proto_dir = repo_root.parent / "protos"
    proto_file = proto_dir / "market_maker.proto"
    out_dir = repo_root / "src" / "protos"

    if not proto_file.is_file():
        raise SystemExit(f"Cannot find proto file: {proto_file}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Importing here so the script can fail with a friendly message if the
    # build dep isn't installed yet.
    try:
        from grpc_tools import protoc
    except ImportError as exc:
        raise SystemExit(
            "grpcio-tools is required to generate protobuf stubs. "
            "Install it with `pip install grpcio-tools`."
        ) from exc

    args = [
        "grpc_tools.protoc",
        f"--proto_path={proto_dir}",
        f"--python_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        str(proto_file),
    ]
    rc = protoc.main(args)
    if rc != 0:
        raise SystemExit(f"protoc failed with exit code {rc}")

    # The grpc plugin emits ``import market_maker_pb2`` (top-level) which
    # breaks once the package is installed. Rewrite to a relative import,
    # matching what the user-facing package expects.
    grpc_path = out_dir / "market_maker_pb2_grpc.py"
    text = grpc_path.read_text()
    fixed = text.replace(
        "import market_maker_pb2 as market__maker__pb2",
        "from . import market_maker_pb2 as market__maker__pb2",
    )
    if fixed != text:
        grpc_path.write_text(fixed)

    print(f"Generated:\n  {out_dir / 'market_maker_pb2.py'}")
    print(f"  {out_dir / 'market_maker_pb2_grpc.py'}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    generate(here)
