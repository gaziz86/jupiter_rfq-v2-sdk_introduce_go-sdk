# RFQ V2 Python Test Suite

End-to-end integration tests that interact with the live V2 gRPC service and
the preprod Ultra API. Mirrors the Rust integration suite at
`rust-sdk/tests/`.

## Layout

| File                          | Description                                                |
| ----------------------------- | ---------------------------------------------------------- |
| `test_builders.py`            | Unit tests for `MarketMakerQuoteBuilder` validation rules. |
| `test_client.py`              | Mock-server tests for `MarketMakerClient.get_quotes`.      |
| `test_reflection.py`          | Unit tests for the reflection dataclass formatting.        |
| `test_ultra_api_e2e.py`       | Integration tests against the live preprod Ultra API.      |
| `common/__init__.py`          | Shared `TestConfig` + signing helper.                      |

## Running unit tests

```bash
pytest -m "not integration"
```

## Running integration tests

Integration tests are gated by the `integration` marker **and** the
`RUN_INTEGRATION_TESTS=1` environment variable so that an accidental
`pytest -m integration` cannot hit live services.

| Variable             | Description                                              | Required |
| -------------------- | -------------------------------------------------------- | -------- |
| `RUN_INTEGRATION_TESTS` | Must be set to `1` to enable integration tests        | **Yes**  |
| `SOLANA_PRIVATE_KEY` | Base58-encoded private key of the **taker** wallet       | **Yes**  |
| `INPUT_MINT`         | SPL token mint for the input side (default: USDC)        | No       |
| `OUTPUT_MINT`        | SPL token mint for the output side (default: SPL token)  | No       |
| `TAKER`              | Taker public key — derived from `SOLANA_PRIVATE_KEY` if omitted | No |
| `ULTRA_API_BASE`     | Ultra API base URL (default: `https://preprod.ultra-api.jup.ag`) | No |

```bash
RUN_INTEGRATION_TESTS=1 \
SOLANA_PRIVATE_KEY=... \
pytest -m integration -s
```

```bash
# Run just one test
RUN_INTEGRATION_TESTS=1 \
SOLANA_PRIVATE_KEY=... \
pytest tests/test_ultra_api_e2e.py::test_execute_order -s
```
