"""Jupiter RFQv2 SDK for Python.

This SDK provides a Python interface for the RFQv2 Ingestion Service. It
mirrors the Rust ``market-maker-client-sdk`` crate so the two SDKs share the
same shape, naming, and feature set.

Key entry points:

* :class:`MarketMakerClient` — async gRPC client (unary RPCs + streaming).
* :class:`MarketMakerQuoteBuilder` — fluent builder for quotes.
* :class:`ReflectionClient` / :class:`ReflectionHandle` — gRPC reflection.
* :mod:`rfq_sdk.streaming` — :class:`QuoteStreamHandle`,
  :class:`SwapStreamHandle`, :class:`update_helpers`, :class:`swap_update_helpers`.
* :mod:`rfq_sdk.error` — :class:`MarketMakerError` and subclasses.
"""

# --- Version & constants (mirror `lib.rs`) --------------------------------

__version__ = "0.1.0"
VERSION: str = __version__
DEFAULT_TIMEOUT_SECS: int = 30
DEFAULT_CHANNEL_BUFFER_SIZE: int = 1000

# --- Submodules (re-exported as `rfq_sdk.<name>`) -------------------------

from . import builders, error, reflection, streaming, types
from . import swap_helpers  # backward-compat shim

# --- Client ---------------------------------------------------------------

from .client import MarketMakerClient

# --- Errors (mirror `pub use error::{MarketMakerError, Result}`) ----------

from .error import (
    ConfigurationError,
    ConnectionError,
    GrpcError,
    MarketMakerError,
    OtherError,
    SerializationError,
    StreamingError,
    TimeoutError,
    ValidationError,
)

# --- Types & helpers (mirror `pub use types::*`) --------------------------

from .types import (
    DEFAULT_ENDPOINT,
    ClientConfig,
    PriceLevelHelper,
    QuoteHelper,
    TokenHelper,
    TokenPairHelper,
)

# --- Builders (mirror `pub use builders::*`) ------------------------------

from .builders import (
    DEFAULT_QUOTE_EXPIRY_MICROS,
    MarketMakerQuoteBuilder,
    QuoteBuilder,
    market_maker_quote_builder,
)

# --- Streaming (mirror `pub use streaming::*`) ----------------------------

from .streaming import (
    ConnectionStats,
    QuoteStreamHandle,
    QuoteUpdateStream,
    StreamConfig,
    SwapStats,
    SwapStreamHandle,
)

# --- Reflection (mirror `pub use reflection::*`) -------------------------

from .reflection import (
    FieldInfo,
    MessageInfo,
    MethodInfo,
    ReflectionClient,
    ReflectionHandle,
    ServiceInfo,
)

# --- Auth helpers (Python-only convenience) ------------------------------

from .auth import (
    get_auth_token_from_env,
    get_maker_id_from_env,
    get_solana_private_key_from_env,
    validate_environment,
)

# --- Utility helpers (Python-only convenience) ---------------------------

from .utils import (
    current_timestamp_micros,
    format_price,
    format_volume,
    to_raw_price,
    to_raw_volume,
    validate_keypair,
)

# --- Re-export protobuf types (mirror `pub mod market_maker { ... }`) ----

from protos.market_maker_pb2 import (
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

__all__ = [
    # Version / constants
    "VERSION",
    "__version__",
    "DEFAULT_TIMEOUT_SECS",
    "DEFAULT_CHANNEL_BUFFER_SIZE",
    "DEFAULT_ENDPOINT",
    "DEFAULT_QUOTE_EXPIRY_MICROS",
    # Submodules
    "builders",
    "error",
    "reflection",
    "streaming",
    "swap_helpers",
    "types",
    # Client
    "MarketMakerClient",
    # Errors
    "MarketMakerError",
    "ConfigurationError",
    "ConnectionError",
    "GrpcError",
    "OtherError",
    "SerializationError",
    "StreamingError",
    "TimeoutError",
    "ValidationError",
    # Configuration / helpers
    "ClientConfig",
    "TokenHelper",
    "TokenPairHelper",
    "PriceLevelHelper",
    "QuoteHelper",
    # Builders
    "MarketMakerQuoteBuilder",
    "QuoteBuilder",
    "market_maker_quote_builder",
    # Streaming
    "ConnectionStats",
    "StreamConfig",
    "QuoteStreamHandle",
    "QuoteUpdateStream",
    "SwapStats",
    "SwapStreamHandle",
    # Reflection
    "ReflectionClient",
    "ReflectionHandle",
    "ServiceInfo",
    "MethodInfo",
    "MessageInfo",
    "FieldInfo",
    # Auth
    "get_auth_token_from_env",
    "get_maker_id_from_env",
    "get_solana_private_key_from_env",
    "validate_environment",
    # Utils
    "current_timestamp_micros",
    "format_price",
    "format_volume",
    "to_raw_price",
    "to_raw_volume",
    "validate_keypair",
    # Protobuf types
    "Cluster",
    "GetAllOrderbooksRequest",
    "GetAllOrderbooksResponse",
    "GetQuotesRequest",
    "GetQuotesResponse",
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
]
