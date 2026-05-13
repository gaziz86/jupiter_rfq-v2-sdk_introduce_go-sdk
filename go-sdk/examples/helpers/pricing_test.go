package helpers

import (
	"testing"

	gosdk "go-sdk"
)

func TestPriceToDisplay(t *testing.T) {
	got := PriceToDisplay(123456789, 6)
	if got != "123.456789" {
		t.Fatalf("unexpected display: %s", got)
	}
}

func TestBuildVolumeTierLevels(t *testing.T) {
	builder := gosdk.NewMarketMakerQuoteBuilder().
		MakerID("maker").
		MakerAddress("addr").
		LotSizeBase(1).
		TokenPair(gosdk.SolUSDC())

	tiers := []VolumeTier{
		{Volume: 100, SpreadBP: 10},
		{Volume: 200, SpreadBP: 20},
	}
	builder, minBid, maxAsk := BuildVolumeTierLevels(builder, 1_000_000, tiers, 7)
	if builder == nil {
		t.Fatalf("expected non-nil builder")
	}
	quote, err := builder.Build()
	if err != nil {
		t.Fatalf("build failed: %v", err)
	}
	if len(quote.GetBidLevels()) != 2 || len(quote.GetAskLevels()) != 2 {
		t.Fatalf("expected 2 levels per side, got %d bids and %d asks", len(quote.GetBidLevels()), len(quote.GetAskLevels()))
	}
	if minBid == 0 || maxAsk == 0 {
		t.Fatalf("expected non-zero minBid/maxAsk, got %d/%d", minBid, maxAsk)
	}
}
