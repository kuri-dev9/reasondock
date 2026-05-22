#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${DPE_BASE_URL:-http://localhost:8200}"
PASS=0
FAIL=0

_check() {
    local label="$1"
    local result="$2"
    local expect="$3"
    if echo "$result" | grep -q "$expect"; then
        echo "  PASS  $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $label (expected '$expect')"
        echo "        got: $result"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== DPE Smoke Test ==="
echo "Target: $BASE_URL"
echo ""

# --- /health ---
echo "[1] GET /health"
R=$(curl -sf "$BASE_URL/health")
_check "/health → status ok" "$R" '"status":"ok"'

# --- /status ---
echo "[2] GET /status"
R=$(curl -sf "$BASE_URL/status")
_check "/status → min_confidence_threshold" "$R" "min_confidence_threshold"

# --- markdown 파일 (구조 명확) ---
echo "[3] POST /process — markdown"
R=$(curl -sf -X POST "$BASE_URL/process" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "smoke_md",
    "filename": "architecture.md",
    "content": "# 시스템 개요\n\n## 목적\n\n이 시스템은 LLM 앞단에서 동작합니다.\n\n## 구성\n\n- backend\n- frontend"
  }')
_check "markdown → structure_type markdown" "$R" '"structure_type":"markdown"'
_check "markdown → chunk_strategy heading-aware" "$R" '"chunk_strategy":"heading-aware"'
_check "markdown → normalization_applied false" "$R" '"normalization_applied":false'
_check "markdown → retrieval_hints heading" "$R" '"heading"'

# --- json 파일 ---
echo "[4] POST /process — json"
R=$(curl -sf -X POST "$BASE_URL/process" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "smoke_json",
    "filename": "data.json",
    "content": "{\"name\": \"test\", \"version\": \"1.0\", \"items\": [\"a\", \"b\", \"c\"]}"
  }')
_check "json → structure_type json" "$R" '"structure_type":"json"'
_check "json → chunk_strategy json-object" "$R" '"chunk_strategy":"json-object"'

# --- log 파일 ---
echo "[5] POST /process — log"
R=$(curl -sf -X POST "$BASE_URL/process" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "smoke_log",
    "filename": "app.log",
    "content": "2026-05-21 09:00:01 INFO server started\n2026-05-21 09:01:15 WARN slow query detected\n2026-05-21 09:02:30 ERROR connection timeout"
  }')
_check "log → structure_type log" "$R" '"structure_type":"log"'
_check "log → chunk_strategy log-window" "$R" '"chunk_strategy":"log-window"'

# --- plain_text 파일 (normalization 비활성화) ---
echo "[6] POST /process — plain_text (normalization off)"
R=$(curl -sf -X POST "$BASE_URL/process" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "smoke_txt",
    "filename": "report.txt",
    "content": "장애 시각 2026-05-10 오후 2시 30분. 원인은 서버 다운. 영향 사용자 1000명. 복구 완료 3시간 후."
  }')
_check "plain_text → normalization_applied false" "$R" '"normalization_applied":false'
_check "plain_text → chunk_strategy sliding-window" "$R" '"chunk_strategy":"sliding-window"'

# --- 빈 content ---
echo "[7] POST /process — empty content"
R=$(curl -sf -X POST "$BASE_URL/process" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "smoke_empty",
    "filename": "empty.txt",
    "content": ""
  }')
_check "empty → structure_type unknown" "$R" '"structure_type":"unknown"'
_check "empty → confidence 0.0" "$R" '"structure_confidence":0.0'

# --- 결과 ---
echo ""
echo "=== 결과: PASS $PASS / FAIL $FAIL ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
