package helpers

import (
	"testing"

	gosdk "go-sdk"
)

func TestExtractSwapDetails(t *testing.T) {
	update := &gosdk.SwapUpdate{
		MessageType:         gosdk.SwapTypeSwapAvailable.Enum(),
		SwapUuid:            strPtr("uuid-1"),
		UnsignedTransaction: strPtr("tx"),
	}
	uuid, tx, ok := ExtractSwapDetails(update)
	if !ok {
		t.Fatalf("expected swap details extraction to succeed")
	}
	if uuid != "uuid-1" || tx != "tx" {
		t.Fatalf("unexpected details: uuid=%s tx=%s", uuid, tx)
	}
}

func TestExtractConfirmationDetails(t *testing.T) {
	update := &gosdk.SwapUpdate{
		MessageType:          gosdk.SwapTypeTransactionConfirm.Enum(),
		SwapUuid:             strPtr("uuid-2"),
		TransactionSignature: strPtr("sig"),
	}
	uuid, sig, ok := ExtractConfirmationDetails(update)
	if !ok {
		t.Fatalf("expected confirmation extraction to succeed")
	}
	if uuid != "uuid-2" || sig != "sig" {
		t.Fatalf("unexpected details: uuid=%s sig=%s", uuid, sig)
	}
}

func strPtr(v string) *string { return &v }
