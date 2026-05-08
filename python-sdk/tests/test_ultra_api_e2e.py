"""Integration tests for the RFQ V2 flow.

Mirrors ``rust-sdk/tests/ultra_api_e2e.rs``:

1. Fetch a swap order from the preprod Ultra API ``/order``.
2. Sign the returned transaction and POST to ``/execute``.
3. Fetch a USDC → SPL token order and confirm the transaction structure.

These tests hit live services and require env vars — see ``tests/README.md``.
They are gated behind the ``integration`` pytest marker so a default
``pytest`` run skips them.
"""

import os
from typing import Any, Dict, List, Optional

import pytest

from .common import (
    SPL_TOKEN_MINT,
    USDC_MINT,
    TestConfig,
    sign_transaction,
)


# Optional dep: tests are decorated with skipif so they remain importable
# even when ``requests`` is missing in a stripped-down install.
try:  # noqa: SIM105
    import requests  # type: ignore[import]
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(requests is None, reason="`requests` is required for integration tests"),
    pytest.mark.skipif(
        not os.environ.get("RUN_INTEGRATION_TESTS"),
        reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
]


def _fetch_order(
    api_base: str,
    input_mint: str,
    output_mint: str,
    amount: int,
    taker: str,
) -> Dict[str, Any]:
    """Fetch a swap order from ``/order``. Mirrors Rust ``fetch_order``."""
    url = (
        f"{api_base}/order?"
        f"inputMint={input_mint}&"
        f"outputMint={output_mint}&"
        f"amount={amount}&"
        f"swapMode=ExactIn&"
        f"slippageBps=3000&"
        f"broadcastFeeType=maxCap&"
        f"priorityFeeLamports=1000000&"
        f"useWsol=false&"
        f"asLegacyTransaction=false&"
        f"excludeDexes=&"
        f"excludeRouters=jupiterz&"
        f"taker={taker}&"
        f"clientPlatform=jupiter.web.home_page"
    )
    print(f"  GET {url}")

    resp = requests.get(url)
    print(f"  status: {resp.status_code}")
    print(f"  body  : {resp.text}")
    assert resp.status_code == 200, f"/order returned {resp.status_code}: {resp.text}"

    order = resp.json()
    print(
        "  requestId: %s, inAmount: %s, outAmount: %s, threshold: %s, slippageBps: %s, feeBps: %s"
        % (
            order.get("requestId"),
            order.get("inAmount"),
            order.get("outAmount"),
            order.get("otherAmountThreshold"),
            order.get("slippageBps"),
            order.get("feeBps"),
        )
    )
    if order.get("routePlan"):
        for i, step in enumerate(order["routePlan"]):
            info = step["swapInfo"]
            print(
                "  route[%d]: %s%% via %s (%s -> %s)"
                % (
                    i,
                    step["percent"],
                    info["label"],
                    info["inAmount"],
                    info["outAmount"],
                )
            )
    if order.get("error"):
        print(f"  error: {order['error']}")
    return order


def test_ultra_api_order():
    """Fetch a swap order from the Ultra API ``/order`` endpoint.

    Mirrors Rust ``test_ultra_api_order``.
    """
    cfg = TestConfig.from_env()
    print("=== test_ultra_api_order ===")

    order = _fetch_order(
        cfg.ultra_api_base,
        cfg.input_mint,
        cfg.output_mint,
        1_000_000,
        cfg.taker,
    )

    request_id = order.get("requestId", "")
    transaction = order.get("transaction") or ""
    assert request_id, "Expected a non-empty requestId"
    assert transaction, "Expected a non-empty unsigned transaction"


def test_execute_order():
    """Full end-to-end ``/order`` -> sign -> ``/execute``.

    Mirrors Rust ``test_execute_order``.
    """
    cfg = TestConfig.from_env()
    keypair = cfg.require_keypair()
    print("=== test_execute_order ===")

    print("\n--- Step 1: GET /order ---")
    order = _fetch_order(
        cfg.ultra_api_base,
        cfg.input_mint,
        cfg.output_mint,
        1_000_000,
        cfg.taker,
    )

    unsigned_tx: Optional[str] = order.get("transaction")
    assert unsigned_tx, "Order has no transaction"

    print("\n--- Step 2: Sign transaction ---")
    signed_tx = sign_transaction(unsigned_tx, keypair)

    print("\n--- Step 3: POST /execute ---")
    execute_url = f"{cfg.ultra_api_base}/execute"
    resp = requests.post(
        execute_url,
        json={
            "requestId": order["requestId"],
            "signedTransaction": signed_tx,
        },
    )
    print(f"  status: {resp.status_code}")
    print(f"  body  : {resp.text}")
    assert resp.status_code == 200, f"/execute returned {resp.status_code}: {resp.text}"

    result = resp.json()
    print(
        "  result: status=%s, signature=%s, slot=%s"
        % (result.get("status"), result.get("signature"), result.get("slot"))
    )
    if result.get("swapEvents"):
        for i, ev in enumerate(result["swapEvents"]):
            print(
                "  swap[%d]: %s %s -> %s %s"
                % (
                    i,
                    ev["inputAmount"],
                    ev["inputMint"],
                    ev["outputAmount"],
                    ev["outputMint"],
                )
            )

    assert result["status"] == "Success", (
        f"Expected 'Success', got '{result['status']}'. "
        f"code={result.get('code')}, error={result.get('error')}"
    )


def test_decode_spl_token_order():
    """Fetch USDC -> SPL token order and verify the transaction is well-formed.

    Mirrors Rust ``test_decode_spl_token_order``. The Rust SDK uses the
    ``fill-decoder`` crate to scan for an embedded RFQ v2 fill; the Python
    SDK has no equivalent decoder yet, so we instead verify the basic shape
    of the returned versioned transaction.
    """
    cfg = TestConfig.from_env()
    print("=== test_decode_spl_token_order ===")

    order = _fetch_order(
        cfg.ultra_api_base,
        USDC_MINT,
        SPL_TOKEN_MINT,
        1_000_000,
        cfg.taker,
    )

    tx_b64: Optional[str] = order.get("transaction")
    assert tx_b64, "Order has no transaction — taker wallet likely has no funds"

    import base64

    from solders.transaction import VersionedTransaction  # type: ignore[import]

    tx_bytes = base64.b64decode(tx_b64)
    tx = VersionedTransaction.from_bytes(tx_bytes)

    msg = tx.message
    print(
        "  sigs=%d, accounts=%d, ixs=%d"
        % (len(tx.signatures), len(msg.account_keys), len(msg.instructions))
    )
    for i, ix in enumerate(msg.instructions):
        program_id_index = ix.program_id_index
        program_id = msg.account_keys[program_id_index]
        print(f"  ix[{i}] program: {program_id}")

    assert len(msg.instructions) > 0, "Transaction has no instructions"
    assert len(msg.account_keys) > 0, "Transaction has no account keys"
