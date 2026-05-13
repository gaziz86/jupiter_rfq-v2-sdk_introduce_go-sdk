package gosdk

import (
	"fmt"
	"strings"
	"time"

	"go-sdk/marketmakerpb"

	"google.golang.org/protobuf/proto"
)

type (
	Cluster                  = marketmakerpb.Cluster
	GetAllOrderbooksResponse = marketmakerpb.GetAllOrderbooksResponse
	GetQuotesResponse        = marketmakerpb.GetQuotesResponse
	MarketMakerQuote         = marketmakerpb.MarketMakerQuote
	MarketMakerSwap          = marketmakerpb.MarketMakerSwap
	Orderbook                = marketmakerpb.Orderbook
	PriceLevel               = marketmakerpb.PriceLevel
	QuoteUpdate              = marketmakerpb.QuoteUpdate
	SequenceNumberResponse   = marketmakerpb.SequenceNumberResponse
	SwapMessageType          = marketmakerpb.SwapMessageType
	SwapUpdate               = marketmakerpb.SwapUpdate
	Token                    = marketmakerpb.Token
	TokenPair                = marketmakerpb.TokenPair
	UpdateType               = marketmakerpb.UpdateType
	PairConfig               struct {
		Name             string
		TokenPair        *TokenPair
		MinTradeSizeBase uint64
	}
)

const (
	ClusterUnspecified Cluster = marketmakerpb.Cluster_CLUSTER_UNSPECIFIED
	ClusterMainnet     Cluster = marketmakerpb.Cluster_CLUSTER_MAINNET
	ClusterDevnet      Cluster = marketmakerpb.Cluster_CLUSTER_DEVNET

	UpdateTypeUnspecified UpdateType = marketmakerpb.UpdateType_UPDATE_TYPE_UNSPECIFIED
	UpdateTypeNew         UpdateType = marketmakerpb.UpdateType_UPDATE_TYPE_NEW
	UpdateTypeUpdated     UpdateType = marketmakerpb.UpdateType_UPDATE_TYPE_UPDATED
	UpdateTypeExpired     UpdateType = marketmakerpb.UpdateType_UPDATE_TYPE_EXPIRED
	UpdateTypeRejected    UpdateType = marketmakerpb.UpdateType_UPDATE_TYPE_REJECTED

	SwapTypePing               SwapMessageType = marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_PING
	SwapTypePong               SwapMessageType = marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_PONG
	SwapTypeConnectionReady    SwapMessageType = marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_CONNECTION_READY
	SwapTypeSwapAvailable      SwapMessageType = marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_SWAP_AVAILABLE
	SwapTypeSwapSubmit         SwapMessageType = marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_SWAP_SUBMIT
	SwapTypeTransactionConfirm SwapMessageType = marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_TRANSACTION_CONFIRMED
	SwapTypeError              SwapMessageType = marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_ERROR
)

type ClientConfig struct {
	Endpoint         string
	Timeout          time.Duration
	MaxRetries       int
	StreamBufferSize int
	AuthToken        string
}

func DefaultClientConfig(endpoint string) ClientConfig {
	return ClientConfig{
		Endpoint:         endpoint,
		Timeout:          time.Duration(DefaultTimeoutSeconds) * time.Second,
		MaxRetries:       3,
		StreamBufferSize: DefaultChannelBufferSize,
	}
}

func SolUSDC() *TokenPair {
	return &TokenPair{
		BaseToken: &Token{
			Address:  proto.String("So11111111111111111111111111111111111111112"),
			Decimals: proto.Uint32(9),
			Symbol:   proto.String("SOL"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
		QuoteToken: &Token{
			Address:  proto.String("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
			Decimals: proto.Uint32(6),
			Symbol:   proto.String("USDC"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
	}
}

func SolUSDT() *TokenPair {
	return &TokenPair{
		BaseToken: &Token{
			Address:  proto.String("So11111111111111111111111111111111111111112"),
			Decimals: proto.Uint32(9),
			Symbol:   proto.String("SOL"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
		QuoteToken: &Token{
			Address:  proto.String("Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"),
			Decimals: proto.Uint32(6),
			Symbol:   proto.String("USDT"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
	}
}

func EthUSDC() *TokenPair {
	return &TokenPair{
		BaseToken: &Token{
			Address:  proto.String("7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs"),
			Decimals: proto.Uint32(8),
			Symbol:   proto.String("ETH"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
		QuoteToken: &Token{
			Address:  proto.String("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
			Decimals: proto.Uint32(6),
			Symbol:   proto.String("USDC"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
	}
}

var knownPairConfigs = map[string]PairConfig{
	"SOL/USDC": {
		Name:      "SOL/USDC",
		TokenPair: SolUSDC(),
	},
	"SOL/USDT": {
		Name:      "SOL/USDT",
		TokenPair: SolUSDT(),
	},
	"ETH/USDC": {
		Name:      "ETH/USDC",
		TokenPair: EthUSDC(),
	},
}

func ResolvePairConfig(name string) (PairConfig, error) {
	normalized := normalizePairName(name)
	cfg, ok := knownPairConfigs[normalized]
	if !ok {
		return PairConfig{}, fmt.Errorf("unsupported pair %q", name)
	}
	cfg.MinTradeSizeBase = deriveMinTradeSizeBase(cfg.TokenPair)
	if cfg.MinTradeSizeBase == 0 {
		return PairConfig{}, fmt.Errorf("pair %s is missing min trade size", cfg.Name)
	}
	cfg.TokenPair = CloneTokenPair(cfg.TokenPair)
	return cfg, nil
}

func deriveMinTradeSizeBase(pair *TokenPair) uint64 {
	if pair == nil || pair.GetBaseToken() == nil || pair.GetQuoteToken() == nil {
		return 0
	}
	baseDecimals := pair.GetBaseToken().GetDecimals()
	quoteDecimals := pair.GetQuoteToken().GetDecimals()
	if baseDecimals <= quoteDecimals {
		return 1
	}
	exp := baseDecimals - quoteDecimals
	if exp >= 20 {
		return 0
	}
	minTrade := uint64(1)
	for i := uint32(0); i < exp; i++ {
		minTrade *= 10
	}
	return minTrade
}

func normalizePairName(name string) string {
	replacer := strings.NewReplacer("-", "/", "_", "/", " ", "")
	return strings.ToUpper(replacer.Replace(strings.TrimSpace(name)))
}

func PairName(pair *TokenPair) string {
	if pair == nil || pair.BaseToken == nil || pair.QuoteToken == nil {
		return ""
	}
	return fmt.Sprintf("%s/%s", pair.BaseToken.GetSymbol(), pair.QuoteToken.GetSymbol())
}

func CloneTokenPair(pair *TokenPair) *TokenPair {
	if pair == nil {
		return nil
	}
	clone, ok := proto.Clone(pair).(*TokenPair)
	if !ok {
		return nil
	}
	return clone
}

func BestBid(quote *MarketMakerQuote) *PriceLevel {
	if quote == nil || len(quote.BidLevels) == 0 {
		return nil
	}
	best := quote.BidLevels[0]
	for _, lvl := range quote.BidLevels[1:] {
		if lvl.GetPrice() > best.GetPrice() {
			best = lvl
		}
	}
	return best
}

func BestAsk(quote *MarketMakerQuote) *PriceLevel {
	if quote == nil || len(quote.AskLevels) == 0 {
		return nil
	}
	best := quote.AskLevels[0]
	for _, lvl := range quote.AskLevels[1:] {
		if lvl.GetPrice() < best.GetPrice() {
			best = lvl
		}
	}
	return best
}

func Spread(quote *MarketMakerQuote) (uint64, bool) {
	bid := BestBid(quote)
	ask := BestAsk(quote)
	if bid == nil || ask == nil || ask.GetPrice() < bid.GetPrice() {
		return 0, false
	}
	return ask.GetPrice() - bid.GetPrice(), true
}

func IsQuoteExpired(quote *MarketMakerQuote, now time.Time) bool {
	if quote == nil {
		return true
	}
	nowMicros := uint64(now.UnixMicro())
	expiryMicros := quote.GetQuoteExpiryTime() * 1_000_000
	return nowMicros > quote.GetTimestamp()+expiryMicros
}
