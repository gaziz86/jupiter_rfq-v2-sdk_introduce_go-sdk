//! Jupiter aggregator instruction decoding.

use borsh::BorshDeserialize;

use crate::analysis::analyze_fill;
use crate::decode::FILL_EXACT_IN_DISCRIMINATOR;
use crate::types::{FillAnalysis, FillExactInInstruction, FillExactInParams, Side};

pub const JUPITER_PROGRAM_ID: &str = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4";
pub const AGGREGATOR_IDL_JSON: &str = include_str!("../idls/aggregator.json");

const ROUTE: [u8; 8] = [229, 23, 203, 151, 122, 227, 173, 42];
const ROUTE_WITH_TOKEN_LEDGER: [u8; 8] = [150, 86, 71, 116, 167, 93, 14, 104];
const EXACT_OUT_ROUTE: [u8; 8] = [208, 51, 239, 151, 123, 43, 237, 92];
const SHARED_ACCOUNTS_ROUTE: [u8; 8] = [193, 32, 155, 51, 65, 214, 156, 129];
const SHARED_ACCOUNTS_EXACT_OUT_ROUTE: [u8; 8] = [176, 209, 105, 168, 154, 125, 69, 62];
const SHARED_ACCOUNTS_ROUTE_WITH_TOKEN_LEDGER: [u8; 8] = [230, 121, 143, 80, 119, 159, 106, 170];
const ROUTE_V2: [u8; 8] = [187, 100, 250, 204, 49, 196, 175, 20];
const EXACT_OUT_ROUTE_V2: [u8; 8] = [157, 138, 184, 82, 21, 244, 243, 36];
const SHARED_ACCOUNTS_ROUTE_V2: [u8; 8] = [209, 152, 83, 147, 124, 254, 216, 233];
const SHARED_ACCOUNTS_EXACT_OUT_ROUTE_V2: [u8; 8] = [53, 96, 229, 202, 216, 187, 250, 24];

// Lenient: ignores trailing bytes. `borsh::from_slice` errors on them, but
// Jupiter routes append a `RemainingAccountsInfo` after the args.
fn deser<T: BorshDeserialize>(bytes: &[u8]) -> Option<T> {
    let mut slice = bytes;
    T::deserialize(&mut slice).ok()
}

#[derive(Debug, Clone, BorshDeserialize)]
#[allow(dead_code)]
struct RemainingAccountsSlice {
    accounts_type: u8,
    length: u8,
}

#[derive(Debug, Clone, BorshDeserialize)]
#[allow(dead_code)]
struct RemainingAccountsInfo {
    slices: Vec<RemainingAccountsSlice>,
}

#[derive(Debug, Clone, BorshDeserialize)]
enum JupSide {
    Bid,
    Ask,
}

#[derive(Debug, Clone, BorshDeserialize)]
#[allow(dead_code)]
enum CandidateSwap {
    HumidiFi {
        swap_id: u64,
        is_base_to_quote: bool,
    },
    TesseraV {
        side: JupSide,
    },
    HumidiFiV2 {
        swap_id: u64,
        is_base_to_quote: bool,
    },
}

// Layout drift in any variant breaks Borsh decoding of the whole
// route_plan — `decode_jupiter_rfq_step_indices` byte-scans as a fallback.
#[derive(Debug, Clone, BorshDeserialize)]
#[allow(dead_code)]
enum Swap {
    Saber,                    // 0
    SaberAddDecimalsDeposit,  // 1
    SaberAddDecimalsWithdraw, // 2
    TokenSwap,                // 3
    Sencha,                   // 4
    Step,                     // 5
    Cropper,                  // 6
    Raydium,                  // 7
    Crema {
        a_to_b: bool,
    }, // 8
    Lifinity,                 // 9
    Mercurial,                // 10
    Cykura,                   // 11
    Serum {
        side: JupSide,
    }, // 12
    MarinadeDeposit,          // 13
    MarinadeUnstake,          // 14
    Aldrin {
        side: JupSide,
    }, // 15
    AldrinV2 {
        side: JupSide,
    }, // 16
    Whirlpool {
        a_to_b: bool,
    }, // 17
    Invariant {
        x_to_y: bool,
    }, // 18
    Meteora,                  // 19
    GooseFX,                  // 20
    DeltaFi {
        stable: bool,
    }, // 21
    Balansol,                 // 22
    MarcoPolo {
        x_to_y: bool,
    }, // 23
    Dradex {
        side: JupSide,
    }, // 24
    LifinityV2,               // 25
    RaydiumClmm,              // 26
    Openbook {
        side: JupSide,
    }, // 27
    Phoenix {
        side: JupSide,
    }, // 28
    Symmetry {
        from_token_id: u64,
        to_token_id: u64,
    }, // 29
    TokenSwapV2,              // 30
    HeliumTreasuryManagementRedeemV0, // 31
    StakeDexStakeWrappedSol,  // 32
    StakeDexSwapViaStake {
        bridge_stake_seed: u32,
    }, // 33
    GooseFXV2,                // 34
    Perps,                    // 35
    PerpsAddLiquidity,        // 36
    PerpsRemoveLiquidity,     // 37
    MeteoraDlmm,              // 38
    OpenBookV2 {
        side: JupSide,
    }, // 39
    RaydiumClmmV2,            // 40
    StakeDexPrefundWithdrawStakeAndDepositStake {
        bridge_stake_seed: u32,
    }, // 41
    Clone {
        pool_index: u8,
        quantity_is_input: bool,
        quantity_is_collateral: bool,
    }, // 42
    SanctumS {
        src_lst_value_calc_accs: u8,
        dst_lst_value_calc_accs: u8,
        src_lst_index: u32,
        dst_lst_index: u32,
    }, // 43
    SanctumSAddLiquidity {
        lst_value_calc_accs: u8,
        lst_index: u32,
    }, // 44
    SanctumSRemoveLiquidity {
        lst_value_calc_accs: u8,
        lst_index: u32,
    }, // 45
    RaydiumCP,                // 46
    WhirlpoolSwapV2 {
        a_to_b: bool,
        remaining_accounts_info: Option<RemainingAccountsInfo>,
    }, // 47
    OneIntro,                 // 48
    PumpWrappedBuy,           // 49
    PumpWrappedSell,          // 50
    PerpsV2,                  // 51
    PerpsV2AddLiquidity,      // 52
    PerpsV2RemoveLiquidity,   // 53
    MoonshotWrappedBuy,       // 54
    MoonshotWrappedSell,      // 55
    StabbleStableSwap,        // 56
    StabbleWeightedSwap,      // 57
    Obric {
        x_to_y: bool,
    }, // 58
    FoxBuyFromEstimatedCost,  // 59
    FoxClaimPartial {
        is_y: bool,
    }, // 60
    SolFi {
        is_quote_to_base: bool,
    }, // 61
    SolayerDelegateNoInit,    // 62
    SolayerUndelegateNoInit,  // 63
    TokenMill {
        side: JupSide,
    }, // 64
    DaosFunBuy,               // 65
    DaosFunSell,              // 66
    ZeroFi,                   // 67
    StakeDexWithdrawWrappedSol, // 68
    VirtualsBuy,              // 69
    VirtualsSell,             // 70
    Perena {
        in_index: u8,
        out_index: u8,
    }, // 71
    PumpSwapBuy,              // 72
    PumpSwapSell,             // 73
    Gamma,                    // 74
    MeteoraDlmmSwapV2 {
        remaining_accounts_info: RemainingAccountsInfo,
    }, // 75
    Woofi,                    // 76
    MeteoraDammV2,            // 77
    MeteoraDynamicBondingCurveSwap, // 78
    StabbleStableSwapV2,      // 79
    StabbleWeightedSwapV2,    // 80
    RaydiumLaunchlabBuy {
        share_fee_rate: u64,
    }, // 81
    RaydiumLaunchlabSell {
        share_fee_rate: u64,
    }, // 82
    BoopdotfunWrappedBuy,     // 83
    BoopdotfunWrappedSell,    // 84
    Plasma {
        side: JupSide,
    }, // 85
    GoonFi {
        is_bid: bool,
        blacklist_bump: u8,
    }, // 86
    HumidiFi {
        swap_id: u64,
        is_base_to_quote: bool,
    }, // 87
    MeteoraDynamicBondingCurveSwapWithRemainingAccounts, // 88
    TesseraV {
        side: JupSide,
    }, // 89
    PumpWrappedBuyV2,         // 90
    PumpWrappedSellV2,        // 91
    PumpSwapBuyV2,            // 92
    PumpSwapSellV2,           // 93
    Heaven {
        a_to_b: bool,
    }, // 94
    SolFiV2 {
        is_quote_to_base: bool,
    }, // 95
    Aquifer,                  // 96
    PumpWrappedBuyV3,         // 97
    PumpWrappedSellV3,        // 98
    PumpSwapBuyV3,            // 99
    PumpSwapSellV3,           // 100
    JupiterLendDeposit,       // 101
    JupiterLendRedeem,        // 102
    DefiTuna {
        a_to_b: bool,
        remaining_accounts_info: Option<RemainingAccountsInfo>,
    }, // 103
    AlphaQ {
        a_to_b: bool,
    }, // 104
    RaydiumV2,                // 105
    SarosDlmm {
        swap_for_y: bool,
    }, // 106
    Futarchy {
        side: JupSide,
    }, // 107
    MeteoraDammV2WithRemainingAccounts, // 108
    Obsidian,                 // 109
    WhaleStreet {
        side: JupSide,
    }, // 110
    DynamicV1 {
        candidate_swaps: Vec<CandidateSwap>,
        best_position: Option<u8>,
    }, // 111
    PumpWrappedBuyV4,         // 112
    PumpWrappedSellV4,        // 113
    CarrotIssue,              // 114
    CarrotRedeem,             // 115
    Manifest {
        side: JupSide,
    }, // 116
    BisonFi {
        a_to_b: bool,
    }, // 117
    HumidiFiV2 {
        swap_id: u64,
        is_base_to_quote: bool,
    }, // 118
    PerenaStar {
        is_mint: bool,
    }, // 119
    JupiterRfqV2 {
        side: JupSide,
        fill_data: Vec<u8>,
    }, // 120
    GoonFiV2 {
        is_bid: bool,
    }, // 121
    Scorch {
        swap_id: u128,
    }, // 122
    VaultLiquidUnstake {
        lst_amounts: [u64; 5],
        seed: u64,
    }, // 123
    XOrca,                    // 124
    Quantum {
        side: JupSide,
    }, // 125
}

#[derive(Debug, Clone, BorshDeserialize)]
#[allow(dead_code)]
struct RoutePlanStep {
    swap: Swap,
    percent: u8,
    input_index: u8,
    output_index: u8,
}

#[derive(Debug, Clone, BorshDeserialize)]
#[allow(dead_code)]
struct RoutePlanStepV2 {
    swap: Swap,
    bps: u16,
    input_index: u8,
    output_index: u8,
}

#[derive(BorshDeserialize)]
struct RouteArgs {
    route_plan: Vec<RoutePlanStep>,
    in_amount: u64,
    #[allow(dead_code)]
    quoted_out_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u8,
}

#[derive(BorshDeserialize)]
struct RouteWithTokenLedgerArgs {
    route_plan: Vec<RoutePlanStep>,
    #[allow(dead_code)]
    quoted_out_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u8,
}

#[derive(BorshDeserialize)]
struct ExactOutRouteArgs {
    route_plan: Vec<RoutePlanStep>,
    #[allow(dead_code)]
    out_amount: u64,
    #[allow(dead_code)]
    quoted_in_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u8,
}

#[derive(BorshDeserialize)]
struct SharedAccountsRouteArgs {
    #[allow(dead_code)]
    id: u8,
    route_plan: Vec<RoutePlanStep>,
    in_amount: u64,
    #[allow(dead_code)]
    quoted_out_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u8,
}

#[derive(BorshDeserialize)]
struct SharedAccountsExactOutRouteArgs {
    #[allow(dead_code)]
    id: u8,
    route_plan: Vec<RoutePlanStep>,
    #[allow(dead_code)]
    out_amount: u64,
    #[allow(dead_code)]
    quoted_in_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u8,
}

#[derive(BorshDeserialize)]
struct SharedAccountsRouteWithTokenLedgerArgs {
    #[allow(dead_code)]
    id: u8,
    route_plan: Vec<RoutePlanStep>,
    #[allow(dead_code)]
    quoted_out_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u8,
}

#[derive(BorshDeserialize)]
struct RouteV2Args {
    in_amount: u64,
    #[allow(dead_code)]
    quoted_out_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u16,
    #[allow(dead_code)]
    positive_slippage_bps: u16,
    route_plan: Vec<RoutePlanStepV2>,
}

#[derive(BorshDeserialize)]
struct ExactOutRouteV2Args {
    #[allow(dead_code)]
    out_amount: u64,
    #[allow(dead_code)]
    quoted_in_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u16,
    #[allow(dead_code)]
    positive_slippage_bps: u16,
    route_plan: Vec<RoutePlanStepV2>,
}

#[derive(BorshDeserialize)]
struct SharedAccountsRouteV2Args {
    #[allow(dead_code)]
    id: u8,
    in_amount: u64,
    #[allow(dead_code)]
    quoted_out_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u16,
    #[allow(dead_code)]
    positive_slippage_bps: u16,
    route_plan: Vec<RoutePlanStepV2>,
}

#[derive(BorshDeserialize)]
struct SharedAccountsExactOutRouteV2Args {
    #[allow(dead_code)]
    id: u8,
    #[allow(dead_code)]
    out_amount: u64,
    #[allow(dead_code)]
    quoted_in_amount: u64,
    #[allow(dead_code)]
    slippage_bps: u16,
    #[allow(dead_code)]
    platform_fee_bps: u16,
    #[allow(dead_code)]
    positive_slippage_bps: u16,
    route_plan: Vec<RoutePlanStepV2>,
}

/// `total_steps == Some(1)` means the RFQ leg is the only step in the
/// route. `None` only when the byte-scan fallback ran and couldn't recover
/// the count.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct JupiterRfqStepInfo {
    pub input_index: u8,
    pub output_index: u8,
    pub total_steps: Option<u32>,
}

pub fn decode_jupiter_rfq_fill(data: &[u8]) -> Option<(FillExactInInstruction, FillAnalysis)> {
    let (steps, in_amount, _) = parse_route_steps(data)?;
    steps
        .iter()
        .find_map(|(side, fill_data, _, _)| try_decode_rfq_fill(side, fill_data, in_amount))
}

pub fn decode_jupiter_rfq_step_indices(data: &[u8]) -> Option<JupiterRfqStepInfo> {
    if let Some((steps, _, total)) = parse_route_steps(data) {
        if let Some((_, _, in_idx, out_idx)) = steps.first() {
            return Some(JupiterRfqStepInfo {
                input_index: *in_idx,
                output_index: *out_idx,
                total_steps: Some(total),
            });
        }
    }
    let (input_index, output_index) = scan_jupiter_rfq_step_indices(data)?;
    let disc: [u8; 8] = data.get(..8)?.try_into().ok()?;
    Some(JupiterRfqStepInfo {
        input_index,
        output_index,
        total_steps: read_route_plan_len(disc, data),
    })
}

fn parse_route_steps(data: &[u8]) -> Option<(Vec<(JupSide, Vec<u8>, u8, u8)>, Option<u64>, u32)> {
    let disc: [u8; 8] = data.get(..8)?.try_into().ok()?;
    let args = &data[8..];
    Some(match disc {
        ROUTE => {
            let a = deser::<RouteArgs>(args)?;
            let total = a.route_plan.len() as u32;
            (
                extract_rfq_steps_v1(&a.route_plan),
                Some(a.in_amount),
                total,
            )
        }
        ROUTE_WITH_TOKEN_LEDGER => {
            let a = deser::<RouteWithTokenLedgerArgs>(args)?;
            let total = a.route_plan.len() as u32;
            (extract_rfq_steps_v1(&a.route_plan), None, total)
        }
        EXACT_OUT_ROUTE => {
            let a = deser::<ExactOutRouteArgs>(args)?;
            let total = a.route_plan.len() as u32;
            (extract_rfq_steps_v1(&a.route_plan), None, total)
        }
        SHARED_ACCOUNTS_ROUTE => {
            let a = deser::<SharedAccountsRouteArgs>(args)?;
            let total = a.route_plan.len() as u32;
            (
                extract_rfq_steps_v1(&a.route_plan),
                Some(a.in_amount),
                total,
            )
        }
        SHARED_ACCOUNTS_EXACT_OUT_ROUTE => {
            let a = deser::<SharedAccountsExactOutRouteArgs>(args)?;
            let total = a.route_plan.len() as u32;
            (extract_rfq_steps_v1(&a.route_plan), None, total)
        }
        SHARED_ACCOUNTS_ROUTE_WITH_TOKEN_LEDGER => {
            let a = deser::<SharedAccountsRouteWithTokenLedgerArgs>(args)?;
            let total = a.route_plan.len() as u32;
            (extract_rfq_steps_v1(&a.route_plan), None, total)
        }
        ROUTE_V2 => {
            let a = deser::<RouteV2Args>(args)?;
            let total = a.route_plan.len() as u32;
            (
                extract_rfq_steps_v2(&a.route_plan),
                Some(a.in_amount),
                total,
            )
        }
        EXACT_OUT_ROUTE_V2 => {
            let a = deser::<ExactOutRouteV2Args>(args)?;
            let total = a.route_plan.len() as u32;
            (extract_rfq_steps_v2(&a.route_plan), None, total)
        }
        SHARED_ACCOUNTS_ROUTE_V2 => {
            let a = deser::<SharedAccountsRouteV2Args>(args)?;
            let total = a.route_plan.len() as u32;
            (
                extract_rfq_steps_v2(&a.route_plan),
                Some(a.in_amount),
                total,
            )
        }
        SHARED_ACCOUNTS_EXACT_OUT_ROUTE_V2 => {
            let a = deser::<SharedAccountsExactOutRouteV2Args>(args)?;
            let total = a.route_plan.len() as u32;
            (extract_rfq_steps_v2(&a.route_plan), None, total)
        }
        _ => return None,
    })
}

// v1: route_plan first in args (+0, or +1 after `id` for shared_*).
// v2: route_plan after a 22-byte fixed prefix (+22, or +23 after `id`).
fn read_route_plan_len(disc: [u8; 8], data: &[u8]) -> Option<u32> {
    let offset: usize = match disc {
        ROUTE | ROUTE_WITH_TOKEN_LEDGER | EXACT_OUT_ROUTE => 8,
        SHARED_ACCOUNTS_ROUTE
        | SHARED_ACCOUNTS_EXACT_OUT_ROUTE
        | SHARED_ACCOUNTS_ROUTE_WITH_TOKEN_LEDGER => 9,
        ROUTE_V2 | EXACT_OUT_ROUTE_V2 => 8 + 22,
        SHARED_ACCOUNTS_ROUTE_V2 | SHARED_ACCOUNTS_EXACT_OUT_ROUTE_V2 => 9 + 22,
        _ => return None,
    };
    let bytes: [u8; 4] = data.get(offset..offset + 4)?.try_into().ok()?;
    Some(u32::from_le_bytes(bytes))
}

fn scan_jupiter_rfq_step_indices(data: &[u8]) -> Option<(u8, u8)> {
    scan_via_fill_disc(data).or_else(|| scan_via_tag_byte(data))
}

// Anchor at FILL_EXACT_IN_DISCRIMINATOR; walk backwards/forwards:
//   [tag=120][side u8][fill_data_len u32][FILL_DISC ...fill_data][bps u16][in u8][out u8]
//   ↑ P-6   ↑ P-5    ↑ P-4..P-1         ↑ P                     ↑ P+L    ↑ P+L+2 ↑ P+L+3
fn scan_via_fill_disc(data: &[u8]) -> Option<(u8, u8)> {
    if data.len() < FILL_EXACT_IN_DISCRIMINATOR.len() + 6 {
        return None;
    }
    for p in 6..data.len().saturating_sub(FILL_EXACT_IN_DISCRIMINATOR.len()) {
        if data[p..p + 8] != FILL_EXACT_IN_DISCRIMINATOR {
            continue;
        }
        let fill_data_len =
            u32::from_le_bytes([data[p - 4], data[p - 3], data[p - 2], data[p - 1]]) as usize;
        if !(8..=1024).contains(&fill_data_len) {
            continue;
        }
        let side = data[p - 5];
        if side > 1 {
            continue;
        }
        if data[p - 6] != 120 {
            continue;
        }
        let fill_data_end = p + fill_data_len;
        if fill_data_end + 4 > data.len() {
            continue;
        }
        let fill_data = &data[p..fill_data_end];
        let jup_side = if side == 0 {
            JupSide::Bid
        } else {
            JupSide::Ask
        };
        if try_decode_rfq_fill(&jup_side, fill_data, None).is_none() {
            continue;
        }
        return Some((data[fill_data_end + 2], data[fill_data_end + 3]));
    }
    None
}

// 0x78 occurs by chance; validate each candidate by decoding fill_data.
// Tries common in_amount offsets for the params-only fill_data layout.
fn scan_via_tag_byte(data: &[u8]) -> Option<(u8, u8)> {
    const JUPITER_RFQ_V2_TAG: u8 = 120;
    let in_amount_hints: [Option<u64>; 3] = [
        None,
        data.get(8..16)
            .and_then(|s| s.try_into().ok())
            .map(u64::from_le_bytes),
        data.get(9..17)
            .and_then(|s| s.try_into().ok())
            .map(u64::from_le_bytes),
    ];

    for i in 0..data.len() {
        if data[i] != JUPITER_RFQ_V2_TAG {
            continue;
        }
        if i + 6 > data.len() {
            break;
        }
        let side = data[i + 1];
        if side > 1 {
            continue;
        }
        let fill_data_len =
            u32::from_le_bytes([data[i + 2], data[i + 3], data[i + 4], data[i + 5]]) as usize;
        if !(16..=1024).contains(&fill_data_len) {
            continue;
        }
        let fill_data_end = i + 6 + fill_data_len;
        if fill_data_end + 4 > data.len() {
            continue;
        }
        let fill_data = &data[i + 6..fill_data_end];
        let jup_side = if side == 0 {
            JupSide::Bid
        } else {
            JupSide::Ask
        };
        let decoded = in_amount_hints
            .iter()
            .any(|hint| try_decode_rfq_fill(&jup_side, fill_data, *hint).is_some());
        if !decoded {
            continue;
        }
        return Some((data[fill_data_end + 2], data[fill_data_end + 3]));
    }
    None
}

fn extract_rfq_steps_v1(plan: &[RoutePlanStep]) -> Vec<(JupSide, Vec<u8>, u8, u8)> {
    plan.iter()
        .filter_map(|step| match &step.swap {
            Swap::JupiterRfqV2 { side, fill_data } => Some((
                side.clone(),
                fill_data.clone(),
                step.input_index,
                step.output_index,
            )),
            _ => None,
        })
        .collect()
}

fn extract_rfq_steps_v2(plan: &[RoutePlanStepV2]) -> Vec<(JupSide, Vec<u8>, u8, u8)> {
    plan.iter()
        .filter_map(|step| match &step.swap {
            Swap::JupiterRfqV2 { side, fill_data } => Some((
                side.clone(),
                fill_data.clone(),
                step.input_index,
                step.output_index,
            )),
            _ => None,
        })
        .collect()
}

fn to_rfq_side(side: &JupSide) -> Side {
    match side {
        JupSide::Bid => Side::Bid,
        JupSide::Ask => Side::Ask,
    }
}

// Three observed fill_data layouts: full instruction, disc + instruction,
// or params-only. The levels_consumed guard rejects noise that happens to
// borsh-deserialise.
fn try_decode_rfq_fill(
    jup_side: &JupSide,
    fill_data: &[u8],
    in_amount: Option<u64>,
) -> Option<(FillExactInInstruction, FillAnalysis)> {
    let side = to_rfq_side(jup_side);

    if let Some(ix) = deser::<FillExactInInstruction>(fill_data) {
        if let Ok(analysis) = analyze_fill(&ix) {
            if analysis.levels_consumed > 0 {
                return Some((ix, analysis));
            }
        }
    }

    if fill_data.len() > 8 {
        if let Some(ix) = deser::<FillExactInInstruction>(&fill_data[8..]) {
            if let Ok(analysis) = analyze_fill(&ix) {
                if analysis.levels_consumed > 0 {
                    return Some((ix, analysis));
                }
            }
        }
    }

    if let Some(params) = deser::<FillExactInParams>(fill_data) {
        let ix = FillExactInInstruction {
            taker_side: side,
            amount_in_atoms: in_amount.unwrap_or(0),
            params,
        };
        if let Ok(analysis) = analyze_fill(&ix) {
            if analysis.levels_consumed > 0 {
                return Some((ix, analysis));
            }
        }
    }

    None
}
