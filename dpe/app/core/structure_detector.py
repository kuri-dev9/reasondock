import json
import re
from pathlib import Path

EXTENSION_HINTS: dict[str, str] = {
    ".md":       "markdown",
    ".markdown": "markdown",
    ".json":     "json",
    ".yaml":     "yaml",
    ".yml":      "yaml",
    ".py":       "code",
    ".js":       "code",
    ".ts":       "code",
    ".java":     "code",
    ".go":       "code",
    ".rs":       "code",
    ".c":        "code",
    ".cpp":      "code",
    ".cs":       "code",
    ".rb":       "code",
    ".php":      "code",
    ".sh":       "code",
    ".csv":      "table",
    ".tsv":      "table",
    ".xls":      "unknown",
    ".xlsx":     "unknown",
    ".log":      "log",
    ".txt":      "unknown",
}

_TIMESTAMP_RE = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}")
_CODE_PATTERNS = [
    re.compile(p) for p in [
        r"\bdef \w+\s*\(",
        r"\bclass \w+[\s(:]",
        r"\bimport \w+",
        r"\bfrom \w+\s+import\b",
        r"\bfunction\s+\w+\s*\(",
        r"\bconst\s+\w+\s*=",
        r"\bpublic\s+(class|void|static)\b",
        r"\bfunc\s+\w+\s*\(",
    ]
]


def _sniff_content(content: str) -> tuple[str, float]:
    if not content.strip():
        return "unknown", 0.0

    # sniffing 대상은 앞 2000자로 제한 (성능 + 충분한 패턴)
    sample = content[:2000]
    lines = sample.splitlines()
    total_lines = max(len(lines), 1)

    stripped = sample.strip()

    # Excel 추출 텍스트: file_parser가 시트명을 "[시트: ...]" 형식으로 붙인다.
    if any(line.startswith("[시트:") for line in lines[:5]):
        return "mixed", 0.45

    # JSON: 시작 문자로 빠른 판별 후 파싱 시도. 파싱 실패 시 다른 패턴으로 계속 판단한다.
    if stripped and stripped[0] in ("{", "["):
        try:
            json.loads(content)
            return "json", 0.92
        except (json.JSONDecodeError, ValueError):
            pass

    # Markdown: heading 줄 비율
    heading_lines = sum(1 for line in lines if re.match(r"^#{1,3}\s+\S", line))
    heading_ratio = heading_lines / total_lines
    if heading_ratio >= 0.03 or (heading_lines >= 2 and total_lines >= 5):
        conf = min(0.70 + heading_ratio * 4.0, 0.92)
        return "markdown", conf

    # YAML: key: value 패턴 + 구분자
    yaml_kv = sum(1 for line in lines if re.match(r"^[a-zA-Z_][a-zA-Z0-9_\-]*\s*:", line))
    has_yaml_sep = "---" in sample
    if yaml_kv / total_lines >= 0.30 or (has_yaml_sep and yaml_kv >= 2):
        return "yaml", 0.78

    # Code: 코드 패턴 누적
    code_hits = sum(1 for p in _CODE_PATTERNS if p.search(sample))
    if code_hits >= 2:
        return "code", min(0.60 + code_hits * 0.06, 0.88)

    # Log: timestamp 줄 비율
    ts_lines = sum(1 for line in lines if _TIMESTAMP_RE.search(line))
    ts_ratio = ts_lines / total_lines
    if ts_ratio >= 0.20:
        return "log", min(0.60 + ts_ratio * 0.60, 0.88)

    # Table/CSV: delimiter 반복
    delimiter_lines = sum(
        1 for line in lines if line.count(",") >= 3 or line.count("\t") >= 2
    )
    if delimiter_lines / total_lines >= 0.30:
        return "table", 0.72

    # Mixed: 여러 구조 신호가 동시에 존재
    signals = sum([
        heading_lines >= 1,
        ts_lines >= 1,
        delimiter_lines >= 1,
        code_hits >= 1,
    ])
    if signals >= 2:
        return "mixed", 0.48

    return "plain_text", 0.38


def detect(filename: str, content: str) -> tuple[str, float]:
    """
    Returns (structure_type, confidence 0.0~1.0).
    confidence < 0.55 이면 normalization 후보.
    """
    ext = Path(filename).suffix.lower()
    ext_hint = EXTENSION_HINTS.get(ext)

    sniff_type, sniff_conf = _sniff_content(content)

    # 확장자가 명확한 경우
    if ext_hint and ext_hint != "unknown":
        if ext_hint == sniff_type:
            # 일치 → 신뢰도 상승
            return ext_hint, min(sniff_conf + 0.08, 0.95)

        if sniff_type in ("plain_text", "unknown") or sniff_conf < 0.50:
            # content sniffing이 불명확 → 확장자 우선
            ext_conf = {
                "markdown": 0.82,
                "json":     0.86,
                "yaml":     0.80,
                "code":     0.82,
                "log":      0.76,
                "table":    0.76,
            }.get(ext_hint, 0.70)
            return ext_hint, ext_conf

        # 불일치 + sniffing 신뢰도 있음 → content 우선, 소폭 패널티
        return sniff_type, max(sniff_conf - 0.10, 0.28)

    # 확장자가 .txt이거나 미등록 → content sniffing에 의존
    return sniff_type, sniff_conf
