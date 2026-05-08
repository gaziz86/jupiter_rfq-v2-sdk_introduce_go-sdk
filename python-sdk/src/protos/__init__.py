"""Generated protobuf code for Jupiter RFQ gRPC service.

The two generated modules ``market_maker_pb2`` and ``market_maker_pb2_grpc``
are produced from ``../../protos/market_maker.proto`` at build time and are
intentionally **not** committed to the repository. They are regenerated:

* automatically by ``pip install`` (via ``setup.py`` ``build_py`` hook), or
* manually via ``python scripts/generate_protos.py``.

If the imports below fail with ``ModuleNotFoundError``, the stubs have not
been generated yet — run the script above.
"""

try:
    from .market_maker_pb2 import (
        Cluster,
        GetAllOrderbooksRequest,
        GetAllOrderbooksResponse,
        GetQuotesRequest,
        GetQuotesResponse,
        MarketMakerQuote,
        MarketMakerSwap,
        Orderbook,
        PriceLevel,
        QuoteResponse,
        QuoteUpdate,
        SequenceNumberRequest,
        SequenceNumberResponse,
        SwapMessageType,
        SwapUpdate,
        Token,
        TokenPair,
        UpdateType,
    )
    from .market_maker_pb2_grpc import (
        MarketMakerIngestionServiceServicer,
        MarketMakerIngestionServiceStub,
        add_MarketMakerIngestionServiceServicer_to_server,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - install-time error
    raise ModuleNotFoundError(
        "Generated protobuf stubs are missing. Run "
        "`python scripts/generate_protos.py` from the python-sdk/ directory, "
        "or reinstall with `pip install .`."
    ) from exc

__all__ = [
    "Cluster",
    "GetAllOrderbooksRequest",
    "GetAllOrderbooksResponse",
    "GetQuotesRequest",
    "GetQuotesResponse",
    "MarketMakerIngestionServiceServicer",
    "MarketMakerIngestionServiceStub",
    "MarketMakerQuote",
    "MarketMakerSwap",
    "Orderbook",
    "PriceLevel",
    "QuoteResponse",
    "QuoteUpdate",
    "SequenceNumberRequest",
    "SequenceNumberResponse",
    "SwapMessageType",
    "SwapUpdate",
    "Token",
    "TokenPair",
    "UpdateType",
    "add_MarketMakerIngestionServiceServicer_to_server",
]
