//! Scan raw instruction data for an embedded `fill_exact_in` argument pattern.

use std::io::Cursor;

use borsh::BorshDeserialize;

use crate::analysis::{analyze_fill, is_params_plausible};
use crate::types::{FillAnalysis, FillExactInInstruction, FillExactInParams, Side};

/// Scan raw instruction data for an embedded `fill_exact_in` argument pattern.
pub fn scan_for_embedded_fill(data: &[u8]) -> Option<(FillExactInInstruction, FillAnalysis)> {
    // Minimum full instruction: side(1) + amount(8) + params(24 + 4 + 16) = 53
    if data.len() < 53 {
        return None;
    }

    // Best-effort: amount_in_atoms lives at offset 8 (after the 8-byte
    // discriminator) in typical Jupiter CPI instruction data.
    let amount_in = if data.len() >= 16 {
        u64::from_le_bytes(data[8..16].try_into().unwrap())
    } else {
        0
    };

    let mut best: Option<(FillExactInInstruction, FillAnalysis)> = None;

    // Scan for u32 values that could be a levels-vector length.
    for pos in 16..data.len().saturating_sub(20) {
        let num_levels = u32::from_le_bytes(data[pos..pos + 4].try_into().ok()?) as usize;
        if num_levels == 0 || num_levels > 20 {
            continue;
        }
        if pos + 4 + num_levels * 16 > data.len() {
            continue;
        }

        // ── Strategy 1: full FillExactInInstruction via Borsh ────────────
        // Borsh layout before the levels vec u32:
        //   side(1) + amount_in(8) + expire_at(8) + tick_size(8) + lot_size(8) = 33
        if pos >= 33 {
            let start = pos - 33;
            let mut cursor = Cursor::new(&data[start..]);
            if let Ok(ix) = FillExactInInstruction::deserialize_reader(&mut cursor) {
                if is_plausible(&ix) {
                    if let Ok(analysis) = analyze_fill(&ix) {
                        if analysis.levels_consumed > 0 {
                            if analysis.amount_spent_atoms == ix.amount_in_atoms {
                                return Some((ix, analysis));
                            }
                            if best.is_none() {
                                best = Some((ix, analysis));
                            }
                        }
                    }
                }
            }
        }

        // ── Strategy 2: FillExactInParams only, infer side + amount ──────
        // Borsh layout: expire_at(8) + tick_size(8) + lot_size(8) = 24 before vec
        if pos >= 24 {
            let start = pos - 24;
            let mut cursor = Cursor::new(&data[start..]);
            if let Ok(params) = FillExactInParams::deserialize_reader(&mut cursor) {
                if !is_params_plausible(&params) {
                    continue;
                }
                for &side in &[Side::Bid, Side::Ask] {
                    let ix = FillExactInInstruction {
                        taker_side: side,
                        amount_in_atoms: amount_in,
                        params: params.clone(),
                    };
                    if let Ok(analysis) = analyze_fill(&ix) {
                        if analysis.levels_consumed > 0 {
                            if analysis.amount_spent_atoms == amount_in {
                                return Some((ix, analysis));
                            }
                            if best.is_none() {
                                best = Some((ix, analysis));
                            }
                        }
                    }
                }
            }
        }
    }

    best
}

fn is_plausible(ix: &FillExactInInstruction) -> bool {
    ix.amount_in_atoms > 0 && is_params_plausible(&ix.params)
}
