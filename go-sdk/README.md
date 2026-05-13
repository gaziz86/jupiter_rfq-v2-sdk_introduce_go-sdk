# Jupiter RFQ v2 Go SDK

Go SDK for interacting with Jupiter's RFQ (Request for Quote) v2.

Mirrors the Rust [`market-maker-client-sdk`](../rust-sdk) crate so the two SDKs
share the same shape, naming, and feature set.

## Installation

Go protobuf stubs are generated locally from
[`../protos/market_maker.proto`](../protos/market_maker.proto).

After cloning:

```bash
cd go-sdk
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.11
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.5.1
./scripts/generate_protos.sh
go test ./...
```

Re-run `./scripts/generate_protos.sh` whenever the `.proto` file changes.

## Examples

Check out the `examples/` directory for complete examples:

- [`production_streaming/main.go`](examples/production_streaming/main.go)
- [`deploy_spl_token/main.go`](examples/deploy_spl_token/main.go)

Run an example:

```bash
go run ./examples/production_streaming
```

## Tests

```bash
go test ./...
```

## Requirements

Go 1.24+. Dependencies are managed by `go.mod`.

## License

MIT
