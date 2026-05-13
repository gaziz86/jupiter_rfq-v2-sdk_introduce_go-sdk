package helpers

import gosdk "go-sdk"

func SwapUpdateTypeDescription(update *gosdk.SwapUpdate) string {
	if update == nil {
		return "nil"
	}
	switch update.GetMessageType() {
	case gosdk.SwapTypePing:
		return "ping"
	case gosdk.SwapTypePong:
		return "pong"
	case gosdk.SwapTypeConnectionReady:
		return "connection_ready"
	case gosdk.SwapTypeSwapAvailable:
		return "swap_available"
	case gosdk.SwapTypeSwapSubmit:
		return "swap_submit"
	case gosdk.SwapTypeTransactionConfirm:
		return "transaction_confirmed"
	case gosdk.SwapTypeError:
		return "error"
	default:
		return update.GetMessageType().String()
	}
}

func GetSwapStatusMessage(update *gosdk.SwapUpdate) string {
	if update == nil {
		return ""
	}
	return update.GetStatusMessage()
}

func ExtractSwapDetails(update *gosdk.SwapUpdate) (swapUUID string, unsignedTransaction string, ok bool) {
	if !gosdk.IsSwapAvailable(update) {
		return "", "", false
	}
	uuid := update.GetSwapUuid()
	tx := update.GetUnsignedTransaction()
	if uuid == "" || tx == "" {
		return "", "", false
	}
	return uuid, tx, true
}

func ExtractConfirmationDetails(update *gosdk.SwapUpdate) (swapUUID string, signature string, ok bool) {
	if !gosdk.IsSwapConfirmed(update) {
		return "", "", false
	}
	uuid := update.GetSwapUuid()
	sig := update.GetTransactionSignature()
	if uuid == "" || sig == "" {
		return "", "", false
	}
	return uuid, sig, true
}

func QuoteUpdateTypeDescription(update *gosdk.QuoteUpdate) string {
	if update == nil {
		return "nil"
	}
	switch {
	case gosdk.IsHeartbeat(update):
		return "heartbeat"
	case gosdk.IsNewQuote(update):
		return "new"
	case gosdk.IsUpdatedQuote(update):
		return "updated"
	case gosdk.IsExpiredQuote(update):
		return "expired"
	case gosdk.IsRejectedQuote(update):
		return "rejected"
	default:
		return update.GetUpdateType().String()
	}
}
