package helpers

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const defaultUserAgent = "rfq-v2-go-sdk-example/0.1"

type TokenPriceData struct {
	USDPrice       float64 `json:"usdPrice"`
	BlockID        uint64  `json:"blockId"`
	Decimals       uint8   `json:"decimals"`
	PriceChange24H float64 `json:"priceChange24h"`
}

type DatapiResponse map[string]TokenPriceData

type DatapiClient struct {
	host   string
	client *http.Client
}

func NewDatapiClient(host string) *DatapiClient {
	h := strings.TrimSpace(host)
	if h == "" {
		h = "https://datapi.jup.ag"
	}
	return &DatapiClient{
		host:   strings.TrimRight(h, "/"),
		client: &http.Client{Timeout: 10 * time.Second},
	}
}

func (c *DatapiClient) FetchPrices(ctx context.Context, tokenIDs []string) (DatapiResponse, error) {
	if c == nil {
		return nil, fmt.Errorf("datapi client is nil")
	}
	if len(tokenIDs) == 0 {
		return nil, fmt.Errorf("tokenIDs cannot be empty")
	}

	ids := strings.Join(tokenIDs, ",")
	endpoint := fmt.Sprintf("%s/v1/prices?ids=%s", c.host, url.QueryEscape(ids))
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, fmt.Errorf("create datapi request: %w", err)
	}
	req.Header.Set("accept", "application/json")
	req.Header.Set("user-agent", defaultUserAgent)

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("datapi request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		msg := strings.TrimSpace(string(body))
		if msg == "" {
			return nil, fmt.Errorf("datapi returned HTTP %d", resp.StatusCode)
		}
		return nil, fmt.Errorf("datapi returned HTTP %d: %s", resp.StatusCode, msg)
	}

	var body DatapiResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, fmt.Errorf("decode datapi response: %w", err)
	}
	return body, nil
}

func (c *DatapiClient) FetchPrice(ctx context.Context, tokenID string) (DatapiResponse, error) {
	id := strings.TrimSpace(tokenID)
	if id == "" {
		return nil, fmt.Errorf("tokenID cannot be empty")
	}
	return c.FetchPrices(ctx, []string{id})
}
