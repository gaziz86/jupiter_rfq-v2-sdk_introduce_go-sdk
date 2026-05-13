package gosdk

import "testing"

func TestResolvePairConfigUsesKnownDefaults(t *testing.T) {
	cfg, err := ResolvePairConfig("sol/usdc")
	if err != nil {
		t.Fatalf("resolve pair config: %v", err)
	}
	if cfg.Name != "SOL/USDC" {
		t.Fatalf("unexpected pair name: %s", cfg.Name)
	}
	if cfg.MinTradeSizeBase != 1_000 {
		t.Fatalf("unexpected default min trade size: %d", cfg.MinTradeSizeBase)
	}
	if got := PairName(cfg.TokenPair); got != "SOL/USDC" {
		t.Fatalf("unexpected pair: %s", got)
	}
}

func TestResolvePairConfigDerivesFromTokenDecimals(t *testing.T) {
	cfg, err := ResolvePairConfig("ETH-USDC")
	if err != nil {
		t.Fatalf("resolve pair config: %v", err)
	}
	if cfg.MinTradeSizeBase != 100 {
		t.Fatalf("unexpected derived min trade size: %d", cfg.MinTradeSizeBase)
	}
	if got := PairName(cfg.TokenPair); got != "ETH/USDC" {
		t.Fatalf("unexpected pair: %s", got)
	}
}

func TestResolvePairConfigRejectsUnknownPair(t *testing.T) {
	if _, err := ResolvePairConfig("BTC/USDC"); err == nil {
		t.Fatal("expected unknown pair error")
	}
}
