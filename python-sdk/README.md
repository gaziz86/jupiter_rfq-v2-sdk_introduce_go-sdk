# Jupiter RFQ v2 Python SDK

Python SDK for interacting with Jupiter's RFQ (Request for Quote) v2.

Mirrors the Rust [`market-maker-client-sdk`](../rust-sdk) crate so the two SDKs
share the same shape, naming, and feature set.

## Installation

The Python protobuf stubs are not committed — they are generated locally from
[`../protos/market_maker.proto`](../protos/market_maker.proto). After cloning,
generate them once and install:

```bash
cd python-sdk
python -m venv ./venv && source venv/bin/activate
pip install grpcio-tools
python scripts/generate_protos.py
pip install .
```

Re-run `python scripts/generate_protos.py` whenever the `.proto` file changes.

## Examples

Self-contained scripts under [`examples/`](examples) — see the file headers
for what each one does:

- [`production_streaming.py`](examples/production_streaming.py)
- [`reflection_cli.py`](examples/reflection_cli.py)
- [`deploy_spl_token.py`](examples/deploy_spl_token.py)

```bash
python examples/production_streaming.py
```

## Tests

```bash
pytest -m "not integration"
```

Integration tests require live services and credentials —
see [`tests/README.md`](tests/README.md).

## Requirements

Python 3.8+. Dependencies (installed by `pip install .`): grpcio,
grpcio-tools, grpcio-reflection, protobuf, solders, base58.

## License

MIT
