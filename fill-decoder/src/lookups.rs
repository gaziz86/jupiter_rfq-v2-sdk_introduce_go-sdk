//! Address lookup table parsing and placeholder resolution.

use std::collections::HashMap;

use crate::error::FillDecoderError;
use crate::transaction::DecodedMessage;

/// Solana ALT meta header size — addresses start at this byte offset.
const LOOKUP_TABLE_META_SIZE: usize = 56;

/// Map from a lookup-table address (base-58) to its ordered address list.
pub type LookupTableMap = HashMap<String, Vec<String>>;

/// Parse the raw account data of a Solana Address Lookup Table into its
/// stored pubkey list.
pub fn parse_lookup_table_addresses(data: &[u8]) -> crate::Result<Vec<String>> {
    if data.len() < LOOKUP_TABLE_META_SIZE {
        return Err(FillDecoderError::other(format!(
            "lookup table data too short: {} bytes (need at least {})",
            data.len(),
            LOOKUP_TABLE_META_SIZE
        )));
    }
    let addresses = &data[LOOKUP_TABLE_META_SIZE..];
    if !addresses.len().is_multiple_of(32) {
        return Err(FillDecoderError::other(format!(
            "lookup table address region not a multiple of 32 bytes: {}",
            addresses.len()
        )));
    }
    Ok(addresses
        .chunks_exact(32)
        .map(|c| bs58::encode(c).into_string())
        .collect())
}

/// Replace `LookupWritable[N]` / `LookupReadonly[N]` placeholders in the
/// decoded message with actual pubkeys, using the provided table contents.
///
/// Entries that can't be resolved (table missing, or index out of bounds)
/// are left as their placeholder string.
pub fn resolve_address_lookups(msg: &mut DecodedMessage, tables: &LookupTableMap) {
    let mut writable: Vec<Option<String>> = Vec::new();
    let mut readonly: Vec<Option<String>> = Vec::new();
    for lookup in &msg.address_table_lookups {
        let table = tables.get(&lookup.account_key);
        for &idx in &lookup.writable_indexes {
            writable.push(table.and_then(|t| t.get(idx as usize)).cloned());
        }
        for &idx in &lookup.readonly_indexes {
            readonly.push(table.and_then(|t| t.get(idx as usize)).cloned());
        }
    }

    for ix in &mut msg.instructions {
        for acct in &mut ix.accounts {
            if let Some(resolved) = resolve_placeholder(&acct.pubkey, &writable, &readonly) {
                acct.pubkey = resolved;
            }
        }
        if let Some(mints) = &mut ix.fill_mints {
            if let Some(r) = resolve_placeholder(&mints.input_mint, &writable, &readonly) {
                mints.input_mint = r;
            }
            if let Some(r) = resolve_placeholder(&mints.output_mint, &writable, &readonly) {
                mints.output_mint = r;
            }
            if let Some(r) = resolve_placeholder(&mints.base_mint, &writable, &readonly) {
                mints.base_mint = r;
            }
            if let Some(r) = resolve_placeholder(&mints.quote_mint, &writable, &readonly) {
                mints.quote_mint = r;
            }
        }
    }
}

fn resolve_placeholder(
    s: &str,
    writable: &[Option<String>],
    readonly: &[Option<String>],
) -> Option<String> {
    let (slice, is_writable) = if let Some(rest) = s.strip_prefix("LookupWritable[") {
        (rest.strip_suffix(']')?, true)
    } else if let Some(rest) = s.strip_prefix("LookupReadonly[") {
        (rest.strip_suffix(']')?, false)
    } else {
        return None;
    };
    let idx: usize = slice.parse().ok()?;
    let table = if is_writable { writable } else { readonly };
    table.get(idx).cloned().flatten()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_lookup_table_addresses_empty() {
        let data = vec![0u8; LOOKUP_TABLE_META_SIZE];
        let addrs = parse_lookup_table_addresses(&data).unwrap();
        assert!(addrs.is_empty());
    }

    #[test]
    fn test_parse_lookup_table_addresses_two() {
        let mut data = vec![0u8; LOOKUP_TABLE_META_SIZE];
        data.extend_from_slice(&[1u8; 32]);
        data.extend_from_slice(&[2u8; 32]);
        let addrs = parse_lookup_table_addresses(&data).unwrap();
        assert_eq!(addrs.len(), 2);
        assert_eq!(addrs[0], bs58::encode([1u8; 32]).into_string());
        assert_eq!(addrs[1], bs58::encode([2u8; 32]).into_string());
    }

    #[test]
    fn test_parse_lookup_table_too_short() {
        let data = vec![0u8; 10];
        assert!(parse_lookup_table_addresses(&data).is_err());
    }

    #[test]
    fn test_parse_lookup_table_misaligned() {
        let mut data = vec![0u8; LOOKUP_TABLE_META_SIZE];
        data.extend_from_slice(&[1u8; 31]);
        assert!(parse_lookup_table_addresses(&data).is_err());
    }

    #[test]
    fn test_resolve_placeholder_basic() {
        let writable = vec![Some("AAA".to_string()), None];
        let readonly = vec![Some("BBB".to_string())];
        assert_eq!(
            resolve_placeholder("LookupWritable[0]", &writable, &readonly).as_deref(),
            Some("AAA")
        );
        assert_eq!(
            resolve_placeholder("LookupReadonly[0]", &writable, &readonly).as_deref(),
            Some("BBB")
        );
        // Unresolvable: index out of bounds
        assert!(resolve_placeholder("LookupWritable[5]", &writable, &readonly).is_none());
        // Unresolvable: table missing entry
        assert!(resolve_placeholder("LookupWritable[1]", &writable, &readonly).is_none());
        // Not a placeholder
        assert!(resolve_placeholder("SomeRealPubkey", &writable, &readonly).is_none());
    }
}
