package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/gagliardetto/solana-go"
	"github.com/gagliardetto/solana-go/programs/system"
	"github.com/gagliardetto/solana-go/programs/token"
)

var (
	tokenProgramID           = solana.MustPublicKeyFromBase58("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
	associatedTokenProgramID = solana.MustPublicKeyFromBase58("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
)

const (
	defaultRPCURL          = "https://api.mainnet-beta.solana.com"
	defaultTokenName       = "My Custom Token"
	defaultTokenSymbol     = "MCT"
	defaultTokenDecimals   = uint(6)
	defaultInitialSupply   = uint64(1_000_000_000_000)
	defaultConfirmRetries  = 15
	defaultConfirmInterval = 2 * time.Second
	mintSize               = uint64(82)
)

type config struct {
	RPCURL        string
	Keypair       string
	TokenName     string
	TokenSymbol   string
	TokenDecimals uint
	InitialSupply uint64
}

type rpcClient struct {
	url    string
	client *http.Client
}

type rpcEnvelope struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      int         `json:"id"`
	Method  string      `json:"method"`
	Params  interface{} `json:"params,omitempty"`
}

type createATAInstruction struct {
	payer  solana.PublicKey
	ata    solana.PublicKey
	wallet solana.PublicKey
	mint   solana.PublicKey
}

func main() {
	log.SetFlags(0)

	cfg, err := loadConfig()
	if err != nil {
		log.Fatalf("invalid config: %v", err)
	}

	payer, err := loadKeypair(cfg.Keypair)
	if err != nil {
		log.Fatalf("load keypair: %v", err)
	}

	rpc := newRPCClient(cfg.RPCURL)
	mintWallet := solana.NewWallet()

	log.Printf("=== SPL Token Deployment ===")
	log.Printf("RPC endpoint : %s", cfg.RPCURL)
	log.Printf("Payer wallet : %s", payer.PublicKey())
	log.Printf("Token name   : %s (%s)", cfg.TokenName, cfg.TokenSymbol)
	log.Printf("Decimals     : %d", cfg.TokenDecimals)
	log.Printf("Initial supply: %f (raw: %d smallest units)", humanSupply(cfg.InitialSupply, cfg.TokenDecimals), cfg.InitialSupply)

	log.Printf("\n--- Step 1: Creating mint account ---")
	log.Printf("New mint address: %s", mintWallet.PublicKey())

	rentExemption, err := rpc.getMinimumBalanceForRentExemption(mintSize)
	if err != nil {
		log.Fatalf("get rent exemption: %v", err)
	}
	log.Printf("Rent-exempt minimum: %d lamports (%.6f SOL)", rentExemption, float64(rentExemption)/1e9)

	createMintIx := system.NewCreateAccountInstruction(
		rentExemption,
		mintSize,
		tokenProgramID,
		payer.PublicKey(),
		mintWallet.PublicKey(),
	).Build()
	initMintIx := token.NewInitializeMint2Instruction(
		uint8(cfg.TokenDecimals),
		payer.PublicKey(),
		payer.PublicKey(),
		mintWallet.PublicKey(),
	).Build()

	createMintTx, err := buildTransaction(rpc, payer.PublicKey(), createMintIx, initMintIx)
	if err != nil {
		log.Fatalf("build create-mint transaction: %v", err)
	}
	if err := signTransaction(createMintTx, payer, mintWallet.PrivateKey); err != nil {
		log.Fatalf("sign create-mint transaction: %v", err)
	}

	log.Printf("Sending create-mint transaction...")
	sig, err := rpc.sendTransaction(createMintTx)
	if err != nil {
		log.Fatalf("send create-mint transaction: %v", err)
	}
	log.Printf("Transaction signature: %s", sig)
	confirmed, err := rpc.confirmTransaction(sig, defaultConfirmRetries, defaultConfirmInterval)
	if err != nil {
		log.Fatalf("confirm create-mint transaction: %v", err)
	}
	if !confirmed {
		log.Fatalf("mint creation not confirmed")
	}
	log.Printf("Mint account created successfully!")

	log.Printf("\n--- Step 2: Creating associated token account ---")
	createATAIx, ata, err := newCreateATAInstruction(payer.PublicKey(), payer.PublicKey(), mintWallet.PublicKey())
	if err != nil {
		log.Fatalf("build create-ATA instruction: %v", err)
	}
	log.Printf("Associated token account: %s", ata)

	createATATx, err := buildTransaction(rpc, payer.PublicKey(), createATAIx)
	if err != nil {
		log.Fatalf("build create-ATA transaction: %v", err)
	}
	if err := signTransaction(createATATx, payer); err != nil {
		log.Fatalf("sign create-ATA transaction: %v", err)
	}

	log.Printf("Sending create-ATA transaction...")
	sig, err = rpc.sendTransaction(createATATx)
	if err != nil {
		log.Fatalf("send create-ATA transaction: %v", err)
	}
	log.Printf("Transaction signature: %s", sig)
	confirmed, err = rpc.confirmTransaction(sig, defaultConfirmRetries, defaultConfirmInterval)
	if err != nil {
		log.Fatalf("confirm create-ATA transaction: %v", err)
	}
	if !confirmed {
		log.Fatalf("ATA creation not confirmed")
	}
	log.Printf("Associated token account created!")

	log.Printf("\n--- Step 3: Minting initial supply ---")
	mintToIx := token.NewMintToInstruction(
		cfg.InitialSupply,
		mintWallet.PublicKey(),
		ata,
		payer.PublicKey(),
		nil,
	).Build()
	mintToTx, err := buildTransaction(rpc, payer.PublicKey(), mintToIx)
	if err != nil {
		log.Fatalf("build mint-to transaction: %v", err)
	}
	if err := signTransaction(mintToTx, payer); err != nil {
		log.Fatalf("sign mint-to transaction: %v", err)
	}

	log.Printf("Sending mint-to transaction...")
	sig, err = rpc.sendTransaction(mintToTx)
	if err != nil {
		log.Fatalf("send mint-to transaction: %v", err)
	}
	log.Printf("Transaction signature: %s", sig)
	confirmed, err = rpc.confirmTransaction(sig, defaultConfirmRetries, defaultConfirmInterval)
	if err != nil {
		log.Fatalf("confirm mint-to transaction: %v", err)
	}
	if !confirmed {
		log.Fatalf("mint-to not confirmed")
	}
	log.Printf("Initial supply minted!")

	log.Printf("\n========================================")
	log.Printf("  SPL Token Deployed Successfully!")
	log.Printf("========================================")
	log.Printf("  Mint address     : %s", mintWallet.PublicKey())
	log.Printf("  Token account    : %s", ata)
	log.Printf("  Mint authority   : %s", payer.PublicKey())
	log.Printf("  Freeze authority : %s", payer.PublicKey())
	log.Printf("  Decimals         : %d", cfg.TokenDecimals)
	log.Printf("  Total supply     : %f", humanSupply(cfg.InitialSupply, cfg.TokenDecimals))
	log.Printf("========================================")
	log.Printf("  Explorer: https://explorer.solana.com/address/%s", mintWallet.PublicKey())
	log.Printf("========================================")
}

func loadConfig() (config, error) {
	var cfg config
	flag.StringVar(&cfg.RPCURL, "rpc-url", envOrDefault("SOLANA_RPC_URL", defaultRPCURL), "Solana RPC endpoint")
	flag.StringVar(&cfg.Keypair, "keypair", os.Getenv("SOLANA_KEYPAIR"), "Base58 private key or path to a Solana JSON keypair file")
	flag.StringVar(&cfg.TokenName, "token-name", envOrDefault("TOKEN_NAME", defaultTokenName), "Display token name")
	flag.StringVar(&cfg.TokenSymbol, "token-symbol", envOrDefault("TOKEN_SYMBOL", defaultTokenSymbol), "Display token symbol")
	flag.UintVar(&cfg.TokenDecimals, "decimals", uintFromEnv("TOKEN_DECIMALS", defaultTokenDecimals), "SPL token decimals")
	flag.Uint64Var(&cfg.InitialSupply, "initial-supply", uint64FromEnv("INITIAL_SUPPLY", defaultInitialSupply), "Initial supply in smallest units")
	flag.Parse()

	if strings.TrimSpace(cfg.Keypair) == "" {
		return cfg, errors.New("SOLANA_KEYPAIR is required (base58 private key or path to JSON file)")
	}
	if cfg.TokenDecimals > 255 {
		return cfg, fmt.Errorf("decimals must fit in uint8, got %d", cfg.TokenDecimals)
	}
	return cfg, nil
}

func newRPCClient(url string) *rpcClient {
	return &rpcClient{
		url: strings.TrimSpace(url),
		client: &http.Client{
			Timeout: 20 * time.Second,
		},
	}
}

func buildTransaction(rpc *rpcClient, payer solana.PublicKey, instructions ...solana.Instruction) (*solana.Transaction, error) {
	blockhash, err := rpc.getLatestBlockhash()
	if err != nil {
		return nil, err
	}
	return solana.NewTransaction(instructions, blockhash, solana.TransactionPayer(payer))
}

func newCreateATAInstruction(payer, wallet, mint solana.PublicKey) (solana.Instruction, solana.PublicKey, error) {
	ata, _, err := solana.FindAssociatedTokenAddress(wallet, mint)
	if err != nil {
		return nil, solana.PublicKey{}, fmt.Errorf("find associated token address: %w", err)
	}
	return &createATAInstruction{
		payer:  payer,
		ata:    ata,
		wallet: wallet,
		mint:   mint,
	}, ata, nil
}

func (ix *createATAInstruction) ProgramID() solana.PublicKey {
	return associatedTokenProgramID
}

func (ix *createATAInstruction) Accounts() []*solana.AccountMeta {
	return []*solana.AccountMeta{
		{PublicKey: ix.payer, IsSigner: true, IsWritable: true},
		{PublicKey: ix.ata, IsSigner: false, IsWritable: true},
		{PublicKey: ix.wallet, IsSigner: false, IsWritable: false},
		{PublicKey: ix.mint, IsSigner: false, IsWritable: false},
		{PublicKey: solana.SystemProgramID, IsSigner: false, IsWritable: false},
		{PublicKey: tokenProgramID, IsSigner: false, IsWritable: false},
	}
}

func (ix *createATAInstruction) Data() ([]byte, error) {
	return []byte{}, nil
}

func (c *rpcClient) post(body rpcEnvelope, out interface{}) error {
	payload, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal rpc request: %w", err)
	}

	resp, err := c.client.Post(c.url, "application/json", bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("rpc post %s: %w", body.Method, err)
	}
	defer resp.Body.Close()

	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read rpc response %s: %w", body.Method, err)
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("rpc %s http %d: %s", body.Method, resp.StatusCode, strings.TrimSpace(string(responseBody)))
	}
	if err := json.Unmarshal(responseBody, out); err != nil {
		return fmt.Errorf("decode rpc response %s: %w", body.Method, err)
	}
	return nil
}

func (c *rpcClient) getLatestBlockhash() (solana.Hash, error) {
	var response struct {
		Result struct {
			Value struct {
				Blockhash string `json:"blockhash"`
			} `json:"value"`
		} `json:"result"`
		Error *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := c.post(rpcEnvelope{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "getLatestBlockhash",
		Params:  []interface{}{map[string]string{"commitment": "finalized"}},
	}, &response); err != nil {
		return solana.Hash{}, err
	}
	if response.Error != nil {
		return solana.Hash{}, fmt.Errorf("getLatestBlockhash rpc error %d: %s", response.Error.Code, response.Error.Message)
	}
	if response.Result.Value.Blockhash == "" {
		return solana.Hash{}, errors.New("missing blockhash in response")
	}
	return solana.HashFromBase58(response.Result.Value.Blockhash)
}

func (c *rpcClient) getMinimumBalanceForRentExemption(dataLen uint64) (uint64, error) {
	var response struct {
		Result uint64 `json:"result"`
		Error  *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := c.post(rpcEnvelope{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "getMinimumBalanceForRentExemption",
		Params:  []interface{}{dataLen},
	}, &response); err != nil {
		return 0, err
	}
	if response.Error != nil {
		return 0, fmt.Errorf("getMinimumBalanceForRentExemption rpc error %d: %s", response.Error.Code, response.Error.Message)
	}
	return response.Result, nil
}

func (c *rpcClient) sendTransaction(tx *solana.Transaction) (string, error) {
	encodedTx, err := tx.MarshalBinary()
	if err != nil {
		return "", fmt.Errorf("marshal transaction: %w", err)
	}

	var response struct {
		Result string `json:"result"`
		Error  *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := c.post(rpcEnvelope{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "sendTransaction",
		Params: []interface{}{
			base64.StdEncoding.EncodeToString(encodedTx),
			map[string]interface{}{
				"encoding":            "base64",
				"skipPreflight":       false,
				"preflightCommitment": "confirmed",
			},
		},
	}, &response); err != nil {
		return "", err
	}
	if response.Error != nil {
		return "", fmt.Errorf("sendTransaction rpc error %d: %s", response.Error.Code, response.Error.Message)
	}
	if response.Result == "" {
		return "", errors.New("missing signature in sendTransaction response")
	}
	return response.Result, nil
}

func (c *rpcClient) confirmTransaction(signature string, maxRetries int, interval time.Duration) (bool, error) {
	for attempt := 1; attempt <= maxRetries; attempt++ {
		time.Sleep(interval)

		var response struct {
			Result struct {
				Value []struct {
					Err                interface{} `json:"err"`
					ConfirmationStatus string      `json:"confirmationStatus"`
				} `json:"value"`
			} `json:"result"`
			Error *struct {
				Code    int    `json:"code"`
				Message string `json:"message"`
			} `json:"error"`
		}
		if err := c.post(rpcEnvelope{
			JSONRPC: "2.0",
			ID:      1,
			Method:  "getSignatureStatuses",
			Params:  []interface{}{[]string{signature}},
		}, &response); err != nil {
			return false, err
		}
		if response.Error != nil {
			return false, fmt.Errorf("getSignatureStatuses rpc error %d: %s", response.Error.Code, response.Error.Message)
		}
		if len(response.Result.Value) > 0 {
			status := response.Result.Value[0]
			if status.Err != nil {
				return false, fmt.Errorf("transaction failed: %v", status.Err)
			}
			if status.ConfirmationStatus == "confirmed" || status.ConfirmationStatus == "finalized" {
				log.Printf("Transaction confirmed (attempt %d/%d): status = %s", attempt, maxRetries, status.ConfirmationStatus)
				return true, nil
			}
		}
		log.Printf("Waiting for confirmation (attempt %d/%d)...", attempt, maxRetries)
	}
	return false, nil
}

func loadKeypair(value string) (solana.PrivateKey, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return nil, errors.New("empty keypair value")
	}

	if contents, err := os.ReadFile(trimmed); err == nil {
		pk, err := solana.PrivateKeyFromSolanaKeygenFileBytes(contents)
		if err == nil {
			return pk, nil
		}
	}

	pk, err := solana.PrivateKeyFromBase58(trimmed)
	if err != nil {
		return nil, fmt.Errorf("parse base58 keypair: %w", err)
	}
	return pk, nil
}

func signTransaction(tx *solana.Transaction, privateKeys ...solana.PrivateKey) error {
	if len(privateKeys) == 0 {
		return errors.New("at least one signer is required")
	}

	lookup := make(map[solana.PublicKey]solana.PrivateKey, len(privateKeys))
	for _, privateKey := range privateKeys {
		lookup[privateKey.PublicKey()] = privateKey
	}

	_, err := tx.Sign(func(key solana.PublicKey) *solana.PrivateKey {
		privateKey, ok := lookup[key]
		if !ok {
			return nil
		}
		privateKeyCopy := privateKey
		return &privateKeyCopy
	})
	if err != nil {
		return fmt.Errorf("sign transaction: %w", err)
	}
	return nil
}

func envOrDefault(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func uintFromEnv(key string, fallback uint) uint {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return fallback
	}
	return uint(parsed)
}

func uint64FromEnv(key string, fallback uint64) uint64 {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return fallback
	}
	return parsed
}

func humanSupply(raw uint64, decimals uint) float64 {
	divisor := 1.0
	for range decimals {
		divisor *= 10
	}
	return float64(raw) / divisor
}
