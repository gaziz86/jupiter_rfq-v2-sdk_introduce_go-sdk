package helpers

import (
	"fmt"

	gosdk "go-sdk"
)

type VolumeTier struct {
	Volume   uint64
	SpreadBP uint64
}

func PriceToDisplay(price uint64, decimals uint32) string {
	if decimals == 0 {
		return fmt.Sprintf("%d", price)
	}
	scale := pow10(decimals)
	whole := price / scale
	fractional := price % scale
	return fmt.Sprintf("%d.%0*d", whole, int(decimals), fractional)
}

func BasisPointsToPercentage(bp uint64) float64 {
	return (float64(bp) / 10_000.0) * 100.0
}

func SpreadBPForVolume(volume uint64, tiers []VolumeTier, fallback uint64) uint64 {
	if len(tiers) == 0 {
		return fallback
	}
	for i := len(tiers) - 1; i >= 0; i-- {
		if volume >= tiers[i].Volume {
			return tiers[i].SpreadBP
		}
	}
	return fallback
}

func ApplySpreadWithImprovement(basePrice, spreadBP, improvementBP uint64) (uint64, uint64) {
	halfSpread := basePrice * spreadBP / (10_000 * 2)
	improvement := basePrice * improvementBP / 10_000

	bid := basePrice + improvement
	if bid > halfSpread {
		bid -= halfSpread
	} else {
		bid = 0
	}

	ask := basePrice + halfSpread
	if ask > improvement {
		ask -= improvement
	} else {
		ask = 0
	}
	return bid, ask
}

func BuildVolumeTierLevels(builder *gosdk.MarketMakerQuoteBuilder, basePrice uint64, tiers []VolumeTier, improvementBP uint64) (*gosdk.MarketMakerQuoteBuilder, uint64, uint64) {
	if builder == nil {
		return nil, 0, 0
	}
	if len(tiers) == 0 {
		bid, ask := ApplySpreadWithImprovement(basePrice, 0, improvementBP)
		builder.BidLevel(1, bid)
		builder.AskLevel(1, ask)
		return builder, bid, ask
	}

	minBid := ^uint64(0)
	maxAsk := uint64(0)
	for _, tier := range tiers {
		if tier.Volume == 0 {
			continue
		}
		bid, ask := ApplySpreadWithImprovement(basePrice, tier.SpreadBP, improvementBP)
		builder.BidLevel(tier.Volume, bid)
		builder.AskLevel(tier.Volume, ask)
		if bid < minBid {
			minBid = bid
		}
		if ask > maxAsk {
			maxAsk = ask
		}
	}

	if minBid == ^uint64(0) {
		minBid = 0
	}
	return builder, minBid, maxAsk
}

func pow10(exp uint32) uint64 {
	if exp == 0 {
		return 1
	}
	v := uint64(1)
	for i := uint32(0); i < exp; i++ {
		v *= 10
	}
	return v
}
