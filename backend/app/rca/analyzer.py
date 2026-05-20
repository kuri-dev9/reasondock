from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import sqrt
from typing import Any

from app.rca.cause_dictionary import resolve_cause
from app.rca.knowledge_loader import lookup_cause, lookup_error_cause, lookup_message


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


def _message_label(interface: str, message: Any) -> str:
    meta = lookup_message(interface, message)
    if not meta:
        return f"Message code {message}"

    if meta.get("name") and meta.get("abbreviation"):
        label = f"{meta['name']} ({meta['abbreviation']})"
    elif meta.get("name"):
        label = str(meta["name"])
    elif meta.get("message"):
        label = str(meta["message"])
    elif meta.get("procedure"):
        label = str(meta["procedure"])
    elif meta.get("meaning"):
        label = str(meta["meaning"])
    else:
        label = f"Message code {message}"
    return f"{label} ({message})"


def _cause_label(interface: str, message: Any, cause: Any) -> str:
    if str(cause) == "900":
        return "TIMEOUT (900)"

    xdr_meta = lookup_error_cause(interface, cause)
    if xdr_meta:
        label = str(xdr_meta.get("meaning") or xdr_meta.get("name") or xdr_meta.get("message_type") or "Known cause")
        if xdr_meta.get("group"):
            label = f"{label} [{xdr_meta['group']}]"
        return f"{label} ({cause})"

    release_meta = lookup_cause(interface, cause)
    if release_meta:
        return f"{release_meta.get('name', 'Unknown cause')} ({cause})"

    local_cause = resolve_cause(interface, message, cause)
    if local_cause.get("known"):
        return f"{local_cause.get('semantic')} ({cause})"
    return f"Cause code {cause}"


def _failure_key(record: dict[str, str]) -> str:
    interface = record.get("first_error_interface_protocol") or "0"
    cause = record.get("first_error_cause") or "0"
    message = record.get("first_error_message") or "0"
    interface_name = ERROR_INTERFACE.get(interface, f"INTERFACE_{interface}")
    message_name = _message_label(interface_name, message)
    cause_name = _cause_label(interface_name, message, cause)
    return f"{interface_name}|{message_name}|{cause_name}"


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
            interface = record.get("first_error_interface_protocol") or "0"

            if interface in ("2", "5"):
                failures_by_mme[record.get("MME_ID") or "(empty)"] += 1
            if interface == "2":
                failures_by_enb[record.get("First_eNB_ID") or "(empty)"] += 1
            if interface == "3":
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

    if not failures_by_mme or not failures_by_enb or not failures_by_sgw:
        for record in records:
            attempt = _int(record.get("attempt_flag"))
            success = _int(record.get("success_flag"))
            is_detach_cleanup = (
                record.get("call_type") == "9"
                and record.get("detach_flag") == "1"
                and success == 1
            )
            is_failure = attempt == 1 and success == 0 and not is_detach_cleanup
            if is_failure:
                if not failures_by_mme:
                    failures_by_mme[record.get("MME_ID") or "(empty)"] += 1
                if not failures_by_enb:
                    failures_by_enb[record.get("First_eNB_ID") or "(empty)"] += 1
                if not failures_by_sgw:
                    failures_by_sgw[record.get("SGW_ID") or "(empty)"] += 1

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
        "analysis_mode": "healthy" if failures == 0 and drops == 0 else "incident",
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
    added_causes: set[str] = set()

    if summary.get("analysis_mode") == "healthy":
        return []

    def add(cause: str, confidence: float, evidence: list[str]) -> None:
        evidence_key = f"{cause}|{evidence[0] if evidence else ''}"
        if evidence_key in added_causes:
            return
        added_causes.add(evidence_key)
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

    for failure in top_failures[:5]:
        key = failure["key"]
        ratio = failure["count"] / fail_total if fail_total else 0
        if key.startswith("S6a_Diameter"):
            add(
                "HSS_authentication_failure",
                0.35 + ratio * 0.35,
                [f"S6a Diameter failure observed: {key} ({failure['count']} records, {ratio:.1%} of failures)."],
            )
        if key.startswith("S11_GTPv2C"):
            add(
                "SGW_PGW_bearer_issue",
                0.35 + ratio * 0.35,
                [f"S11 GTPv2C failure observed: {key} ({failure['count']} records, {ratio:.1%} of failures)."],
            )
        if "S1MME_NAS-EMM" in key:
            add(
                "NAS_signaling_issue",
                0.35 + ratio * 0.3,
                [f"NAS-EMM first error observed: {key} ({failure['count']} records, {ratio:.1%} of failures)."],
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
    period = summary["file_info"].get("period", {})

    def format_period(epoch_microseconds: int | None) -> str:
        if epoch_microseconds is None:
            return "N/A"
        dt = datetime.fromtimestamp(epoch_microseconds / 1_000_000, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")

    def split_failure_key(key: str) -> tuple[str, str, str]:
        parts = key.split("|", 2)
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        if len(parts) == 2:
            return parts[0], parts[1], ""
        return key, "", ""

    def pct(value: float) -> str:
        return f"{value:.2%}"

    if summary.get("analysis_mode") == "healthy":
        call_types = ", ".join(
            f"{item['key']}({item['count']:,})" for item in summary.get("top_call_types", [])[:5]
        ) or "없음"
        lines = [
            "## 서비스 상태 요약",
            "",
            f"- 파일: `{summary['file_info']['filename']}`",
            f"- 기간: {format_period(period.get('start_us'))} ~ {format_period(period.get('end_us'))}",
            "- 분석 대상 기간 동안 Call Failure 및 Drop 현상은 관찰되지 않았습니다.",
            f"- 총 레코드 / 시도 / 성공: {overall['total']:,} / {overall['attempt']:,} / {overall['success']:,}",
            f"- 성공률 / 실패율 / 절단율: {pct(_ratio(overall['success'], overall['attempt']))} / {pct(overall['fail_rate'])} / {pct(overall['drop_rate'])}",
            "",
            "## 정상 동작 지표",
            "",
            "- Call Failure: 0건",
            "- Drop: 0건",
            "- 주요 실패 패턴: 없음",
            f"- 주요 절차 분포: {call_types}",
            "",
            "## 인터페이스 상태",
            "",
            "- S1-MME: 특이 오류 미관찰",
            "- S11: 세션 생성 실패 미관찰",
            "- NAS: Reject 패턴 미관찰",
            "- S6a Diameter: 인증 관련 실패 미관찰",
            "",
            "## 절차 상태",
            "",
            "- 분석 구간 내 주요 Call 절차가 실패 없이 처리된 것으로 관찰됩니다.",
            "- 특정 장비 또는 인터페이스에 집중된 장애 패턴은 확인되지 않습니다.",
            "",
            "## 운영 의견",
            "",
            "- 현재 분석 구간의 서비스 상태는 안정적인 수준으로 판단됩니다.",
            "- 비정상 signaling 증가 또는 특정 인터페이스 집중 장애 징후는 관찰되지 않았습니다.",
            "",
            "## 권장 사항",
            "",
            "- 기존 KPI 모니터링을 유지하세요.",
            "- 장기 추세 기반 품질 분석은 별도 주기로 지속하는 것을 권장합니다.",
        ]
        return "\n".join(lines)

    lines = [
        "## xDR 통계 요약",
        "",
        f"- 파일: `{summary['file_info']['filename']}`",
        f"- 기간: {format_period(period.get('start_us'))} ~ {format_period(period.get('end_us'))}",
        f"- 총 레코드 / 시도 / 성공 / 실패 / 절단: {overall['total']:,} / {overall['attempt']:,} / {overall['success']:,} / {overall['fail']:,} / {overall['drop']:,}",
        f"- 실패율 / 절단율: {pct(overall['fail_rate'])} / {pct(overall['drop_rate'])}",
        "",
    ]

    lines.extend(
        [
            "## 실패 패턴 Top 5",
            "",
            "| 순위 | Interface | Message | Cause | 건수 | 비율 |",
            "|-----|-----------|---------|-------|------|------|",
        ]
    )
    if summary["top_failures"]:
        for rank, item in enumerate(summary["top_failures"][:5], start=1):
            interface, message, cause = split_failure_key(item["key"])
            ratio = item["count"] / overall["fail"] if overall["fail"] else 0.0
            lines.append(
                f"| {rank} | `{interface}` | {message} | {cause} | {item['count']:,} | {pct(ratio)} |"
            )
    else:
        lines.append("| - | - | - | - | 0 | 0.00% |")

    lines.extend(
        [
            "",
            "## 영향 장비",
            "",
            "| 유형 | ID | 실패 건수 |",
            "|------|----|----------|",
        ]
    )
    for label, entries in summary["affected_equipment"].items():
        equipment_type = label.upper()
        for item in entries[:3]:
            lines.append(f"| {equipment_type} | `{item['key']}` | {item['count']:,} |")
    if not any(summary["affected_equipment"].values()):
        lines.append("| - | - | 0 |")

    lines.extend(
        [
            "",
            "## RCA 후보",
            "",
            "| 순위 | 후보 원인 | 신뢰도 | 근거 |",
            "|------|---------|--------|------|",
        ]
    )
    if candidates:
        for candidate in candidates:
            evidence = "<br>".join(candidate.get("evidence", [])) or "-"
            lines.append(
                f"| {candidate['rank']} | `{candidate['suspected_cause']}` | {candidate['confidence']:.2f} | {evidence} |"
            )
    else:
        lines.append("| - | - | - | - |")

    lines.extend(["", "## 시간대 이상", ""])
    time_anomaly = summary["time_anomaly"]
    lines.append(f"- 탐지 여부: {'있음' if time_anomaly['detected'] else '없음'}")
    if time_anomaly["detected"]:
        windows = ", ".join(item["bucket"] for item in time_anomaly["windows"])
        lines.append(f"- 이상 구간: {windows}")
    else:
        lines.append("- 이상 구간: 없음")

    return "\n".join(lines)
