from __future__ import annotations

from collections import Counter
from typing import Any

from app.rca.analyzer import CALL_TYPE, ERROR_INTERFACE
from app.rca.cause_dictionary import resolve_cause


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _is_failure(record: dict[str, Any]) -> bool:
    attempt = _int(record.get("attempt_flag"))
    success = _int(record.get("success_flag"))
    is_detach_cleanup = (
        str(record.get("call_type")) == "9"
        and str(record.get("detach_flag")) == "1"
        and success == 1
    )
    return attempt == 1 and success == 0 and not is_detach_cleanup


def _event_time(record: dict[str, Any]) -> int:
    first_error_time = _int(record.get("first_error_time"), -1)
    if first_error_time >= 0:
        return first_error_time
    return _int(record.get("call_start_time"), -1)


def enrich_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not _is_failure(record):
            continue
        interface_code = str(record.get("first_error_interface_protocol") or "0")
        interface = ERROR_INTERFACE.get(interface_code, f"INTERFACE_{interface_code}")
        message = str(record.get("first_error_message") or "0")
        cause_code = str(record.get("first_error_cause") or "0")
        cause = resolve_cause(interface, message, cause_code)
        events.append(
            {
                "record_index": index,
                "timestamp_us": _event_time(record),
                "call_type": CALL_TYPE.get(str(record.get("call_type")), f"CALL_TYPE_{record.get('call_type', '0')}"),
                "interface": interface,
                "interface_code": interface_code,
                "message": message,
                "cause": cause,
                "equipment": {
                    "mme": str(record.get("MME_ID") or "(empty)"),
                    "enb": str(record.get("First_eNB_ID") or "(empty)"),
                    "sgw": str(record.get("SGW_ID") or "(empty)"),
                },
                "session": {
                    "imsi": str(record.get("IMSI") or ""),
                    "msisdn": str(record.get("MSISDN") or ""),
                    "apn": str(record.get("APN") or ""),
                },
            }
        )
    events.sort(key=lambda item: (item["timestamp_us"] if item["timestamp_us"] >= 0 else 10**30, item["record_index"]))
    return events


def summarize_semantics(events: list[dict[str, Any]]) -> dict[str, Any]:
    semantic_counts = Counter(event["cause"]["semantic"] for event in events)
    domain_counts = Counter(event["cause"]["domain"] for event in events)
    unknown_count = sum(1 for event in events if not event["cause"]["known"])
    return {
        "events": events[:50],
        "top_semantics": [{"semantic": key, "count": count} for key, count in semantic_counts.most_common(10)],
        "top_domains": [{"domain": key, "count": count} for key, count in domain_counts.most_common(10)],
        "unknown_cause_count": unknown_count,
    }
