#!/usr/bin/env bash
# scripts/docker-up.sh
# OS 감지 → .env 적용 → docker compose up

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# OS 감지 및 .env 적용
bash "$SCRIPT_DIR/set-env.sh"

# Docker Compose 실행
cd "$ROOT_DIR"

if [ "$1" == "--build" ]; then
  echo "🔨 빌드 후 시작..."
  docker compose up -d --build
else
  echo "🚀 시작..."
  docker compose up -d
fi

echo ""
echo "📋 컨테이너 상태:"
docker compose ps
