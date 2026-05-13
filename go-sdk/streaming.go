package gosdk

import (
	"context"
	"errors"
	"io"
	"sync"
	"time"

	"go-sdk/marketmakerpb"

	"google.golang.org/grpc"
)

type StreamConfig struct {
	SendBufferSize       int
	OperationTimeout     time.Duration
	AutoReconnect        bool
	MaxReconnectAttempts uint32
	InactivityTimeout    time.Duration
}

func DefaultStreamConfig() StreamConfig {
	return StreamConfig{
		SendBufferSize:       DefaultChannelBufferSize,
		OperationTimeout:     30 * time.Second,
		AutoReconnect:        false,
		MaxReconnectAttempts: 3,
		InactivityTimeout:    120 * time.Second,
	}
}

type ConnectionStats struct {
	MessagesSent      uint64
	UpdatesReceived   uint64
	ErrorsEncountered uint64
	Reconnections     uint64
	ConnectedAt       time.Time
	LastActivity      time.Time
}

func (s ConnectionStats) TimeSinceLastActivity() time.Duration {
	if s.LastActivity.IsZero() {
		return 0
	}
	return time.Since(s.LastActivity)
}

func (s ConnectionStats) Uptime() time.Duration {
	if s.ConnectedAt.IsZero() {
		return 0
	}
	return time.Since(s.ConnectedAt)
}

type QuoteStreamHandle struct {
	stream grpc.BidiStreamingClient[marketmakerpb.MarketMakerQuote, marketmakerpb.QuoteUpdate]
	stats  ConnectionStats
	mu     sync.Mutex
	closed bool
}

func newQuoteStreamHandle(stream grpc.BidiStreamingClient[marketmakerpb.MarketMakerQuote, marketmakerpb.QuoteUpdate]) *QuoteStreamHandle {
	now := time.Now()
	return &QuoteStreamHandle{stream: stream, stats: ConnectionStats{ConnectedAt: now, LastActivity: now}}
}

func (h *QuoteStreamHandle) SendQuote(quote *MarketMakerQuote) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed {
		return newError(ErrorKindStreaming, "stream has been closed", nil)
	}
	if err := h.stream.Send(quote); err != nil {
		h.stats.ErrorsEncountered++
		return newError(ErrorKindGRPC, "failed to send quote", err)
	}
	h.stats.MessagesSent++
	h.stats.LastActivity = time.Now()
	return nil
}

func (h *QuoteStreamHandle) ReceiveUpdate() (*QuoteUpdate, error) {
	update, err := h.stream.Recv()
	if err == io.EOF {
		h.mu.Lock()
		h.closed = true
		h.mu.Unlock()
		return nil, nil
	}
	if err != nil {
		h.mu.Lock()
		h.stats.ErrorsEncountered++
		h.mu.Unlock()
		return nil, newError(ErrorKindGRPC, "failed to receive quote update", err)
	}
	h.mu.Lock()
	h.stats.UpdatesReceived++
	h.stats.LastActivity = time.Now()
	h.mu.Unlock()
	return update, nil
}

func (h *QuoteStreamHandle) ReceiveUpdateTimeout(timeout time.Duration) (*QuoteUpdate, error) {
	type result struct {
		update *QuoteUpdate
		err    error
	}
	ch := make(chan result, 1)
	go func() {
		u, err := h.ReceiveUpdate()
		ch <- result{update: u, err: err}
	}()
	select {
	case out := <-ch:
		return out.update, out.err
	case <-time.After(timeout):
		return nil, newError(ErrorKindTimeout, "timed out waiting for update", nil)
	}
}

func (h *QuoteStreamHandle) Close() error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed {
		return nil
	}
	h.closed = true
	if err := h.stream.CloseSend(); err != nil {
		return newError(ErrorKindGRPC, "failed to close quote stream", err)
	}
	return nil
}

func (h *QuoteStreamHandle) CloseWithTimeout(timeout time.Duration) error {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	ch := make(chan error, 1)
	go func() { ch <- h.Close() }()
	select {
	case err := <-ch:
		return err
	case <-ctx.Done():
		return newError(ErrorKindTimeout, "stream close operation timed out", ctx.Err())
	}
}

func (h *QuoteStreamHandle) IsClosed() bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.closed
}

func (h *QuoteStreamHandle) IsHealthy(config StreamConfig) bool {
	stats := h.Stats()
	if stats.LastActivity.IsZero() {
		return time.Since(stats.ConnectedAt) < config.InactivityTimeout
	}
	return time.Since(stats.LastActivity) <= config.InactivityTimeout
}

func (h *QuoteStreamHandle) Stats() ConnectionStats {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.stats
}

func (h *QuoteStreamHandle) DrainUpdates(maxDuration, receiveTimeout time.Duration, onUpdate func(*QuoteUpdate)) (int, error) {
	if maxDuration <= 0 {
		return 0, newError(ErrorKindValidation, "maxDuration must be positive", nil)
	}
	if receiveTimeout <= 0 {
		return 0, newError(ErrorKindValidation, "receiveTimeout must be positive", nil)
	}
	deadline := time.Now().Add(maxDuration)
	drained := 0

	for time.Now().Before(deadline) {
		update, err := h.ReceiveUpdateTimeout(receiveTimeout)
		if err != nil {
			var e *Error
			if errors.As(err, &e) && e.Kind == ErrorKindTimeout {
				continue
			}
			return drained, err
		}
		if update == nil {
			break
		}
		drained++
		if onUpdate != nil {
			onUpdate(update)
		}
	}

	return drained, nil
}

type SwapStreamHandle struct {
	stream grpc.BidiStreamingClient[marketmakerpb.MarketMakerSwap, marketmakerpb.SwapUpdate]
	stats  ConnectionStats
	mu     sync.Mutex
	closed bool
}

func newSwapStreamHandle(stream grpc.BidiStreamingClient[marketmakerpb.MarketMakerSwap, marketmakerpb.SwapUpdate]) *SwapStreamHandle {
	now := time.Now()
	return &SwapStreamHandle{stream: stream, stats: ConnectionStats{ConnectedAt: now, LastActivity: now}}
}

func (h *SwapStreamHandle) SendSwap(swap *MarketMakerSwap) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed {
		return newError(ErrorKindStreaming, "stream has been closed", nil)
	}
	if err := h.stream.Send(swap); err != nil {
		h.stats.ErrorsEncountered++
		return newError(ErrorKindGRPC, "failed to send swap", err)
	}
	h.stats.MessagesSent++
	h.stats.LastActivity = time.Now()
	return nil
}

func (h *SwapStreamHandle) ReceiveUpdate() (*SwapUpdate, error) {
	update, err := h.stream.Recv()
	if err == io.EOF {
		h.mu.Lock()
		h.closed = true
		h.mu.Unlock()
		return nil, nil
	}
	if err != nil {
		h.mu.Lock()
		h.stats.ErrorsEncountered++
		h.mu.Unlock()
		return nil, newError(ErrorKindGRPC, "failed to receive swap update", err)
	}
	h.mu.Lock()
	h.stats.UpdatesReceived++
	h.stats.LastActivity = time.Now()
	h.mu.Unlock()
	return update, nil
}

func (h *SwapStreamHandle) ReceiveUpdateTimeout(timeout time.Duration) (*SwapUpdate, error) {
	type result struct {
		update *SwapUpdate
		err    error
	}
	ch := make(chan result, 1)
	go func() {
		u, err := h.ReceiveUpdate()
		ch <- result{update: u, err: err}
	}()
	select {
	case out := <-ch:
		return out.update, out.err
	case <-time.After(timeout):
		return nil, newError(ErrorKindTimeout, "timed out waiting for swap update", nil)
	}
}

func (h *SwapStreamHandle) IsHealthy(config StreamConfig) bool {
	stats := h.Stats()
	if stats.LastActivity.IsZero() {
		return time.Since(stats.ConnectedAt) < config.InactivityTimeout
	}
	return time.Since(stats.LastActivity) <= config.InactivityTimeout
}

func (h *SwapStreamHandle) Close() error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed {
		return nil
	}
	h.closed = true
	if err := h.stream.CloseSend(); err != nil {
		return newError(ErrorKindGRPC, "failed to close swap stream", err)
	}
	return nil
}

func (h *SwapStreamHandle) CloseWithTimeout(timeout time.Duration) error {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	ch := make(chan error, 1)
	go func() { ch <- h.Close() }()
	select {
	case err := <-ch:
		return err
	case <-ctx.Done():
		return newError(ErrorKindTimeout, "swap stream close operation timed out", ctx.Err())
	}
}

func (h *SwapStreamHandle) IsClosed() bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.closed
}

func (h *SwapStreamHandle) Stats() ConnectionStats {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.stats
}

func (h *SwapStreamHandle) DrainUpdates(maxDuration, receiveTimeout time.Duration, onUpdate func(*SwapUpdate)) (int, error) {
	if maxDuration <= 0 {
		return 0, newError(ErrorKindValidation, "maxDuration must be positive", nil)
	}
	if receiveTimeout <= 0 {
		return 0, newError(ErrorKindValidation, "receiveTimeout must be positive", nil)
	}
	deadline := time.Now().Add(maxDuration)
	drained := 0

	for time.Now().Before(deadline) {
		update, err := h.ReceiveUpdateTimeout(receiveTimeout)
		if err != nil {
			var e *Error
			if errors.As(err, &e) && e.Kind == ErrorKindTimeout {
				continue
			}
			return drained, err
		}
		if update == nil {
			break
		}
		drained++
		if onUpdate != nil {
			onUpdate(update)
		}
	}

	return drained, nil
}

func IsHeartbeat(update *QuoteUpdate) bool {
	return update != nil && update.GetUpdateType() == UpdateTypeUnspecified
}

func IsNewQuote(update *QuoteUpdate) bool {
	return update != nil && update.GetUpdateType() == UpdateTypeNew
}

func IsUpdatedQuote(update *QuoteUpdate) bool {
	return update != nil && update.GetUpdateType() == UpdateTypeUpdated
}

func IsExpiredQuote(update *QuoteUpdate) bool {
	return update != nil && update.GetUpdateType() == UpdateTypeExpired
}

func IsRejectedQuote(update *QuoteUpdate) bool {
	return update != nil && update.GetUpdateType() == UpdateTypeRejected
}

func IsSwapConnectionReady(update *SwapUpdate) bool {
	return update != nil && update.GetMessageType() == SwapTypeConnectionReady
}

func IsSwapAvailable(update *SwapUpdate) bool {
	return update != nil && update.GetMessageType() == SwapTypeSwapAvailable
}

func IsSwapConfirmed(update *SwapUpdate) bool {
	return update != nil && update.GetMessageType() == SwapTypeTransactionConfirm
}

func IsSwapError(update *SwapUpdate) bool {
	return update != nil && update.GetMessageType() == SwapTypeError
}

func IsPong(update *SwapUpdate) bool {
	return update != nil && update.GetMessageType() == SwapTypePong
}

// IsPingSwap returns true when the server sends a PING on the swap stream.
// The caller must respond with a PONG.
func IsPingSwap(update *SwapUpdate) bool {
	return update != nil && update.GetMessageType() == SwapTypePing
}
