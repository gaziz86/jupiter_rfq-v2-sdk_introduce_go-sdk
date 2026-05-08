"""gRPC Server Reflection client for discovering services and methods at runtime.

Mirrors ``rust-sdk/src/reflection.rs``: provides high-level helpers that wrap
the v1alpha reflection protocol exposed by gRPC servers built with
``tonic-reflection`` / ``grpc_reflection``.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import grpc
from google.protobuf.descriptor_pb2 import (
    DescriptorProto,
    FieldDescriptorProto,
    FileDescriptorProto,
    MethodDescriptorProto,
    ServiceDescriptorProto,
)
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

from .error import (
    ConfigurationError,
    ConnectionError as MMConnectionError,
    GrpcError,
    OtherError,
)

logger = logging.getLogger(__name__)


# --- Data classes ---------------------------------------------------------

@dataclass
class FieldInfo:
    """Information about a protobuf message field. Mirrors the Rust struct."""

    name: str
    number: int
    type_name: str
    is_repeated: bool
    is_required: bool
    is_optional: bool

    def __str__(self) -> str:
        if self.is_required:
            label = "required"
        elif self.is_repeated:
            label = "repeated"
        else:
            label = "optional"
        return f"{label} {self.type_name} {self.name} = {self.number};"


@dataclass
class MessageInfo:
    """Information about a protobuf message type."""

    name: str
    fields: List[FieldInfo] = field(default_factory=list)

    def __str__(self) -> str:
        body = "\n".join(f"  {f}" for f in self.fields)
        return f"message {self.name} {{\n{body}\n}}"


@dataclass
class MethodInfo:
    """Information about a gRPC method."""

    name: str
    input_type: str
    output_type: str
    client_streaming: bool
    server_streaming: bool

    def __str__(self) -> str:
        if self.client_streaming and self.server_streaming:
            tag = " [bidirectional streaming]"
        elif self.client_streaming:
            tag = " [client streaming]"
        elif self.server_streaming:
            tag = " [server streaming]"
        else:
            tag = ""
        return f"rpc {self.name}({self.input_type}) returns ({self.output_type}){tag}"


@dataclass
class ServiceInfo:
    """Information about a gRPC service."""

    name: str
    methods: List[MethodInfo] = field(default_factory=list)

    def __str__(self) -> str:
        head = f"Service: {self.name}"
        body = "\n".join(f"  {m}" for m in self.methods)
        return f"{head}\n{body}"


# --- Type-name helpers ----------------------------------------------------

_SCALAR_TYPE_NAMES = {
    FieldDescriptorProto.TYPE_DOUBLE: "double",
    FieldDescriptorProto.TYPE_FLOAT: "float",
    FieldDescriptorProto.TYPE_INT64: "int64",
    FieldDescriptorProto.TYPE_UINT64: "uint64",
    FieldDescriptorProto.TYPE_INT32: "int32",
    FieldDescriptorProto.TYPE_FIXED64: "fixed64",
    FieldDescriptorProto.TYPE_FIXED32: "fixed32",
    FieldDescriptorProto.TYPE_BOOL: "bool",
    FieldDescriptorProto.TYPE_STRING: "string",
    FieldDescriptorProto.TYPE_BYTES: "bytes",
    FieldDescriptorProto.TYPE_UINT32: "uint32",
    FieldDescriptorProto.TYPE_SFIXED32: "sfixed32",
    FieldDescriptorProto.TYPE_SFIXED64: "sfixed64",
    FieldDescriptorProto.TYPE_SINT32: "sint32",
    FieldDescriptorProto.TYPE_SINT64: "sint64",
    FieldDescriptorProto.TYPE_GROUP: "group",
    FieldDescriptorProto.TYPE_MESSAGE: "message",
    FieldDescriptorProto.TYPE_ENUM: "enum",
}


def _build_field_info(field_proto: FieldDescriptorProto) -> FieldInfo:
    if field_proto.HasField("type_name") and field_proto.type_name:
        # Strip leading dot from fully qualified type names — matches Rust output
        type_name = field_proto.type_name.lstrip(".")
    else:
        type_name = _SCALAR_TYPE_NAMES.get(field_proto.type, "unknown")

    return FieldInfo(
        name=field_proto.name,
        number=field_proto.number,
        type_name=type_name,
        is_repeated=field_proto.label == FieldDescriptorProto.LABEL_REPEATED,
        is_required=field_proto.label == FieldDescriptorProto.LABEL_REQUIRED,
        is_optional=field_proto.label == FieldDescriptorProto.LABEL_OPTIONAL,
    )


def _build_message_info(message: DescriptorProto) -> MessageInfo:
    return MessageInfo(
        name=message.name,
        fields=[_build_field_info(f) for f in message.field],
    )


def _find_message_recursive(
    name: str, message: DescriptorProto
) -> Optional[MessageInfo]:
    if message.name == name:
        return _build_message_info(message)
    for nested in message.nested_type:
        info = _find_message_recursive(name, nested)
        if info is not None:
            return info
    return None


def _find_message_in_file(name: str, fd: FileDescriptorProto) -> Optional[MessageInfo]:
    for msg in fd.message_type:
        info = _find_message_recursive(name, msg)
        if info is not None:
            return info
    return None


def _build_method_info(method: MethodDescriptorProto) -> MethodInfo:
    return MethodInfo(
        name=method.name,
        input_type=method.input_type,
        output_type=method.output_type,
        client_streaming=method.client_streaming,
        server_streaming=method.server_streaming,
    )


def _build_service_info(
    fully_qualified_name: str, service: ServiceDescriptorProto
) -> ServiceInfo:
    return ServiceInfo(
        name=fully_qualified_name,
        methods=[_build_method_info(m) for m in service.method],
    )


# --- Channel helpers ------------------------------------------------------

def _build_channel(endpoint: str) -> "grpc.aio.Channel":
    """Create a gRPC channel honouring the ``http://`` / ``https://`` prefix."""
    if endpoint.startswith("https://"):
        target = endpoint[len("https://") :]
        creds = grpc.ssl_channel_credentials()
        return grpc.aio.secure_channel(target, creds)
    if endpoint.startswith("http://"):
        target = endpoint[len("http://") :]
        return grpc.aio.insecure_channel(target)
    # Fall back to insecure if no scheme is given
    return grpc.aio.insecure_channel(endpoint)


# --- ReflectionClient -----------------------------------------------------

class ReflectionClient:
    """High-level client for querying gRPC server reflection.

    Mirrors the Rust ``ReflectionClient``.
    """

    def __init__(self, channel: "grpc.aio.Channel"):
        self._channel = channel
        self._owns_channel = False

    @classmethod
    async def connect(cls, endpoint: str) -> "ReflectionClient":
        """Connect to a gRPC server's reflection service.

        Raises :class:`ConfigurationError` on invalid endpoints or
        :class:`ConnectionError` when the channel cannot be established.
        """
        if not endpoint:
            raise ConfigurationError("Invalid endpoint: empty")
        try:
            channel = _build_channel(endpoint)
        except Exception as exc:  # pragma: no cover - very unlikely
            raise ConfigurationError(f"Invalid endpoint: {exc}") from exc

        client = cls(channel)
        client._owns_channel = True
        return client

    @classmethod
    def from_channel(cls, channel: "grpc.aio.Channel") -> "ReflectionClient":
        """Build a reflection client from an existing channel."""
        return cls(channel)

    async def close(self) -> None:
        """Close the underlying channel if this client owns it."""
        if self._owns_channel and self._channel is not None:
            await self._channel.close()

    async def __aenter__(self) -> "ReflectionClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    # High-level operations
    # ------------------------------------------------------------------ #

    async def list_services(self) -> List[str]:
        """List all services advertised by the server."""
        response = await self._make_request(
            reflection_pb2.ServerReflectionRequest(list_services="")
        )
        if response.WhichOneof("message_response") != "list_services_response":
            raise OtherError("Unexpected reflection response for list_services")
        services = [svc.name for svc in response.list_services_response.service]
        logger.debug("Discovered %d services", len(services))
        return services

    async def file_descriptor_by_symbol(self, symbol: str) -> List[FileDescriptorProto]:
        """Return file descriptors containing the given symbol."""
        response = await self._make_request(
            reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
        )
        return self._parse_file_descriptor_response(response)

    async def file_descriptor_by_filename(
        self, filename: str
    ) -> List[FileDescriptorProto]:
        """Return file descriptors for a given proto filename."""
        response = await self._make_request(
            reflection_pb2.ServerReflectionRequest(file_by_filename=filename)
        )
        return self._parse_file_descriptor_response(response)

    async def list_methods(self, service_name: str) -> List[str]:
        """List method names for a fully-qualified service name."""
        info = await self.get_service_info(service_name)
        return [m.name for m in info.methods]

    async def get_service_info(self, service_name: str) -> ServiceInfo:
        """Get detailed information about a service."""
        descriptors = await self.file_descriptor_by_symbol(service_name)
        short_name = service_name.rsplit(".", 1)[-1]

        for fd in descriptors:
            for service in fd.service:
                if service.name == short_name:
                    return _build_service_info(service_name, service)

        raise OtherError(f"Service '{service_name}' not found in file descriptors")

    async def get_message_info(self, message_name: str) -> MessageInfo:
        """Get detailed information about a protobuf message type."""
        descriptors = await self.file_descriptor_by_symbol(message_name)
        short_name = message_name.rsplit(".", 1)[-1]

        for fd in descriptors:
            info = _find_message_in_file(short_name, fd)
            if info is not None:
                return info

        raise OtherError(f"Message '{message_name}' not found in file descriptors")

    async def get_all_service_info(self) -> List[ServiceInfo]:
        """Return :class:`ServiceInfo` for every advertised service."""
        names = await self.list_services()
        services: List[ServiceInfo] = []
        for name in names:
            try:
                services.append(await self.get_service_info(name))
            except Exception as exc:  # noqa: BLE001 — match Rust skip behaviour
                logger.debug(
                    "Skipping service '%s' (reflection metadata unavailable): %s",
                    name,
                    exc,
                )
        return services

    async def verify_market_maker_service(self) -> ServiceInfo:
        """Verify the ``MarketMakerIngestionService`` is available on the server."""
        services = await self.list_services()
        match = next((s for s in services if "MarketMakerIngestionService" in s), None)
        if match is None:
            raise OtherError(
                f"MarketMakerIngestionService not found. Available services: {services}"
            )
        return await self.get_service_info(match)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _make_request(
        self, request: reflection_pb2.ServerReflectionRequest
    ) -> reflection_pb2.ServerReflectionResponse:
        stub = reflection_pb2_grpc.ServerReflectionStub(self._channel)

        async def request_iter():
            yield request

        try:
            call = stub.ServerReflectionInfo(request_iter())
            async for resp in call:
                return resp
        except grpc.RpcError as rpc_err:
            raise GrpcError(rpc_err) from rpc_err

        raise OtherError("Empty reflection response stream")

    @staticmethod
    def _parse_file_descriptor_response(
        response: reflection_pb2.ServerReflectionResponse,
    ) -> List[FileDescriptorProto]:
        which = response.WhichOneof("message_response")
        if which == "file_descriptor_response":
            descriptors: List[FileDescriptorProto] = []
            for raw in response.file_descriptor_response.file_descriptor_proto:
                fd = FileDescriptorProto()
                fd.ParseFromString(raw)
                descriptors.append(fd)
            return descriptors
        if which == "error_response":
            err = response.error_response
            raise OtherError(
                f"Reflection error (code {err.error_code}): {err.error_message}"
            )
        raise OtherError("Unexpected reflection response type")


# --- ReflectionHandle -----------------------------------------------------

class ReflectionHandle:
    """Cached endpoint string that opens reflection connections on demand.

    Mirrors the Rust ``ReflectionHandle``.
    """

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    async def connect(self) -> ReflectionClient:
        """Open a fresh :class:`ReflectionClient`."""
        return await ReflectionClient.connect(self.endpoint)

    async def list_services(self) -> List[str]:
        """Convenience helper: list services in one shot."""
        client = await self.connect()
        try:
            return await client.list_services()
        finally:
            await client.close()

    async def verify_market_maker_service(self) -> ServiceInfo:
        """Convenience helper: verify the MarketMaker service in one shot."""
        client = await self.connect()
        try:
            return await client.verify_market_maker_service()
        finally:
            await client.close()


__all__ = [
    "FieldInfo",
    "MessageInfo",
    "MethodInfo",
    "ReflectionClient",
    "ReflectionHandle",
    "ServiceInfo",
]
