package gosdk

import "fmt"

type ErrorKind string

const (
	ErrorKindConnection    ErrorKind = "connection"
	ErrorKindGRPC          ErrorKind = "grpc"
	ErrorKindValidation    ErrorKind = "validation"
	ErrorKindStreaming     ErrorKind = "streaming"
	ErrorKindTimeout       ErrorKind = "timeout"
	ErrorKindConfiguration ErrorKind = "configuration"
	ErrorKindOther         ErrorKind = "other"
)

type Error struct {
	Kind ErrorKind
	Msg  string
	Err  error
}

func (e *Error) Error() string {
	if e == nil {
		return ""
	}
	if e.Err == nil {
		return fmt.Sprintf("%s error: %s", e.Kind, e.Msg)
	}
	if e.Msg == "" {
		return fmt.Sprintf("%s error: %v", e.Kind, e.Err)
	}
	return fmt.Sprintf("%s error: %s: %v", e.Kind, e.Msg, e.Err)
}

func (e *Error) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Err
}

func newError(kind ErrorKind, msg string, err error) error {
	return &Error{Kind: kind, Msg: msg, Err: err}
}
