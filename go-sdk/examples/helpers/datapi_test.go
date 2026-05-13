package helpers

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDatapiClientFetchPrices(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.URL.Path; got != "/v1/prices" {
			t.Fatalf("unexpected path: %s", got)
		}
		if got := r.URL.Query().Get("ids"); got != "SOL,SPL" {
			t.Fatalf("unexpected ids query: %s", got)
		}
		if got := r.Header.Get("User-Agent"); got != defaultUserAgent {
			t.Fatalf("unexpected user agent: %q", got)
		}
		w.Header().Set("content-type", "application/json")
		_, _ = w.Write([]byte(`{"SOL":{"usdPrice":100.5,"blockId":1,"decimals":9,"priceChange24h":1.2},"SPL":{"usdPrice":0.2,"blockId":1,"decimals":6,"priceChange24h":-0.3}}`))
	}))
	defer ts.Close()

	client := NewDatapiClient(ts.URL)
	prices, err := client.FetchPrices(context.Background(), []string{"SOL", "SPL"})
	if err != nil {
		t.Fatalf("FetchPrices returned error: %v", err)
	}
	if len(prices) != 2 {
		t.Fatalf("expected 2 prices, got %d", len(prices))
	}
	if prices["SOL"].USDPrice != 100.5 {
		t.Fatalf("unexpected SOL price: %v", prices["SOL"].USDPrice)
	}
}

func TestDatapiClientFetchPriceValidatesToken(t *testing.T) {
	client := NewDatapiClient("https://datapi.jup.ag")
	if _, err := client.FetchPrice(context.Background(), ""); err == nil {
		t.Fatalf("expected validation error for empty token ID")
	}
}
