from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import sqrt
from typing import Any


CALL_TYPE = {
    "1": "Attach_MO",
    "2": "Attach_MT",
    "3": "Service_MO",
    "4": "Service_MT",
    "5": "TAU",
    "6": "Paging",
    "7": "ExtService_MO",
    "8": "ExtService_MT",
    "9": "Detach_MO",
    "10": "S1HO_InterMME",
}

ERROR_INTERFACE = {
    "1": "S6a_Diameter",
    "2": "S1MME_S1AP",
    "3": "S11_GTPv2C",
    "4": "S10_GTPv2C",
    "5": "S1MME_NAS-EMM",
    "6": "S1MME_NAS-ESM",
    "7": "S3_GTPv1C",
    "8": "S13_Diameter",
}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _ratio(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def _top(counter: Counter, limit: int = 10) -> list[dict[str, Any]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _bucket_label(epoch_microseconds: int) -> str:
    bucket_us = 15 * 60 * 1_000_000
    bucket = (epoch_microseconds // bucket_us) * bucket_us
    dt = datetime.fromtimestamp(bucket / 1_000_000, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _failure_key(record: dict[str, str]) -> str:
    interface = record.get("first_error_interface_protocol") or "0"
    cause = record.get("first_error_cause") or "0"
    message = record.get("first_error_message") or "0"
    interface_name = ERROR_INTERFACE.get(interface, f"INTERFACE_{interface}")
    cause_name = "TIMEOUT" if cause == "900" else f"CAUSE_{cause}"
    return f"{interface_name}|MESSAGE_{message}|{cause_name}"


def aggregate_records(records: list[dict[str, str]], parse_stats: dict[str, Any], filename: str) -> dict[str, Any]:
    total = len(records)
    attempts = 0
    successes = 0
    drops = 0
    failures = 0

    call_types: Counter[str] = Counter()
    call_type_failures: Counter[str] = Counter()
    failures_by_reason: Counter[str] = Counter()
    failures_by_mme: Counter[str] = Counter()
    failures_by_enb: Counter[str] = Counter()
    failures_by_sgw: Counter[str] = Counter()
    apn_distribution: Counter[str] = Counter()
    bucket_total: Counter[str] = Counter()
    bucket_fail: Counter[str] = Counter()

    first_time = None
    last_time = None

    for record in records:
        attempt = _int(record.get("attempt_flag"))
        success = _int(record.get("success_flag"))
        drop = _int(record.get("drop_flag"))
        is_detach_cleanup = (
            record.get("call_type") == "9"
            and record.get("detach_flag") == "1"
            and success == 1
        )
        is_failure = attempt == 1 and success == 0 and not is_detach_cleanup

        attempts += 1 if attempt else 0
        successes += 1 if success else 0
        drops += 1 if drop else 0
        failures += 1 if is_failure else 0

        call_type = CALL_TYPE.get(record.get("call_type"), f"CALL_TYPE_{record.get('call_type', '0')}")
        call_types[call_type] += 1
        apn_distribution[record.get("APN") or "(empty)"] += 1

        call_start = _int(record.get("call_start_time"), -1)
        if call_start >= 0:
            first_time = call_start if first_time is None else min(first_time, call_start)
            last_time = call_start if last_time is None else max(last_time, call_start)
            bucket = _bucket_label(call_start)
            bucket_total[bucket] += 1
            if is_failure:
                bucket_fail[bucket] += 1

        if is_failure:
            call_type_failures[call_type] += 1
            failures_by_reason[_failure_key(record)] += 1
            failures_by_mme[record.get("MME_ID") or "(empty)"] += 1
            failures_by_enb[record.get("First_eNB_ID") or "(empty)"] += 1
            failures_by_sgw[record.get("SGW_ID") or "(empty)"] += 1

    timeline = []
    rates = []
    for bucket in sorted(bucket_total):
        fail_count = bucket_fail[bucket]
        total_count = bucket_total[bucket]
        rate = _ratio(fail_count, total_count)
        rates.append(rate)
        timeline.append(
            {
                "bucket": bucket,
                "total": total_count,
                "fail": fail_count,
                "fail_rate": rate,
            }
        )

    mean_rate = sum(rates) / len(rates) if rates else 0.0
    std_rate = sqrt(sum((rate - mean_rate) ** 2 for rate in rates) / len(rates)) if rates else 0.0
    threshold = mean_rate + (2 * std_rate)
    anomalous = [item for item in timeline if item["fail_rate"] > threshold and item["fail"] > 0]

    return {
        "file_info": {
            "filename": filename,
            "period": {
                "start_us": first_time,
                "end_us": last_time,
            },
            "total_records": total,
            "parse": parse_stats,
        },
        "overall": {
            "total": total,
            "attempt": attempts,
            "success": successes,
            "fail": failures,
            "drop": drops,
            "fail_rate": _ratio(failures, attempts),
            "drop_rate": _ratio(drops, attempts),
        },
        "top_call_types": _top(call_types),
        "call_type_failures": _top(call_type_failures),
        "top_failures": _top(failures_by_reason),
        "affected_equipment": {
            "mme": _top(failures_by_mme, 5),
            "enb": _top(failures_by_enb, 5),
            "sgw": _top(failures_by_sgw, 5),
        },
        "apn_distribution": _top(apn_distribution, 10),
        "timeline": timeline,
        "time_anomaly": {
            "detected": bool(anomalous),
            "threshold": round(threshold, 4),
            "windows": anomalous,
        },
    }


def build_candidates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    overall = summary["overall"]
    fail_total = overall["fail"]
    candidates: list[dict[str, Any]] = []
    top_failures = summary["top_failures"]

    def add(cause: str, confidence: float, evidence: list[str]) -> None:
        candidates.append(
            {
                "rank": 0,
                "suspected_cause": cause,
                "confidence": round(min(confidence, 0.99), 2),
                "evidence": evidence,
            }
        )

    if top_failures:
        top = top_failures[0]
        key = top["key"]
        ratio = top["count"] / fail_total if fail_total else 0
        if "TIMEOUT" in key:
            add(
                "transport_reachability",
                0.55 + ratio * 0.4,
                [f"Top failure is {key} ({top['count']} records, {ratio:.1%} of failures)."],
            )
        if key.startswith("S6a_Diameter"):
            add(
                "HSS_authentication_failure",
                0.5 + ratio * 0.35,
                [f"S6a Diameter failure dominates: {key} ({top['count']} records)."],
            )
        if key.startswith("S11_GTPv2C"):
            add(
                "SGW_PGW_bearer_issue",
                0.5 + ratio * 0.35,
                [f"S11 GTPv2C failure is prominent: {key} ({top['count']} records)."],
            )
        if "S1MME_NAS-EMM" in key:
            add(
                "NAS_signaling_issue",
                0.5 + ratio * 0.3,
                [f"NAS-EMM first error appears in top failures: {key}."],
            )

    for equipment_type, cause in [
        ("mme", "MME_node_issue"),
        ("enb", "eNB_radio_issue"),
        ("sgw", "SGW_PGW_bearer_issue"),
    ]:
        entries = summary["affected_equipment"][equipment_type]
        if entries and fail_total:
            top = entries[0]
            ratio = top["count"] / fail_total
            if ratio >= 0.35:
                add(
                    cause,
                    0.45 + ratio * 0.35,
                    [f"{equipment_type.upper()} {top['key']} has {top['count']} failures ({ratio:.1%} of failures)."],
                )

    if summary["time_anomaly"]["detected"]:
        windows = summary["time_anomaly"]["windows"]
        add(
            "transient_network_event",
            0.6,
            [f"Failure-rate spike detected in {len(windows)} 15-minute window(s)."],
        )

    if not candidates:
        add(
            "insufficient_evidence",
            0.25,
            ["No dominant failure pattern exceeded the initial rule thresholds."],
        )

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    for index, candidate in enumerate(candidates, start=1):
        candidate["rank"] = index
    return candidates


def render_markdown(summary: dict[str, Any]) -> str:
    overall = summary["overall"]
    candidates = summary.get("rca_candidates", [])
    top = candidates[0] if candidates else None
    lines = [
        "## RCA 분석 결과",
        "",
        f"- 파일: `{summary['file_info']['filename']}`",
        f"- 총 레코드: {overall['total']:,}",
        f"- 시도/성공/실패/절단: {overall['attempt']:,} / {overall['success']:,} / {overall['fail']:,} / {overall['drop']:,}",
        f"- 실패율: {overall['fail_rate']:.2%}",
        "",
    ]
    if top:
        lines.extend(
            [
                f"### 1순위 후보: `{top['suspected_cause']}`",
                "",
                f"- 신뢰도: {top['confidence']:.2f}",
                *[f"- 근거: {item}" for item in top["evidence"]],
                "",
            ]
        )

    lines.append("### Top Failures")
    if summary["top_failures"]:
        for item in summary["top_failures"][:5]:
            lines.append(f"- `{item['key']}`: {item['count']:,}")
    else:
        lines.append("- 실패 패턴 없음")

    lines.extend(["", "### Affected Equipment"])
    for label, entries in summary["affected_equipment"].items():
        rendered = ", ".join(f"{item['key']}({item['count']})" for item in entries) or "없음"
        lines.append(f"- {label.upper()}: {rendered}")

    lines.extend(["", "```json", "{", f'  "result_file": "{summary.get("result_path", "")}"', "}", "```"])
    return "\n".join(lines)
