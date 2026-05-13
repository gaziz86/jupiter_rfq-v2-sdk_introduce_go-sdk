package gosdk

import (
	"context"
	"fmt"
	"log"
	"net/url"
	"time"

	"go-sdk/marketmakerpb"

	"google.golang.org/grpc"
	"google.golang.org/grpc/connectivity"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/proto"
)

type MarketMakerClient struct {
	conn   *grpc.ClientConn
	inner  marketmakerpb.MarketMakerIngestionServiceClient
	config ClientConfig
}

func Connect(ctx context.Context, endpoint string) (*MarketMakerClient, error) {
	return ConnectWithConfig(ctx, DefaultClientConfig(endpoint))
}

func ConnectWithConfig(ctx context.Context, config ClientConfig) (*MarketMakerClient, error) {
	if config.Endpoint == "" {
		return nil, newError(ErrorKindConfiguration, "endpoint is required", nil)
	}
	if config.Timeout <= 0 {
		config.Timeout = time.Duration(DefaultTimeoutSeconds) * time.Second
	}

	target, creds, err := dialTargetAndCreds(config.Endpoint)
	if err != nil {
		return nil, err
	}

	conn, err := grpc.NewClient(
		target,
		grpc.WithTransportCredentials(creds),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			// Send application-level keepalive pings every 30 s; the server
			// MUST respond within 10 s or the connection is closed.
			Time:                30 * time.Second,
			Timeout:             10 * time.Second,
			PermitWithoutStream: true,
		}),
	)
	if err != nil {
		return nil, newError(ErrorKindConnection, "failed to connect", err)
	}

	connectCtx, cancel := context.WithTimeout(ctx, config.Timeout)
	defer cancel()
	conn.Connect()
	if err := waitForReady(connectCtx, conn); err != nil {
		_ = conn.Close()
		return nil, newError(ErrorKindConnection, "failed to connect", err)
	}

	return &MarketMakerClient{
		conn:   conn,
		inner:  marketmakerpb.NewMarketMakerIngestionServiceClient(conn),
		config: config,
	}, nil
}

func waitForReady(ctx context.Context, conn *grpc.ClientConn) error {
	for {
		state := conn.GetState()
		switch state {
		case connectivity.Ready:
			return nil
		case connectivity.Shutdown:
			return fmt.Errorf("connection entered shutdown state")
		}

		if !conn.WaitForStateChange(ctx, state) {
			if err := ctx.Err(); err != nil {
				return err
			}
		}
	}
}

func dialTargetAndCreds(endpoint string) (string, credentials.TransportCredentials, error) {
	parsed, err := url.Parse(endpoint)
	if err != nil {
		return "", nil, newError(ErrorKindConfiguration, "invalid endpoint", err)
	}
	if parsed.Scheme == "http" {
		if parsed.Host == "" {
			return "", nil, newError(ErrorKindConfiguration, "invalid http endpoint host", nil)
		}
		log.Printf("[WARN] gRPC endpoint %s is not TLS-secured; use https:// in production", endpoint)
		return parsed.Host, insecure.NewCredentials(), nil
	}
	if parsed.Scheme == "https" {
		if parsed.Host == "" {
			return "", nil, newError(ErrorKindConfiguration, "invalid https endpoint host", nil)
		}
		return parsed.Host, credentials.NewClientTLSFromCert(nil, ""), nil
	}
	// If the endpoint has no scheme, default to insecure for local/dev usage.
	if parsed.Scheme == "" {
		return endpoint, insecure.NewCredentials(), nil
	}
	return "", nil, newError(ErrorKindConfiguration, "unsupported endpoint scheme", nil)
}

func (c *MarketMakerClient) authContext(ctx context.Context) context.Context {
	if c.config.AuthToken == "" {
		return ctx
	}
	return metadata.AppendToOutgoingContext(ctx, "x-api-key", c.config.AuthToken)
}

func (c *MarketMakerClient) Close() error {
	if c.conn == nil {
		return nil
	}
	return c.conn.Close()
}

func (c *MarketMakerClient) Config() ClientConfig {
	return c.config
}

func (c *MarketMakerClient) StartQuoteStreaming(ctx context.Context) (*QuoteStreamHandle, error) {
	return c.StartQuoteStreamingWithConfig(ctx, DefaultStreamConfig())
}

// StartStreaming is a backward-compatible alias for StartQuoteStreaming.
func (c *MarketMakerClient) StartStreaming(ctx context.Context) (*QuoteStreamHandle, error) {
	return c.StartQuoteStreaming(ctx)
}

func (c *MarketMakerClient) StartQuoteStreamingWithConfig(ctx context.Context, _ StreamConfig) (*QuoteStreamHandle, error) {
	stream, err := c.inner.StreamQuotes(c.authContext(ctx))
	if err != nil {
		return nil, newError(ErrorKindGRPC, "failed to start quote stream", err)
	}
	return newQuoteStreamHandle(stream), nil
}

// StartStreamingWithConfig is a backward-compatible alias for StartQuoteStreamingWithConfig.
func (c *MarketMakerClient) StartStreamingWithConfig(ctx context.Context, config StreamConfig) (*QuoteStreamHandle, error) {
	return c.StartQuoteStreamingWithConfig(ctx, config)
}

func (c *MarketMakerClient) StartSwapStreaming(ctx context.Context) (*SwapStreamHandle, error) {
	stream, err := c.inner.StreamSwap(c.authContext(ctx))
	if err != nil {
		return nil, newError(ErrorKindGRPC, "failed to start swap stream", err)
	}
	return newSwapStreamHandle(stream), nil
}

func (c *MarketMakerClient) GetLastSequenceNumber(ctx context.Context, makerID, authToken string) (uint64, error) {
	resp, err := c.inner.GetLastSequenceNumber(c.authContext(ctx), &marketmakerpb.SequenceNumberRequest{
		MakerId:   proto.String(makerID),
		AuthToken: proto.String(authToken),
	})
	if err != nil {
		return 0, newError(ErrorKindGRPC, "get_last_sequence_number failed", err)
	}
	if !resp.GetSuccess() {
		return 0, nil
	}
	return resp.GetLastSequenceNumber(), nil
}

func (c *MarketMakerClient) GetQuotes(ctx context.Context, tokenPair *TokenPair, authToken string) (*GetQuotesResponse, error) {
	resp, err := c.inner.GetQuotes(c.authContext(ctx), &marketmakerpb.GetQuotesRequest{
		TokenPair: tokenPair,
		AuthToken: proto.String(authToken),
	})
	if err != nil {
		return nil, newError(ErrorKindGRPC, "get_quotes failed", err)
	}
	return resp, nil
}

func (c *MarketMakerClient) ReceiveUpdate(ctx context.Context, cluster *Cluster) (*GetAllOrderbooksResponse, error) {
	req := &marketmakerpb.GetAllOrderbooksRequest{}
	if cluster != nil {
		cl := *cluster
		req.Cluster = cl.Enum()
	}
	resp, err := c.inner.GetAllOrderbooks(c.authContext(ctx), req)
	if err != nil {
		return nil, newError(ErrorKindGRPC, "get_all_orderbooks failed", err)
	}
	return resp, nil
}

func (c *MarketMakerClient) StartQuoteStreamingWithSync(ctx context.Context, makerID, authToken string) (*QuoteStreamHandle, uint64, error) {
	last, err := c.GetLastSequenceNumber(ctx, makerID, authToken)
	if err != nil {
		return nil, 0, err
	}
	handle, err := c.StartQuoteStreaming(ctx)
	if err != nil {
		return nil, 0, err
	}
	return handle, last + 1, nil
}

// StartStreamingWithSync is a backward-compatible alias for StartQuoteStreamingWithSync.
func (c *MarketMakerClient) StartStreamingWithSync(ctx context.Context, makerID, authToken string) (*QuoteStreamHandle, uint64, error) {
	return c.StartQuoteStreamingWithSync(ctx, makerID, authToken)
}

func ShutdownStreamWithTimeout(stream *QuoteStreamHandle, timeout time.Duration) error {
	if stream == nil {
		return nil
	}
	return stream.CloseWithTimeout(timeout)
}
