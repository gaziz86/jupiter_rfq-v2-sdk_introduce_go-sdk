# fill-decoder

Decoder and analysis utilities for RFQ v2 `fill_exact_in` transactions on Solana.

Each decoded instruction exposes a `fill_mints` field with the resolved input, output, base, and quote mints, plus labels on all 11 `fill_exact_in` accounts — works for both direct fills and embedded fills inside any Jupiter route variant, including multi-step routes where the RFQ is one leg among many. Mints sitting in address-table lookups appear as `LookupReadonly[N]` placeholders unless an RPC URL is provided to fetch the lookup tables.

## Building the CLI

The `decode-tx` binary requires the `cli` feature:

```bash
cargo build --release --features cli
```

The binary will be at `target/release/decode-tx`.

## Usage

### Decode a base-64 encoded transaction

```bash
decode-tx --base64 <BASE64_DATA>
```

### Fetch and decode by transaction signature

Requires an RPC URL, either via `--rpc-url` or the `RPC_URL` environment variable:

```bash
export RPC_URL=https://api.mainnet-beta.solana.com
decode-tx --tx <SIGNATURE>
```

### Check fill-exclusivity for maker accounts

Verify that specific public keys only appear in fill instructions (not in unrelated instructions):

```bash
decode-tx --tx <SIGNATURE> --check <PUBKEY1> --check <PUBKEY2>
```

### JSON output

Use `--json` for machine-readable output instead of the default human-readable table:

```bash
decode-tx --tx <SIGNATURE> --json
```

Flags can be combined:

```bash
decode-tx --tx <SIGNATURE> --rpc-url <URL> --check <PUBKEY> --json
```

## Options

| Flag | Description |
|------|-------------|
| `--base64 <DATA>` | Base-64 encoded Solana transaction to decode locally |
| `--tx <SIGNATURE>` | Transaction signature to fetch from Solana RPC |
| `--rpc-url <URL>` | Solana RPC URL (overrides `RPC_URL` env var) |
| `--check <PUBKEY>` | Public key to check for fill-exclusivity (repeatable) |
| `--json` | Emit JSON output |
