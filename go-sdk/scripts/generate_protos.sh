#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROTO_DIR="${SDK_DIR}/../protos"
PROTO_FILE="market_maker.proto"

if [[ ! -f "${PROTO_DIR}/${PROTO_FILE}" ]]; then
  echo "Cannot find proto file: ${PROTO_DIR}/${PROTO_FILE}" >&2
  exit 1
fi

export PATH="$(go env GOPATH)/bin:${PATH}"

cd "${SDK_DIR}"
protoc \
  --proto_path="${PROTO_DIR}" \
  --go_out=marketmakerpb \
  --go_opt=paths=source_relative \
  --go_opt=M${PROTO_FILE}=go-sdk/marketmakerpb \
  --go-grpc_out=marketmakerpb \
  --go-grpc_opt=paths=source_relative \
  --go-grpc_opt=M${PROTO_FILE}=go-sdk/marketmakerpb \
  "${PROTO_FILE}"

echo "Generated: ${SDK_DIR}/marketmakerpb/market_maker.pb.go"
echo "Generated: ${SDK_DIR}/marketmakerpb/market_maker_grpc.pb.go"