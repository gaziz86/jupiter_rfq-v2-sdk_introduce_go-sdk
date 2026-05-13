package gosdk

import (
	"time"

	"google.golang.org/protobuf/proto"
)

type MarketMakerQuoteBuilder struct {
	makerID         string
	cluster         Cluster
	tokenPair       *TokenPair
	bidLevels       []*PriceLevel
	askLevels       []*PriceLevel
	quoteExpiryTime uint64
	timestamp       uint64
	hasTimestamp    bool
	sequenceNumber  uint64
	hasSequence     bool
	makerAddress    string
	lotSizeBase     uint64
	hasLotSize      bool
}

func NewMarketMakerQuoteBuilder() *MarketMakerQuoteBuilder {
	return &MarketMakerQuoteBuilder{
		cluster:         ClusterMainnet,
		quoteExpiryTime: 30,
	}
}

func (b *MarketMakerQuoteBuilder) MakerID(makerID string) *MarketMakerQuoteBuilder {
	b.makerID = makerID
	return b
}

func (b *MarketMakerQuoteBuilder) Cluster(cluster Cluster) *MarketMakerQuoteBuilder {
	b.cluster = cluster
	return b
}

func (b *MarketMakerQuoteBuilder) TokenPair(tokenPair *TokenPair) *MarketMakerQuoteBuilder {
	b.tokenPair = tokenPair
	return b
}

func (b *MarketMakerQuoteBuilder) SolUSDCPair() *MarketMakerQuoteBuilder {
	b.tokenPair = SolUSDC()
	return b
}

func (b *MarketMakerQuoteBuilder) EthUSDCPair() *MarketMakerQuoteBuilder {
	b.tokenPair = EthUSDC()
	return b
}

func (b *MarketMakerQuoteBuilder) BidLevel(volume, price uint64) *MarketMakerQuoteBuilder {
	b.bidLevels = append(b.bidLevels, &PriceLevel{Volume: proto.Uint64(volume), Price: proto.Uint64(price)})
	return b
}

func (b *MarketMakerQuoteBuilder) AskLevel(volume, price uint64) *MarketMakerQuoteBuilder {
	b.askLevels = append(b.askLevels, &PriceLevel{Volume: proto.Uint64(volume), Price: proto.Uint64(price)})
	return b
}

// ExpiryTimeSecs sets quote expiry duration in seconds.
func (b *MarketMakerQuoteBuilder) ExpiryTimeSecs(secs uint64) *MarketMakerQuoteBuilder {
	b.quoteExpiryTime = secs
	return b
}

// ExpiryTimeMicros is kept for backward compatibility.
// The wire field is seconds, so micros are converted to seconds (rounded up).
func (b *MarketMakerQuoteBuilder) ExpiryTimeMicros(micros uint64) *MarketMakerQuoteBuilder {
	if micros == 0 {
		b.quoteExpiryTime = 0
		return b
	}
	b.quoteExpiryTime = (micros + 1_000_000 - 1) / 1_000_000
	return b
}

func (b *MarketMakerQuoteBuilder) TimestampMicros(ts uint64) *MarketMakerQuoteBuilder {
	b.timestamp = ts
	b.hasTimestamp = true
	return b
}

func (b *MarketMakerQuoteBuilder) SequenceNumber(seq uint64) *MarketMakerQuoteBuilder {
	b.sequenceNumber = seq
	b.hasSequence = true
	return b
}

func (b *MarketMakerQuoteBuilder) MakerAddress(addr string) *MarketMakerQuoteBuilder {
	b.makerAddress = addr
	return b
}

// LotSizeBase sets the protocol lot_size_base field, which represents the
// minimum trade size in base-token atomic units.
func (b *MarketMakerQuoteBuilder) LotSizeBase(minTradeSizeBase uint64) *MarketMakerQuoteBuilder {
	b.lotSizeBase = minTradeSizeBase
	b.hasLotSize = true
	return b
}

func (b *MarketMakerQuoteBuilder) Build() (*MarketMakerQuote, error) {
	if b.makerID == "" {
		return nil, newError(ErrorKindValidation, "maker_id is required", nil)
	}
	if b.tokenPair == nil {
		return nil, newError(ErrorKindValidation, "token_pair is required", nil)
	}
	if len(b.bidLevels) == 0 && len(b.askLevels) == 0 {
		return nil, newError(ErrorKindValidation, "at least one bid or ask level is required", nil)
	}
	for _, lvl := range append(b.bidLevels, b.askLevels...) {
		if lvl.GetPrice() == 0 {
			return nil, newError(ErrorKindValidation, "price cannot be zero", nil)
		}
		if lvl.GetVolume() == 0 {
			return nil, newError(ErrorKindValidation, "volume cannot be zero", nil)
		}
	}
	if b.makerAddress == "" {
		return nil, newError(ErrorKindValidation, "maker_address is required", nil)
	}
	if !b.hasLotSize {
		return nil, newError(ErrorKindValidation, "lot_size_base is required", nil)
	}

	ts := b.timestamp
	if !b.hasTimestamp {
		ts = uint64(time.Now().UnixMicro())
	}

	seq := uint64(1)
	if b.hasSequence {
		seq = b.sequenceNumber
	}

	return &MarketMakerQuote{
		Timestamp:       proto.Uint64(ts),
		SequenceNumber:  proto.Uint64(seq),
		QuoteExpiryTime: proto.Uint64(b.quoteExpiryTime),
		MakerId:         proto.String(b.makerID),
		MakerAddress:    proto.String(b.makerAddress),
		LotSizeBase:     proto.Uint64(b.lotSizeBase),
		Cluster:         b.cluster.Enum(),
		TokenPair:       CloneTokenPair(b.tokenPair),
		BidLevels:       b.bidLevels,
		AskLevels:       b.askLevels,
	}, nil
}
