#!/usr/bin/env bash
# scripts/set-env.sh
# 현재 OS를 감지해서 적절한 .env 파일을 자동으로 적용합니다.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

OS="$(uname -s)"

case "$OS" in
  Darwin)
    ENV_FILE="$ROOT_DIR/.env.mac"
    ENV_LABEL="Mac"
    ;;
  Linux)
    ENV_FILE="$ROOT_DIR/.env.linux"
    ENV_LABEL="Linux"
    ;;
  *)
    echo "❌ 지원하지 않는 OS: $OS"
    exit 1
    ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ 환경 파일이 없습니다: $ENV_FILE"
  exit 1
fi

cp "$ENV_FILE" "$ROOT_DIR/.env"
echo "✅ [$ENV_LABEL] 환경 적용: $ENV_FILE → .env"
