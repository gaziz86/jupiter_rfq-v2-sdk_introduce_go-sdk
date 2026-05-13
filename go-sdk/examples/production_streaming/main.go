package main

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	gosdk "go-sdk"
	"go-sdk/examples/helpers"

	"github.com/gagliardetto/solana-go"
	"google.golang.org/protobuf/proto"
)

const (
	priceDecimals      = uint32(6)
	solDecimals        = uint32(9)
	splTokenDecimals   = uint32(6)
	priceScale         = uint64(1_000_000)
	solScale           = uint64(1_000_000_000)
	priceImprovementBP = uint64(7)
	streamCloseTimeout = 5 * time.Second
	shutdownWaitTime   = 10 * time.Second
	logMainPrefix      = "[Main]"
	logConfigPrefix    = "[Config]"
	logPricePrefix     = "[Price]"
	logQuotePrefix     = "[Quote]"
	logQuoteAckPrefix  = "[QuoteACK]"
	logSwapPrefix      = "[Swap]"
	logSignerPrefix    = "[Signer]"
)

var volumeTiers = []helpers.VolumeTier{
	{Volume: 1 * solScale, SpreadBP: 0},
	{Volume: 10 * solScale, SpreadBP: 0},
	{Volume: 100 * solScale, SpreadBP: 0},
	{Volume: 1000 * solScale, SpreadBP: 0},
	{Volume: 5000 * solScale, SpreadBP: 0},
}

type tokenMints struct{}

func (tokenMints) SOL() string  { return "So11111111111111111111111111111111111111112" }
func (tokenMints) USDC() string { return "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" }
func (tokenMints) SPL() string  { return "A3QAoKnf3jFcCfTGvEpE7KVBMZqXQJwvwt6Uc4UExkDp" }

var mints tokenMints

type appConfig struct {
	MakerID          string
	AuthToken        string
	Endpoint         string
	MakerAddress     string
	PrivateKeyBase58 string
	DatapiURL        string
}

// sharedPrices is a thread-safe store for current token prices written by the
// quote publisher and read by the quote ack receiver for heartbeat responses.
type sharedPrices struct {
	mu  sync.RWMutex
	sol uint64
	spl uint64
}

func (p *sharedPrices) load() (sol, spl uint64) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.sol, p.spl
}

func (p *sharedPrices) store(sol, spl uint64) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.sol, p.spl = sol, spl
}

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatalf("invalid config: %v", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	clientCfg := gosdk.DefaultClientConfig(cfg.Endpoint)
	clientCfg.AuthToken = cfg.AuthToken

	client, err := gosdk.ConnectWithConfig(ctx, clientCfg)
	if err != nil {
		log.Fatalf("connect failed: %v", err)
	}
	defer client.Close()
	log.Printf(logMainPrefix+" quote streaming with MakerId-%s and MakerAddress-%s",
		cfg.MakerID,
		cfg.MakerAddress)

	quoteStream, nextSeq, err := client.StartQuoteStreamingWithSync(ctx, cfg.MakerID, cfg.AuthToken)
	if err != nil {
		log.Fatalf("start quote stream failed: %v", err)
	}
	defer func() {
		if err := quoteStream.CloseWithTimeout(streamCloseTimeout); err != nil {
			log.Printf(logMainPrefix+" quote stream close error: %v", err)
		}
	}()

	datapi := helpers.NewDatapiClient(cfg.DatapiURL)
	solPrice, splPrice := bootstrapPrices(ctx, datapi)
	prices := &sharedPrices{sol: solPrice, spl: splPrice}
	log.Printf(logMainPrefix+" streaming orderbooks for SOL/USDC ($%s) and MCT/USDC ($%s)",
		helpers.PriceToDisplay(solPrice, priceDecimals),
		helpers.PriceToDisplay(splPrice, priceDecimals))
	log.Printf(logMainPrefix+" connected. quote stream sequence starts at %d", nextSeq)

	var wg sync.WaitGroup
	quoteErr := make(chan error, 1)
	wg.Add(1)
	go func() {
		defer wg.Done()
		quoteErr <- runQuoteSession(ctx, quoteStream, datapi, cfg, nextSeq, prices)
	}()

	swapErr := make(chan error, 1)
	swapStarted := false
	swapStream, swapStartErr := client.StartSwapStreaming(ctx)
	if swapStartErr != nil {
		log.Printf(logMainPrefix+" swap streaming failed: %v. continuing with quotes only", swapStartErr)
	} else {
		swapStarted = true
		defer func() {
			if err := swapStream.CloseWithTimeout(streamCloseTimeout); err != nil {
				log.Printf(logMainPrefix+" swap stream close error: %v", err)
			}
		}()
		wg.Add(1)
		go func() {
			defer wg.Done()
			swapErr <- runSwapLoop(ctx, swapStream, cfg.PrivateKeyBase58)
		}()
	}

	shutdownReason := "context canceled"
	select {
	case <-ctx.Done():
		shutdownReason = fmt.Sprintf("context finished: %v", ctx.Err())
	case err := <-quoteErr:
		shutdownReason = "quote session exited"
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Printf(logMainPrefix+" quote session error: %v", err)
		}
	case err := <-swapErr:
		shutdownReason = "swap session exited"
		if err != nil && !errors.Is(err, context.Canceled) {
			log.Printf(logMainPrefix+" swap session error: %v", err)
		}
	}

	log.Printf(logMainPrefix+" starting graceful shutdown: %s", shutdownReason)
	cancel()
	closeStream(logMainPrefix+" quote stream", quoteStream)
	if swapStarted {
		closeStream(logMainPrefix+" swap stream", swapStream)
	}

	if waitForWaitGroup(&wg, shutdownWaitTime) {
		log.Printf(logMainPrefix + " graceful shutdown completed")
	} else {
		log.Printf(logMainPrefix+" graceful shutdown timed out after %s", shutdownWaitTime)
	}

	stats := quoteStream.Stats()
	log.Printf(logMainPrefix+" quote stats: sent=%d received=%d errors=%d uptime=%s",
		stats.MessagesSent, stats.UpdatesReceived, stats.ErrorsEncountered, stats.Uptime())
	log.Printf(logMainPrefix + " shutdown complete")
}

func loadConfig() (appConfig, error) {
	cfg := appConfig{
		MakerID:          os.Getenv("MM_MAKER_ID"),
		AuthToken:        os.Getenv("MM_AUTH_TOKEN"),
		Endpoint:         os.Getenv("RFQ_ENDPOINT"),
		MakerAddress:     os.Getenv("MM_MAKER_ADDRESS"),
		PrivateKeyBase58: os.Getenv("SOLANA_PRIVATE_KEY"),
		DatapiURL:        os.Getenv("DATAPI_URL"),
	}
	if cfg.MakerID == "" {
		cfg.MakerID = "production_maker"
		log.Printf(logConfigPrefix+" MM_MAKER_ID not set - using default %q", cfg.MakerID)
	}
	if cfg.AuthToken == "" {
		cfg.AuthToken = "production_jwt_token"
		log.Printf(logConfigPrefix+" MM_AUTH_TOKEN not set - using default %q", cfg.AuthToken)
	}
	if cfg.Endpoint == "" {
		cfg.Endpoint = "https://rfq-mm-edge-grpc.raccoons.dev"
		log.Printf(logConfigPrefix+" RFQ_ENDPOINT not set - using default %q", cfg.Endpoint)
	}
	if cfg.MakerAddress == "" {
		cfg.MakerAddress = "11111111111111111111111111111111"
		log.Printf(logConfigPrefix+" MM_MAKER_ADDRESS not set - using default %q", cfg.MakerAddress)
	}
	if cfg.DatapiURL == "" {
		cfg.DatapiURL = "https://datapi.jup.ag"
		log.Printf(logConfigPrefix+" DATAPI_URL not set - using default %q", cfg.DatapiURL)
	}
	return cfg, nil
}

func bootstrapPrices(ctx context.Context, datapi *helpers.DatapiClient) (uint64, uint64) {
	solPrice, splOptional, err := fetchTokenPrices(ctx, datapi)
	if err != nil {
		log.Printf(logPricePrefix+" failed to fetch prices from DatAPI: %v. using fallback prices", err)
		return 100 * priceScale, 200_000
	}

	log.Printf(logPricePrefix+" SOL price: $%s", helpers.PriceToDisplay(solPrice, priceDecimals))

	usdcAmount := uint64(1_000_000) * priceScale
	volumeLamports := usdcToTokenVolume(usdcAmount, solPrice, solScale)
	spreadBP := helpers.SpreadBPForVolume(volumeLamports, volumeTiers, 1)
	bid, ask := helpers.ApplySpreadWithImprovement(solPrice, spreadBP, priceImprovementBP)
	priceSafe := maxU64(solPrice, 1)
	bidDeviation := (solPrice - minU64(solPrice, bid)) * 10_000 / priceSafe
	askDeviation := (ask - minU64(ask, solPrice)) * 10_000 / priceSafe
	spread := (ask - minU64(ask, bid)) * 10_000 / priceSafe
	log.Printf(
		logPricePrefix+" "+
			"example 1M USDC: %s SOL, bid $%s (-%.3f%%), ask $%s (+%.3f%%), spread %.3f%%",
		helpers.PriceToDisplay(volumeLamports, solDecimals),
		helpers.PriceToDisplay(bid, priceDecimals),
		helpers.BasisPointsToPercentage(bidDeviation),
		helpers.PriceToDisplay(ask, priceDecimals),
		helpers.BasisPointsToPercentage(askDeviation),
		helpers.BasisPointsToPercentage(spread),
	)

	splPrice := uint64(200_000)
	if splOptional != 0 {
		splPrice = splOptional
		log.Printf(logPricePrefix+" MCT price: $%s", helpers.PriceToDisplay(splPrice, priceDecimals))
	} else {
		log.Printf(logPricePrefix + " MCT price not available from DatAPI - using fallback $0.20")
	}
	return solPrice, splPrice
}

func fetchTokenPrices(ctx context.Context, datapi *helpers.DatapiClient) (uint64, uint64, error) {
	prices, err := datapi.FetchPrices(ctx, []string{mints.SOL(), mints.SPL()})
	if err != nil {
		return 0, 0, err
	}
	sol, ok := prices[mints.SOL()]
	if !ok {
		return 0, 0, errors.New("SOL price not found in DatAPI response")
	}
	solPrice := uint64(sol.USDPrice*float64(priceScale) + 0.5)
	splPrice := uint64(0)
	if spl, exists := prices[mints.SPL()]; exists {
		splPrice = uint64(spl.USDPrice*float64(priceScale) + 0.5)
	}
	return solPrice, splPrice, nil
}

// runQuoteSession runs a publisher goroutine (sends quotes) and an ack receiver
// goroutine (reads server updates) concurrently over the same stream. Either
// goroutine can signal the other via errCh on a fatal error.
func runQuoteSession(
	ctx context.Context,
	stream *gosdk.QuoteStreamHandle,
	datapi *helpers.DatapiClient,
	cfg appConfig,
	initSeq uint64,
	prices *sharedPrices,
) error {
	sessionCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	errCh := make(chan error, 2)
	var seq uint64 = initSeq
	var seqMu sync.Mutex

	go runQuotePublisher(sessionCtx, stream, datapi, cfg, &seq, &seqMu, prices, errCh)
	go runQuoteAckReceiver(sessionCtx, stream, cfg, &seq, &seqMu, prices, errCh)

	select {
	case <-sessionCtx.Done():
		return sessionCtx.Err()
	case err := <-errCh:
		return err
	}
}

// runQuotePublisher sends SOL/USDC and MCT/USDC quotes on a 10-second ticker.
// It refreshes prices from DatAPI every 5 ticks. It never calls ReceiveUpdate.
func runQuotePublisher(
	ctx context.Context,
	stream *gosdk.QuoteStreamHandle,
	datapi *helpers.DatapiClient,
	cfg appConfig,
	seq *uint64,
	seqMu *sync.Mutex,
	prices *sharedPrices,
	errCh chan<- error,
) {
	solPairCfg, err := gosdk.ResolvePairConfig("SOL/USDC")
	if err != nil {
		errCh <- fmt.Errorf("resolve SOL/USDC pair config: %w", err)
		return
	}
	mctPair := splTokenUSDCPair()
	mctLotSize := uint64(1)

	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	const refreshEvery = 5
	tickCount := 0

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			solPrice, splPrice := prices.load()

			if tickCount > 0 && tickCount%refreshEvery == 0 {
				newSOL, newMCT, err := fetchTokenPrices(ctx, datapi)
				if err != nil {
					log.Printf(logQuotePrefix+" failed to refresh prices from DatAPI: %v", err)
				} else {
					if absDiffU64(newSOL, solPrice) > priceScale/100 {
						log.Printf(logQuotePrefix+" updated SOL price: $%s -> $%s",
							helpers.PriceToDisplay(solPrice, priceDecimals),
							helpers.PriceToDisplay(newSOL, priceDecimals))
						solPrice = newSOL
					}
					if newMCT != 0 && absDiffU64(newMCT, splPrice) > priceScale/100 {
						log.Printf(logQuotePrefix+" updated MCT price: $%s -> $%s",
							helpers.PriceToDisplay(splPrice, priceDecimals),
							helpers.PriceToDisplay(newMCT, priceDecimals))
						splPrice = newMCT
					}
					prices.store(solPrice, splPrice)
				}
			}
			tickCount++

			seqMu.Lock()
			err := sendBothQuotes(stream, cfg, solPairCfg, mctPair, mctLotSize, seq, solPrice, splPrice)
			seqMu.Unlock()
			if err != nil {
				errCh <- err
				return
			}
		}
	}
}

// runQuoteAckReceiver reads server updates from the quote stream in a blocking
// loop. On a server heartbeat PING it responds by re-sending both current quotes.
// Fatal errors are forwarded to errCh.
func runQuoteAckReceiver(
	ctx context.Context,
	stream *gosdk.QuoteStreamHandle,
	cfg appConfig,
	seq *uint64,
	seqMu *sync.Mutex,
	prices *sharedPrices,
	errCh chan<- error,
) {
	solPairCfg, err := gosdk.ResolvePairConfig("SOL/USDC")
	if err != nil {
		errCh <- fmt.Errorf("resolve SOL/USDC pair config: %w", err)
		return
	}
	mctPair := splTokenUSDCPair()
	mctLotSize := uint64(1)

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		update, err := stream.ReceiveUpdate()
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			select {
			case errCh <- fmt.Errorf("receive quote update: %w", err):
			default:
			}
			return
		}
		if update == nil {
			select {
			case errCh <- fmt.Errorf("quote stream closed by server"):
			default:
			}
			return
		}

		switch {
		case gosdk.IsHeartbeat(update):
			solPrice, splPrice := prices.load()
			seqMu.Lock()
			if err := sendBothQuotes(stream, cfg, solPairCfg, mctPair, mctLotSize, seq, solPrice, splPrice); err != nil {
				seqMu.Unlock()
				select {
				case errCh <- err:
				default:
				}
				return
			}
			log.Printf(logQuoteAckPrefix + " heartbeat: sent both quotes")
			seqMu.Unlock()
		case gosdk.IsNewQuote(update):
			log.Printf(logQuoteAckPrefix+" accepted%s", quoteStatusSuffix(update.GetStatusMessage()))
		case gosdk.IsUpdatedQuote(update):
			log.Printf(logQuoteAckPrefix+" updated%s", quoteStatusSuffix(update.GetStatusMessage()))
		case gosdk.IsExpiredQuote(update):
			log.Printf(logQuoteAckPrefix+" expired%s", quoteStatusSuffix(update.GetStatusMessage()))
		case gosdk.IsRejectedQuote(update):
			log.Printf(logQuoteAckPrefix+" rejected: %s", update.GetStatusMessage())
		default:
			log.Printf(logQuoteAckPrefix+" unknown update type=%v", update.GetUpdateType())
		}
	}
}

// sendBothQuotes builds and sends SOL/USDC then MCT/USDC quotes.
// Must be called with seqMu held.
func sendBothQuotes(
	stream *gosdk.QuoteStreamHandle,
	cfg appConfig,
	solPairCfg gosdk.PairConfig,
	mctPair *gosdk.TokenPair,
	mctLotSize uint64,
	seq *uint64,
	solPrice, splPrice uint64,
) error {
	// solBuilder := gosdk.NewMarketMakerQuoteBuilder().
	// 	MakerID(cfg.MakerID).
	// 	TokenPair(solPairCfg.TokenPair).
	// 	SequenceNumber(*seq).
	// 	ExpiryTimeSecs(60).
	// 	MakerAddress(cfg.MakerAddress).
	// 	LotSizeBase(solPairCfg.MinTradeSizeBase)
	// solBuilder, solMinBid, solMaxAsk := helpers.BuildVolumeTierLevels(solBuilder, solPrice, volumeTiers, priceImprovementBP)
	// solQuote, err := solBuilder.Build()
	// if err != nil {
	// 	return fmt.Errorf("build SOL quote: %w", err)
	// }
	// if err := stream.SendQuote(solQuote); err != nil {
	// 	return fmt.Errorf("send SOL quote: %w", err)
	// }
	// log.Printf(logQuotePrefix+" SOL/USDC quote sent seq=%d levels=%d range=$%s-$%s",
	// 	*seq, len(volumeTiers),
	// 	helpers.PriceToDisplay(solMinBid, priceDecimals),
	// 	helpers.PriceToDisplay(solMaxAsk, priceDecimals))
	// *seq++

	mctBuilder := gosdk.NewMarketMakerQuoteBuilder().
		MakerID(cfg.MakerID).
		TokenPair(mctPair).
		SequenceNumber(*seq).
		ExpiryTimeSecs(60).
		MakerAddress(cfg.MakerAddress).
		LotSizeBase(mctLotSize)
	mctBuilder, mctMinBid, mctMaxAsk := helpers.BuildVolumeTierLevels(mctBuilder, splPrice, volumeTiers, priceImprovementBP)
	mctQuote, err := mctBuilder.Build()
	if err != nil {
		return fmt.Errorf("build MCT quote: %w", err)
	}
	if err := stream.SendQuote(mctQuote); err != nil {
		return fmt.Errorf("send MCT quote: %w", err)
	}
	log.Printf(logQuotePrefix+" MCT/USDC quote sent seq=%d levels=%d range=$%s-$%s",
		*seq, len(volumeTiers),
		helpers.PriceToDisplay(mctMinBid, priceDecimals),
		helpers.PriceToDisplay(mctMaxAsk, priceDecimals))
	*seq++

	return nil
}

func quoteStatusSuffix(msg string) string {
	if msg == "" {
		return ""
	}
	return ": " + msg
}

func closeStream(name string, stream interface{ CloseWithTimeout(time.Duration) error }) {
	if err := stream.CloseWithTimeout(streamCloseTimeout); err != nil {
		log.Printf("%s close error: %v", name, err)
	}
}

func waitForWaitGroup(wg *sync.WaitGroup, timeout time.Duration) bool {
	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		return true
	case <-time.After(timeout):
		return false
	}
}

// runSwapLoop manages the swap stream. A pinger goroutine sends keepalive PINGs
// every 10 seconds while the main loop blocks on ReceiveUpdate.
func runSwapLoop(ctx context.Context, stream *gosdk.SwapStreamHandle, privateKeyBase58 string) error {
	log.Printf(logSwapPrefix + " swap stream started with keepalive monitoring")

	go func() {
		ticker := time.NewTicker(10 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				ping := &gosdk.MarketMakerSwap{
					MessageType:       gosdk.SwapTypePing.Enum(),
					SwapUuid:          proto.String(""),
					SignedTransaction: proto.String(""),
				}
				if err := stream.SendSwap(ping); err != nil {
					log.Printf(logSwapPrefix+" ping failed: %v", err)
					return
				}
				log.Printf(logSwapPrefix + " sent ping to server")
			}
		}
	}()

	swapCount := 0
	for {
		update, err := stream.ReceiveUpdate()
		if err != nil {
			if ctx.Err() != nil {
				stats := stream.Stats()
				log.Printf(logSwapPrefix+" stats: sent=%d received=%d errors=%d uptime=%s",
					stats.MessagesSent, stats.UpdatesReceived, stats.ErrorsEncountered, stats.Uptime())
				return nil
			}
			return fmt.Errorf("receive swap update: %w", err)
		}
		if update == nil {
			return nil
		}

		switch {
		case gosdk.IsPong(update):
			log.Printf(logSwapPrefix + " received pong from server")
		case gosdk.IsSwapConnectionReady(update):
			status := helpers.GetSwapStatusMessage(update)
			if status == "" {
				status = "Ready"
			}
			log.Printf(logSwapPrefix+" swap stream ready: %s", status)
		case gosdk.IsSwapError(update):
			errMsg := helpers.GetSwapStatusMessage(update)
			if errMsg == "" {
				errMsg = "Unknown error"
			}
			log.Printf(logSwapPrefix+" swap stream error: %s", errMsg)
		case gosdk.IsSwapConfirmed(update):
			if uuid, signature, ok := helpers.ExtractConfirmationDetails(update); ok {
				log.Printf(logSwapPrefix+" transaction confirmed - uuid=%s signature=%s", uuid, signature)
			}
		case gosdk.IsSwapAvailable(update):
			swapUUID, unsignedTx, ok := helpers.ExtractSwapDetails(update)
			if !ok {
				log.Printf(logSwapPrefix + " received swap available but missing details")
				continue
			}
			swapCount++
			log.Printf(logSwapPrefix+" swap #%d: %s", swapCount, swapUUID)
			signedTx, err := signSwapTransaction(swapUUID, unsignedTx, privateKeyBase58)
			if err != nil {
				log.Printf(logSwapPrefix+" failed to sign transaction: %v", err)
				continue
			}
			submit := &gosdk.MarketMakerSwap{
				MessageType:       gosdk.SwapTypeSwapSubmit.Enum(),
				SwapUuid:          proto.String(swapUUID),
				SignedTransaction: proto.String(signedTx),
			}
			if err := stream.SendSwap(submit); err != nil {
				return fmt.Errorf("failed to send signed transaction: %w", err)
			}
			log.Printf(logSwapPrefix+" submitted signed transaction for swap %s", swapUUID)
		default:
			log.Printf(logSwapPrefix+" received other swap update type: %s", helpers.SwapUpdateTypeDescription(update))
		}
	}
}

func signSwapTransaction(swapUUID, unsignedTxBase64, privateKeyBase58 string) (string, error) {
	if privateKeyBase58 == "" {
		return "", errors.New("SOLANA_PRIVATE_KEY is required to sign swap transactions")
	}
	log.Printf(logSignerPrefix+" processing transaction for swap uuid: %s", swapUUID)

	pk, err := solana.PrivateKeyFromBase58(privateKeyBase58)
	if err != nil {
		return "", fmt.Errorf("invalid private key: %w", err)
	}

	var tx solana.Transaction
	if err := tx.UnmarshalBase64(unsignedTxBase64); err != nil {
		return "", fmt.Errorf("failed to unmarshal transaction: %w", err)
	}
	if err := validateTransaction(&tx); err != nil {
		return "", err
	}

	pub := pk.PublicKey()
	required := int(tx.Message.Header.NumRequiredSignatures)
	if required <= 0 || required > len(tx.Message.AccountKeys) {
		return "", fmt.Errorf("invalid required signer count: %d", required)
	}

	foundSigner := false
	for i := 0; i < required; i++ {
		if tx.Message.AccountKeys[i].Equals(pub) {
			foundSigner = true
			break
		}
	}
	if !foundSigner {
		return "", fmt.Errorf("provided SOLANA_PRIVATE_KEY pubkey %s is not one of required signer keys", pub)
	}

	if _, err := tx.PartialSign(func(key solana.PublicKey) *solana.PrivateKey {
		if key.Equals(pub) {
			return &pk
		}
		return nil
	}); err != nil {
		return "", fmt.Errorf("failed to partial-sign transaction: %w", err)
	}

	encoded, err := tx.MarshalBinary()
	if err != nil {
		return "", err
	}
	log.Printf(logSignerPrefix + " transaction signed and encoded successfully")
	return base64.StdEncoding.EncodeToString(encoded), nil
}

func validateTransaction(tx *solana.Transaction) error {
	if tx == nil {
		return errors.New("transaction is nil")
	}
	if len(tx.Signatures) == 0 {
		return errors.New("transaction has no signatures array")
	}
	if len(tx.Message.AccountKeys) == 0 {
		return errors.New("transaction has no account keys")
	}
	if len(tx.Message.Instructions) == 0 {
		return errors.New("transaction has no instructions")
	}
	log.Printf(
		logSignerPrefix+" "+
			"transaction validation passed (version=%d instructions=%d account_keys=%d address_table_lookups=%d)",
		tx.Message.GetVersion(),
		len(tx.Message.Instructions),
		len(tx.Message.AccountKeys),
		len(tx.Message.AddressTableLookups),
	)
	return nil
}

func splTokenUSDCPair() *gosdk.TokenPair {
	return &gosdk.TokenPair{
		BaseToken: &gosdk.Token{
			Address:  proto.String(mints.SPL()),
			Decimals: proto.Uint32(splTokenDecimals),
			Symbol:   proto.String("MCT"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
		QuoteToken: &gosdk.Token{
			Address:  proto.String(mints.USDC()),
			Decimals: proto.Uint32(priceDecimals),
			Symbol:   proto.String("USDC"),
			Owner:    proto.String("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
		},
	}
}

func usdcToTokenVolume(usdcAmount, tokenPrice, tokenScale uint64) uint64 {
	if tokenPrice == 0 {
		return 0
	}
	if usdcAmount > ^uint64(0)/tokenScale {
		return (usdcAmount / tokenPrice) * tokenScale
	}
	return (usdcAmount * tokenScale) / tokenPrice
}

func absDiffU64(a, b uint64) uint64 {
	if a > b {
		return a - b
	}
	return b - a
}

func minU64(a, b uint64) uint64 {
	if a < b {
		return a
	}
	return b
}

func maxU64(a, b uint64) uint64 {
	if a > b {
		return a
	}
	return b
}
