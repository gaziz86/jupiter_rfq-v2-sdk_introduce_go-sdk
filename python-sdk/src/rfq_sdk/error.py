"""Comprehensive error types for the RFQv2 SDK.

Mirrors the Rust ``MarketMakerError`` enum: each variant maps to a subclass of
:class:`MarketMakerError` so callers can ``except`` on a specific kind of failure
or on the base class.
"""

from typing import Optional

import grpc


class MarketMakerError(Exception):
    """Base class for all RFQv2 SDK errors."""

    def __init__(self, message: str, source: Optional[BaseException] = None):
        super().__init__(message)
        self.message = message
        self.__cause__ = source

    def __str__(self) -> str:
        return self.message

    # ------------------------------------------------------------------
    # Constructors that mirror the Rust helpers (`MarketMakerError::validation`
    # etc.). They return the appropriate subclass so calling code can use
    # ``raise MarketMakerError.validation("…")``.
    # ------------------------------------------------------------------
    @staticmethod
    def validation(msg: str) -> "ValidationError":
        return ValidationError(msg)

    @staticmethod
    def streaming(msg: str) -> "StreamingError":
        return StreamingError(msg)

    @staticmethod
    def timeout(msg: str) -> "TimeoutError":
        return TimeoutError(msg)

    @staticmethod
    def configuration(msg: str) -> "ConfigurationError":
        return ConfigurationError(msg)

    @staticmethod
    def other(msg: str) -> "OtherError":
        return OtherError(msg)

    # ------------------------------------------------------------------
    # Type predicates that mirror Rust's `is_*_error()` helpers.
    # ------------------------------------------------------------------
    def is_connection_error(self) -> bool:
        return isinstance(self, ConnectionError)

    def is_grpc_error(self) -> bool:
        return isinstance(self, GrpcError)

    def is_validation_error(self) -> bool:
        return isinstance(self, ValidationError)

    def is_streaming_error(self) -> bool:
        return isinstance(self, StreamingError)

    def is_timeout_error(self) -> bool:
        return isinstance(self, TimeoutError)


class ConnectionError(MarketMakerError):
    """Raised for connection-related failures (channel setup, transport errors)."""

    def __init__(self, message: str, source: Optional[BaseException] = None):
        super().__init__(f"Connection error: {message}", source)


class GrpcError(MarketMakerError):
    """Raised when an RPC call returns a gRPC status error."""

    def __init__(self, status: "grpc.RpcError"):
        message = f"gRPC error: {status}"
        super().__init__(message, source=status)
        self.status = status


class ValidationError(MarketMakerError):
    """Raised when quote / request data fails validation."""

    def __init__(self, message: str):
        super().__init__(f"Validation error: {message}")


class SerializationError(MarketMakerError):
    """Raised when serialization or deserialization fails."""

    def __init__(self, message: str, source: Optional[BaseException] = None):
        super().__init__(f"Serialization error: {message}", source)


class StreamingError(MarketMakerError):
    """Raised on streaming-specific failures (closed streams, send failures, …)."""

    def __init__(self, message: str):
        super().__init__(f"Streaming error: {message}")


class TimeoutError(MarketMakerError):  # noqa: A001 - intentionally shadows builtin
    """Raised when an operation does not finish before its deadline."""

    def __init__(self, message: str):
        super().__init__(f"Operation timed out: {message}")


class ConfigurationError(MarketMakerError):
    """Raised when client configuration is invalid."""

    def __init__(self, message: str):
        super().__init__(f"Configuration error: {message}")


class OtherError(MarketMakerError):
    """Catch-all for errors that don't fit the more specific categories."""

    def __init__(self, message: str):
        super().__init__(f"Error: {message}")


__all__ = [
    "MarketMakerError",
    "ConnectionError",
    "GrpcError",
    "ValidationError",
    "SerializationError",
    "StreamingError",
    "TimeoutError",
    "ConfigurationError",
    "OtherError",
]
