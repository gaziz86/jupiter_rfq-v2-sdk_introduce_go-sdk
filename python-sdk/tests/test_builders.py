"""Tests for :mod:`rfq_sdk.builders`.

Mirrors the validation behaviour of the Rust ``MarketMakerQuoteBuilder``.
"""

import pytest

from rfq_sdk import (
    Cluster,
    MarketMakerQuoteBuilder,
    QuoteHelper,
    TokenPairHelper,
    ValidationError,
)


def _builder():
    return (
        MarketMakerQuoteBuilder.new()
        .maker_id("test-maker")
        .sol_usdc_pair()
        .maker_address("11111111111111111111111111111111")
        .lot_size_base(1000)
        .sequence_number(1)
    )


def test_build_succeeds_with_required_fields():
    quote = (
        _builder()
        .bid_level(1_000_000_000, 150_000_000)
        .ask_level(1_000_000_000, 151_000_000)
        .build()
    )
    assert quote.maker_id == "test-maker"
    assert quote.cluster == Cluster.CLUSTER_MAINNET
    assert len(quote.bid_levels) == 1
    assert len(quote.ask_levels) == 1
    assert quote.bid_levels[0].price == 150_000_000
    assert quote.ask_levels[0].price == 151_000_000
    assert TokenPairHelper.pair_name(quote.token_pair) == "SOL/USDC"


def test_build_uses_default_timestamp_when_unset():
    quote = _builder().bid_level(1, 1).build()
    assert quote.timestamp > 0


def test_build_eth_usdc_pair():
    quote = (
        MarketMakerQuoteBuilder.new()
        .maker_id("test-maker")
        .eth_usdc_pair()
        .maker_address("11111111111111111111111111111111")
        .lot_size_base(1000)
        .sequence_number(1)
        .bid_level(1, 1)
        .build()
    )
    assert quote.token_pair.base_token.symbol == "ETH"
    assert quote.token_pair.quote_token.symbol == "USDC"


def test_missing_maker_id_raises():
    with pytest.raises(ValidationError, match="maker_id is required"):
        (
            MarketMakerQuoteBuilder.new()
            .sol_usdc_pair()
            .maker_address("a")
            .lot_size_base(1)
            .bid_level(1, 1)
            .build()
        )


def test_missing_token_pair_raises():
    with pytest.raises(ValidationError, match="token_pair is required"):
        (
            MarketMakerQuoteBuilder.new()
            .maker_id("m")
            .maker_address("a")
            .lot_size_base(1)
            .bid_level(1, 1)
            .build()
        )


def test_missing_levels_raises():
    with pytest.raises(ValidationError, match="at least one bid or ask level"):
        _builder().build()


def test_zero_price_raises():
    with pytest.raises(ValidationError, match="price cannot be zero"):
        _builder().bid_level(1000, 0).build()


def test_zero_volume_raises():
    with pytest.raises(ValidationError, match="volume cannot be zero"):
        _builder().bid_level(0, 1000).build()


def test_missing_maker_address_raises():
    with pytest.raises(ValidationError, match="maker_address is required"):
        (
            MarketMakerQuoteBuilder.new()
            .maker_id("m")
            .sol_usdc_pair()
            .lot_size_base(1)
            .bid_level(1, 1)
            .build()
        )


def test_missing_lot_size_base_raises():
    with pytest.raises(ValidationError, match="lot_size_base is required"):
        (
            MarketMakerQuoteBuilder.new()
            .maker_id("m")
            .sol_usdc_pair()
            .maker_address("a")
            .bid_level(1, 1)
            .build()
        )


def test_quote_helper_best_bid_and_ask():
    quote = (
        _builder()
        .bid_level(100, 100)
        .bid_level(100, 200)  # best bid
        .ask_level(100, 300)  # best ask
        .ask_level(100, 400)
        .build()
    )
    assert QuoteHelper.best_bid(quote).price == 200
    assert QuoteHelper.best_ask(quote).price == 300
    assert QuoteHelper.spread(quote) == 100


def test_quote_helper_handles_empty_sides():
    quote = _builder().bid_level(100, 100).build()
    assert QuoteHelper.best_bid(quote).price == 100
    assert QuoteHelper.best_ask(quote) is None
    assert QuoteHelper.spread(quote) is None


def test_from_quote_round_trip():
    original = (
        _builder()
        .bid_level(100, 100)
        .ask_level(100, 200)
        .timestamp(123_456_789)
        .build()
    )
    rebuilt = MarketMakerQuoteBuilder.from_quote(original).build()
    assert rebuilt.timestamp == original.timestamp
    assert rebuilt.maker_id == original.maker_id
    assert rebuilt.bid_levels[0].price == 100
