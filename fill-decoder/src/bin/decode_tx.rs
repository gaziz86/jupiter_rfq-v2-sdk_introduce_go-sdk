//! CLI tool for decoding RFQ v2 `fill_exact_in` transactions.

use clap::Parser;

#[derive(Parser)]
#[command(
    name = "decode-tx",
    about = "Decode RFQ v2 fill_exact_in transactions from Solana",
    long_about = "Decode and analyse RFQ v2 fill_exact_in instructions embedded \
                  in Solana transactions.  Supports direct base-64 decoding, \
                  fetching from an RPC node, fill-exclusivity validation, and \
                  machine-readable JSON output."
)]
struct Cli {
    /// Base-64 encoded Solana transaction (with signatures) to decode locally.
    #[arg(long, group = "input")]
    base64: Option<String>,

    /// Hidden backward-compatible alias for --base64.
    #[arg(long, group = "input", hide = true)]
    message_hash: Option<String>,

    /// Transaction signature to fetch from Solana RPC and decode.
    /// Requires the RPC_URL environment variable or --rpc-url.
    #[arg(long, group = "input")]
    tx: Option<String>,

    /// Solana RPC URL (overrides the RPC_URL env var).
    #[arg(long, env = "RPC_URL")]
    rpc_url: Option<String>,

    /// Public key(s) to check for fill-exclusivity.
    /// May be repeated: --check <PK1> --check <PK2>
    #[arg(long = "check", value_name = "PUBKEY")]
    check_keys: Vec<String>,

    /// Emit machine-readable JSON instead of the human-readable table.
    #[arg(long)]
    json: bool,
}

mod rpc {
    use serde::{Deserialize, Serialize};

    #[derive(Serialize)]
    pub struct Request {
        pub jsonrpc: &'static str,
        pub id: u64,
        pub method: &'static str,
        pub params: serde_json::Value,
    }

    #[derive(Deserialize)]
    pub struct Response<T> {
        pub result: Option<T>,
        pub error: Option<RpcError>,
    }

    #[derive(Deserialize)]
    pub struct RpcError {
        pub code: i64,
        pub message: String,
    }

    #[derive(Deserialize)]
    pub struct TransactionResult {
        /// `[data, encoding]` – we request `"base64"`.
        pub transaction: (String, String),
    }

    #[derive(Deserialize)]
    pub struct AccountsResult {
        pub value: Vec<Option<AccountInfo>>,
    }

    #[derive(Deserialize)]
    pub struct AccountInfo {
        /// `[data, encoding]` – we request `"base64"`.
        pub data: (String, String),
    }
}

/// Fetch a transaction by signature from a Solana JSON-RPC endpoint.
async fn fetch_transaction_base64(rpc_url: &str, signature: &str) -> Result<String, String> {
    let client = reqwest::Client::new();

    let body = rpc::Request {
        jsonrpc: "2.0",
        id: 1,
        method: "getTransaction",
        params: serde_json::json!([
            signature,
            {
                "encoding": "base64",
                "maxSupportedTransactionVersion": 0
            }
        ]),
    };

    let resp = client
        .post(rpc_url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("HTTP request failed: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("RPC returned HTTP {}", resp.status()));
    }

    let rpc_resp: rpc::Response<rpc::TransactionResult> = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse RPC response: {e}"))?;

    if let Some(err) = rpc_resp.error {
        return Err(format!("RPC error ({}): {}", err.code, err.message));
    }

    let result = rpc_resp
        .result
        .ok_or_else(|| "RPC returned null result – transaction not found".to_string())?;

    Ok(result.transaction.0)
}

/// Fetch the address-lookup-table account data for each of the given addresses
/// and parse them into pubkey lists.
async fn fetch_lookup_tables(
    rpc_url: &str,
    addresses: &[String],
) -> Result<fill_decoder::LookupTableMap, String> {
    use base64::{engine::general_purpose::STANDARD, Engine as _};

    if addresses.is_empty() {
        return Ok(fill_decoder::LookupTableMap::new());
    }

    let client = reqwest::Client::new();
    let body = rpc::Request {
        jsonrpc: "2.0",
        id: 1,
        method: "getMultipleAccounts",
        params: serde_json::json!([addresses, { "encoding": "base64" }]),
    };

    let resp = client
        .post(rpc_url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("HTTP request failed: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("RPC returned HTTP {}", resp.status()));
    }

    let rpc_resp: rpc::Response<rpc::AccountsResult> = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse RPC response: {e}"))?;

    if let Some(err) = rpc_resp.error {
        return Err(format!("RPC error ({}): {}", err.code, err.message));
    }
    let result = rpc_resp
        .result
        .ok_or_else(|| "RPC returned null result for getMultipleAccounts".to_string())?;

    let mut map = fill_decoder::LookupTableMap::new();
    for (addr, info) in addresses.iter().zip(result.value.into_iter()) {
        let Some(info) = info else { continue };
        let raw = match STANDARD.decode(&info.data.0) {
            Ok(b) => b,
            Err(e) => {
                eprintln!("warning: failed to base64-decode lookup table {addr}: {e}");
                continue;
            }
        };
        match fill_decoder::parse_lookup_table_addresses(&raw) {
            Ok(addrs) => {
                map.insert(addr.clone(), addrs);
            }
            Err(e) => {
                eprintln!("warning: failed to parse lookup table {addr}: {e}");
            }
        }
    }
    Ok(map)
}

// The lib types intentionally don't pull in serde, so we build JSON manually.

fn fill_to_json(
    ix: &fill_decoder::FillExactInInstruction,
    analysis: &fill_decoder::FillAnalysis,
) -> serde_json::Value {
    serde_json::json!({
        "taker_side": format!("{}", ix.taker_side),
        "amount_in_atoms": ix.amount_in_atoms,
        "expire_at": ix.params.expire_at,
        "tick_size_qpb": ix.params.tick_size_qpb,
        "lot_size_base": ix.params.lot_size_base,
        "levels": ix.params.levels.iter().map(|l| serde_json::json!({
            "px_ticks": l.px_ticks,
            "qty_lots": l.qty_lots,
        })).collect::<Vec<_>>(),
        "analysis": {
            "amount_spent_atoms": analysis.amount_spent_atoms,
            "amount_out_atoms": analysis.amount_out_atoms,
            "vwap_ticks": analysis.vwap_ticks,
            "levels_consumed": analysis.levels_consumed,
            "total_lots_filled": analysis.total_lots_filled,
            "effective_price": analysis.effective_price(),
        }
    })
}

fn exclusivity_to_json(report: &fill_decoder::ExclusivityReport) -> serde_json::Value {
    serde_json::json!({
        "pubkey": report.pubkey,
        "is_exclusive": report.is_exclusive(),
        "fill_instruction_indices": report.fill_instruction_indices,
        "non_fill_instruction_indices": report.non_fill_instruction_indices,
    })
}

fn tx_to_json(
    tx: &fill_decoder::DecodedTransaction,
    exclusivity: &[fill_decoder::ExclusivityReport],
) -> serde_json::Value {
    let fills: Vec<serde_json::Value> = tx
        .message
        .instructions
        .iter()
        .filter_map(|ix| {
            let (fill_ix, analysis) = ix.fill.as_ref()?;
            let accounts: Vec<serde_json::Value> = ix
                .accounts
                .iter()
                .map(|a| {
                    let mut m = serde_json::json!({
                        "index": a.index,
                        "pubkey": a.pubkey,
                        "is_signer": a.is_signer,
                        "is_writable": a.is_writable,
                    });
                    if let Some(label) = &a.label {
                        m["label"] = serde_json::Value::String(label.clone());
                    }
                    m
                })
                .collect();
            let mut entry = serde_json::json!({
                "instruction_index": ix.instruction_index,
                "program_id": ix.program_id,
                "accounts": accounts,
                "fill": fill_to_json(fill_ix, analysis),
            });
            if let Some(mints) = &ix.fill_mints {
                entry["mints"] = serde_json::json!({
                    "input_mint": mints.input_mint,
                    "output_mint": mints.output_mint,
                    "base_mint": mints.base_mint,
                    "quote_mint": mints.quote_mint,
                });
            }
            Some(entry)
        })
        .collect();

    let mut root = serde_json::json!({
        "signatures": tx.signatures,
        "message_version": format!("{}", tx.message.version),
        "num_instructions": tx.message.instructions.len(),
        "fills": fills,
    });

    if !exclusivity.is_empty() {
        root["exclusivity"] =
            serde_json::Value::Array(exclusivity.iter().map(exclusivity_to_json).collect());
    }

    root
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    let b64 = if let Some(b64) = cli.base64.or(cli.message_hash) {
        b64
    } else if let Some(sig) = cli.tx {
        let rpc_url = cli.rpc_url.as_deref().unwrap_or_else(|| {
            eprintln!("Error: --tx requires an RPC URL. Set RPC_URL env var or pass --rpc-url");
            std::process::exit(1);
        });
        eprintln!("Fetching tx {} from {} …", sig, rpc_url);
        match fetch_transaction_base64(rpc_url, &sig).await {
            Ok(data) => data,
            Err(e) => {
                eprintln!("Failed to fetch transaction: {e}");
                std::process::exit(1);
            }
        }
    } else {
        eprintln!("Error: provide --base64 <DATA> or --tx <SIGNATURE>");
        std::process::exit(1);
    };

    let mut tx = match fill_decoder::decode_transaction_base64(&b64) {
        Ok(tx) => tx,
        Err(e) => {
            eprintln!("Failed to decode transaction: {e}");
            std::process::exit(1);
        }
    };

    // Resolve LookupReadonly[N] / LookupWritable[N] placeholders if we have
    // an RPC URL and the message references any address lookup tables.
    if let Some(rpc_url) = cli.rpc_url.as_deref() {
        let table_addresses: Vec<String> = tx
            .message
            .address_table_lookups
            .iter()
            .map(|l| l.account_key.clone())
            .collect();
        if !table_addresses.is_empty() {
            match fetch_lookup_tables(rpc_url, &table_addresses).await {
                Ok(tables) => fill_decoder::resolve_address_lookups(&mut tx.message, &tables),
                Err(e) => {
                    eprintln!("warning: failed to fetch lookup tables, leaving placeholders: {e}")
                }
            }
        }
    }

    let exclusivity: Vec<fill_decoder::ExclusivityReport> = if !cli.check_keys.is_empty() {
        let keys: Vec<&str> = cli.check_keys.iter().map(|s| s.as_str()).collect();
        fill_decoder::check_fill_exclusivity_multi(&tx.message, &keys)
    } else {
        Vec::new()
    };

    if cli.json {
        let json = tx_to_json(&tx, &exclusivity);
        println!("{}", serde_json::to_string_pretty(&json).unwrap());
    } else {
        println!("{tx}");

        if !exclusivity.is_empty() {
            println!("=== Fill Exclusivity ===");
            for report in &exclusivity {
                println!("  {report}");
            }
        }
    }
}
