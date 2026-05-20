from __future__ import annotations

from collections import Counter
from typing import Any

from app.rca.analyzer import CALL_TYPE, ERROR_INTERFACE
from app.rca.cause_dictionary import resolve_cause
from app.rca.knowledge_loader import lookup_cause, lookup_error_cause, lookup_message


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


def _semantic_name(value: str) -> str:
    return value.upper().replace(" ", "_").replace("-", "_").replace("/", "_")


def _domain_from_interface(interface: str) -> str:
    if "Diameter" in interface:
        return "authentication"
    if "GTP" in interface:
        return "bearer_session"
    if "NAS-EMM" in interface or "NAS_EMM" in interface:
        return "mobility_management"
    if "NAS-ESM" in interface or "NAS_ESM" in interface:
        return "subscriber_service"
    if "S1AP" in interface:
        return "radio_access"
    return "unknown"


def _enrich_cause(interface: str, message: Any, cause_code: Any) -> dict[str, Any]:
    cause = resolve_cause(interface, message, cause_code)
    xdr_meta = lookup_error_cause(interface, cause_code)
    if xdr_meta:
        meaning = str(xdr_meta.get("meaning") or xdr_meta.get("name") or xdr_meta.get("message_type") or cause["semantic"])
        cause.update(
            {
                "semantic": _semantic_name(meaning),
                "description": str(xdr_meta.get("description") or meaning),
                "domain": _domain_from_interface(interface),
                "safe_label": meaning,
                "known": True,
                "dictionary_match": xdr_meta.get("dictionary_section"),
            }
        )
        if xdr_meta.get("group"):
            cause["group"] = xdr_meta["group"]
        return cause

    release_meta = lookup_cause(interface, cause_code)
    if release_meta:
        cause.update(
            {
                "semantic": str(release_meta.get("name") or cause["semantic"]),
                "description": str(release_meta.get("description") or cause["description"]),
                "domain": str(release_meta.get("domain") or cause["domain"]),
                "safe_label": str(release_meta.get("name") or cause["safe_label"]),
                "known": True,
                "dictionary_match": release_meta.get("id"),
            }
        )
    return cause


def _enrich_message(interface: str, message: Any) -> dict[str, Any]:
    meta = lookup_message(interface, message)
    if not meta:
        return {"code": str(message or "0"), "name": None, "dictionary_match": None}
    name = (
        meta.get("name")
        or meta.get("message")
        or meta.get("procedure")
        or meta.get("meaning")
    )
    return {
        "code": str(message or "0"),
        "name": name,
        "abbreviation": meta.get("abbreviation"),
        "dictionary_match": meta.get("dictionary_section"),
    }


def enrich_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not _is_failure(record):
            continue
        interface_code = str(record.get("first_error_interface_protocol") or "0")
        interface = ERROR_INTERFACE.get(interface_code, f"INTERFACE_{interface_code}")
        message = str(record.get("first_error_message") or "0")
        cause_code = str(record.get("first_error_cause") or "0")
        cause = _enrich_cause(interface, message, cause_code)
        events.append(
            {
                "record_index": index,
                "timestamp_us": _event_time(record),
                "call_type": CALL_TYPE.get(str(record.get("call_type")), f"CALL_TYPE_{record.get('call_type', '0')}"),
                "interface": interface,
                "interface_code": interface_code,
                "message": message,
                "message_info": _enrich_message(interface, message),
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
