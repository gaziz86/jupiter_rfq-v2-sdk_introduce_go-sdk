package gosdk

import (
	"context"
	"io"
	"net"
	"testing"
	"time"

	"go-sdk/marketmakerpb"

	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
	"google.golang.org/protobuf/proto"
)

type mockRFQServer struct {
	marketmakerpb.UnimplementedMarketMakerIngestionServiceServer
}

func (s *mockRFQServer) GetLastSequenceNumber(context.Context, *marketmakerpb.SequenceNumberRequest) (*marketmakerpb.SequenceNumberResponse, error) {
	return &marketmakerpb.SequenceNumberResponse{
		Success:            proto.Bool(true),
		LastSequenceNumber: proto.Uint64(41),
		Message:            proto.String("ok"),
	}, nil
}

func (s *mockRFQServer) GetAllOrderbooks(context.Context, *marketmakerpb.GetAllOrderbooksRequest) (*marketmakerpb.GetAllOrderbooksResponse, error) {
	return &marketmakerpb.GetAllOrderbooksResponse{
		Orderbooks: []*marketmakerpb.Orderbook{},
		Timestamp:  proto.Uint64(uint64(time.Now().UnixMicro())),
	}, nil
}

func (s *mockRFQServer) StreamQuotes(stream grpc.BidiStreamingServer[marketmakerpb.MarketMakerQuote, marketmakerpb.QuoteUpdate]) error {
	for {
		quote, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		if quote.GetMakerId() != "" {
			if err := stream.Send(&marketmakerpb.QuoteUpdate{UpdateType: marketmakerpb.UpdateType_UPDATE_TYPE_NEW.Enum()}); err != nil {
				return err
			}
		}
	}
}

func (s *mockRFQServer) StreamSwap(stream grpc.BidiStreamingServer[marketmakerpb.MarketMakerSwap, marketmakerpb.SwapUpdate]) error {
	for {
		swap, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		if swap.GetMessageType() == marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_PING {
			if err := stream.Send(&marketmakerpb.SwapUpdate{MessageType: marketmakerpb.SwapMessageType_SWAP_MESSAGE_TYPE_PONG.Enum()}); err != nil {
				return err
			}
		}
	}
}

func (s *mockRFQServer) GetQuotes(_ context.Context, req *marketmakerpb.GetQuotesRequest) (*marketmakerpb.GetQuotesResponse, error) {
	quote := &marketmakerpb.MarketMakerQuote{
		Timestamp:       proto.Uint64(uint64(time.Now().UnixMicro())),
		SequenceNumber:  proto.Uint64(1),
		QuoteExpiryTime: proto.Uint64(30),
		MakerId:         proto.String("test-maker"),
		MakerAddress:    proto.String("11111111111111111111111111111111"),
		LotSizeBase:     proto.Uint64(1000),
		Cluster:         marketmakerpb.Cluster_CLUSTER_MAINNET.Enum(),
		TokenPair:       req.GetTokenPair(),
		BidLevels:       []*marketmakerpb.PriceLevel{{Volume: proto.Uint64(1_000_000_000), Price: proto.Uint64(150_000_000)}},
		AskLevels:       []*marketmakerpb.PriceLevel{{Volume: proto.Uint64(1_000_000_000), Price: proto.Uint64(151_000_000)}},
	}
	return &marketmakerpb.GetQuotesResponse{Quotes: []*marketmakerpb.MarketMakerQuote{quote}}, nil
}

func startMockServer(t *testing.T, withReflection bool) (string, func()) {
	t.Helper()
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen failed: %v", err)
	}
	srv := grpc.NewServer()
	marketmakerpb.RegisterMarketMakerIngestionServiceServer(srv, &mockRFQServer{})
	if withReflection {
		reflection.Register(srv)
	}
	go func() { _ = srv.Serve(lis) }()
	return "http://" + lis.Addr().String(), func() {
		srv.Stop()
		_ = lis.Close()
	}
}

func TestIntegrationGetQuotesAndSync(t *testing.T) {
	endpoint, cleanup := startMockServer(t, false)
	defer cleanup()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client, err := Connect(ctx, endpoint)
	if err != nil {
		t.Fatalf("connect failed: %v", err)
	}
	defer client.Close()

	resp, err := client.GetQuotes(ctx, EthUSDC(), "auth-token")
	if err != nil {
		t.Fatalf("get quotes failed: %v", err)
	}
	if len(resp.GetQuotes()) != 1 {
		t.Fatalf("expected 1 quote, got %d", len(resp.GetQuotes()))
	}
	if got := resp.GetQuotes()[0].GetTokenPair().GetBaseToken().GetSymbol(); got != "ETH" {
		t.Fatalf("unexpected base symbol: %s", got)
	}

	_, nextSeq, err := client.StartStreamingWithSync(ctx, "maker-1", "auth-token")
	if err != nil {
		t.Fatalf("start streaming with sync failed: %v", err)
	}
	if nextSeq != 42 {
		t.Fatalf("expected next seq 42, got %d", nextSeq)
	}
}

func TestIntegrationQuoteAndSwapStreaming(t *testing.T) {
	endpoint, cleanup := startMockServer(t, false)
	defer cleanup()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client, err := Connect(ctx, endpoint)
	if err != nil {
		t.Fatalf("connect failed: %v", err)
	}
	defer client.Close()

	quoteStream, err := client.StartStreaming(ctx)
	if err != nil {
		t.Fatalf("start quote stream failed: %v", err)
	}

	quote, err := NewMarketMakerQuoteBuilder().
		MakerID("maker-1").
		MakerAddress("11111111111111111111111111111111").
		LotSizeBase(1000).
		SolUSDCPair().
		BidLevel(1_000_000_000, 150_000_000).
		AskLevel(1_000_000_000, 151_000_000).
		Build()
	if err != nil {
		t.Fatalf("build quote failed: %v", err)
	}

	if err := quoteStream.SendQuote(quote); err != nil {
		t.Fatalf("send quote failed: %v", err)
	}
	update, err := quoteStream.ReceiveUpdateTimeout(2 * time.Second)
	if err != nil {
		t.Fatalf("receive quote update failed: %v", err)
	}
	if update == nil || !IsNewQuote(update) {
		t.Fatalf("expected NEW quote update")
	}

	swapStream, err := client.StartSwapStreaming(ctx)
	if err != nil {
		t.Fatalf("start swap stream failed: %v", err)
	}
	if err := swapStream.SendSwap(&MarketMakerSwap{MessageType: SwapTypePing.Enum(), SwapUuid: proto.String(""), SignedTransaction: proto.String("")}); err != nil {
		t.Fatalf("send ping failed: %v", err)
	}
	swapUpdate, err := swapStream.ReceiveUpdateTimeout(2 * time.Second)
	if err != nil {
		t.Fatalf("receive swap update failed: %v", err)
	}
	if swapUpdate == nil || !IsPong(swapUpdate) {
		t.Fatalf("expected PONG swap update")
	}
}

func TestIntegrationReflectionHelpers(t *testing.T) {
	endpoint, cleanup := startMockServer(t, true)
	defer cleanup()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client, err := Connect(ctx, endpoint)
	if err != nil {
		t.Fatalf("connect failed: %v", err)
	}
	defer client.Close()

	services, err := client.ListServices(ctx)
	if err != nil {
		t.Fatalf("list services failed: %v", err)
	}
	if len(services) == 0 {
		t.Fatalf("expected at least one reflected service")
	}

	serviceInfo, err := client.VerifyService(ctx)
	if err != nil {
		t.Fatalf("verify service failed: %v", err)
	}
	if serviceInfo == nil || len(serviceInfo.Methods) == 0 {
		t.Fatalf("expected reflected market maker service methods")
	}
}
