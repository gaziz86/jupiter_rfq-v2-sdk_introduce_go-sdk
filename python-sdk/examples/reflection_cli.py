"""CLI tool for exploring gRPC server reflection on the RFQv2 Ingestion Service.

Mirrors ``rust-sdk/examples/reflection_cli.rs`` — a thin command-line wrapper
around :class:`rfq_sdk.reflection.ReflectionClient`.

USAGE::

    python examples/reflection_cli.py [--endpoint URL] <COMMAND> [ARGS]

Commands::

    list-services (ls)                       List all gRPC services
    describe-service (ds) <SERVICE_NAME>     Show methods for a service
    describe-message (dm) <MESSAGE_NAME>     Show fields of a protobuf message
    verify                                   Verify the MarketMaker service
    inspect                                  Full introspection
    help                                     Print this help
"""

import argparse
import asyncio
import os
import sys

# Make the SDK importable when run from the repo
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

from rfq_sdk.reflection import ReflectionClient  # noqa: E402  pylint: disable=wrong-import-position


DEFAULT_ENDPOINT = "http://localhost:2408"


def _short_type(fq: str) -> str:
    """Strip the leading dot and package prefix for display."""
    return fq.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_list_services(client: ReflectionClient) -> None:
    services = await client.list_services()
    print(f"Services ({len(services)}):")
    for name in services:
        print(f"  • {name}")


async def cmd_describe_service(client: ReflectionClient, name: str) -> None:
    info = await client.get_service_info(name)
    print(f"╭─ Service: {info.name}")
    print("│")
    for i, method in enumerate(info.methods):
        prefix = "╰─" if i + 1 == len(info.methods) else "├─"
        if method.client_streaming and method.server_streaming:
            streaming = "  ⇄  bidirectional stream"
        elif method.client_streaming:
            streaming = "  →  client stream"
        elif method.server_streaming:
            streaming = "  ←  server stream"
        else:
            streaming = "     unary"
        print(
            f"{prefix} rpc {method.name}({_short_type(method.input_type)}) "
            f"→ ({_short_type(method.output_type)}){streaming}"
        )


async def cmd_describe_message(client: ReflectionClient, name: str) -> None:
    info = await client.get_message_info(name)
    print(f"message {info.name} {{")
    for field in info.fields:
        if field.is_required:
            label = "required"
        elif field.is_repeated:
            label = "repeated"
        else:
            label = "optional"
        print(
            f"  {label} {_short_type(field.type_name)} {field.name} = {field.number};"
        )
    print("}")


async def cmd_verify(client: ReflectionClient) -> None:
    info = await client.verify_market_maker_service()
    print("✅ MarketMakerIngestionService is available!")
    print()
    print("   Methods:")
    for method in info.methods:
        if method.client_streaming and method.server_streaming:
            badge = "⇄ "
        elif method.client_streaming:
            badge = "→ "
        elif method.server_streaming:
            badge = "← "
        else:
            badge = "  "
        print(f"     {badge}{method.name}")


async def cmd_inspect(client: ReflectionClient) -> None:
    services = await client.get_all_service_info()
    if not services:
        print("No services found (the server may not expose full reflection metadata).")
        names = await client.list_services()
        if names:
            print("\nAdvertised service names:")
            for name in names:
                print(f"  • {name}")
        return

    print("Server Introspection")
    print("====================\n")
    for svc in services:
        print(f"╭─ {svc.name}")
        print("│")
        for i, method in enumerate(svc.methods):
            is_last = i + 1 == len(svc.methods)
            branch, cont = ("╰─", "  ") if is_last else ("├─", "│ ")
            if method.client_streaming and method.server_streaming:
                streaming = "[bidi-stream] "
            elif method.client_streaming:
                streaming = "[client-stream] "
            elif method.server_streaming:
                streaming = "[server-stream] "
            else:
                streaming = ""
            print(f"{branch} {streaming}{method.name}")
            print(f"{cont}     request:  {_short_type(method.input_type)}")
            print(f"{cont}     response: {_short_type(method.output_type)}")
        print()


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reflection_cli.py",
        description="Explore gRPC services on the RFQv2 Ingestion Service",
    )
    parser.add_argument(
        "-e",
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"gRPC server endpoint (default: {DEFAULT_ENDPOINT})",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("list-services", aliases=["ls"], help="List all gRPC services")
    ds = sub.add_parser(
        "describe-service",
        aliases=["ds"],
        help="Show methods for a service",
    )
    ds.add_argument("name", help="Fully-qualified service name")
    dm = sub.add_parser(
        "describe-message",
        aliases=["dm"],
        help="Show fields of a protobuf message",
    )
    dm.add_argument("name", help="Fully-qualified message name")
    sub.add_parser("verify", help="Verify the MarketMaker service")
    sub.add_parser("inspect", help="Full introspection of all services")
    sub.add_parser("help", help="Print this help message")
    return parser


async def _run(args: argparse.Namespace) -> int:
    print(f"Connecting to {args.endpoint}…\n")
    client = await ReflectionClient.connect(args.endpoint)
    try:
        cmd = args.command
        if cmd in ("list-services", "ls"):
            await cmd_list_services(client)
        elif cmd in ("describe-service", "ds"):
            await cmd_describe_service(client, args.name)
        elif cmd in ("describe-message", "dm"):
            await cmd_describe_message(client, args.name)
        elif cmd == "verify":
            await cmd_verify(client)
        elif cmd == "inspect":
            await cmd_inspect(client)
        else:
            return 0  # help is handled before _run
    finally:
        await client.close()
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command in (None, "help"):
        parser.print_help()
        return

    try:
        sys.exit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
