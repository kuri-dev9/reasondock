from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

PROTOCOL_ALIASES = {
    "S6a_Diameter": {"Diameter", "Diameter-S6a", "S6a", "NAS-EMM"},
    "S13_Diameter": {"Diameter", "Diameter-S13", "S13"},
    "S1MME_S1AP": {"S1AP"},
    "S11_GTPv2C": {"GTPv2-C", "GTPv2C"},
    "S10_GTPv2C": {"GTPv2-C", "GTPv2C"},
    "S3_GTPv1C": {"GTPv1-C", "GTPv1C"},
    "S1MME_NAS-EMM": {"NAS-EMM", "NAS_EMM"},
    "S1MME_NAS_EMM": {"NAS-EMM", "NAS_EMM"},
    "S1MME_NAS-ESM": {"NAS-ESM", "NAS_ESM"},
    "S1MME_NAS_ESM": {"NAS-ESM", "NAS_ESM"},
}

MESSAGE_PROTOCOL_KEYS = {
    "S6a_Diameter": ("Diameter",),
    "S13_Diameter": ("Diameter",),
    "S1MME_S1AP": ("S1AP",),
    "S11_GTPv2C": ("GTPv2C",),
    "S10_GTPv2C": ("GTPv2C",),
    "S3_GTPv1C": ("GTPv1C",),
    "S1MME_NAS-EMM": ("NAS_EMM",),
    "S1MME_NAS_EMM": ("NAS_EMM",),
    "S1MME_NAS-ESM": ("NAS_ESM",),
    "S1MME_NAS_ESM": ("NAS_ESM",),
}

CAUSE_PROTOCOL_KEYS = {
    "S6a_Diameter": ("Diameter_ExperimentalResultCode", "Diameter_ResultCode"),
    "S13_Diameter": ("Diameter_ExperimentalResultCode", "Diameter_ResultCode"),
    "S1MME_S1AP": ("S1AP",),
    "S11_GTPv2C": ("GTPv2C",),
    "S10_GTPv2C": ("GTPv2C",),
    "S3_GTPv1C": ("GTPv1C",),
    "S1MME_NAS-EMM": ("NAS_EMM",),
    "S1MME_NAS_EMM": ("NAS_EMM",),
    "S1MME_NAS-ESM": ("NAS_ESM",),
    "S1MME_NAS_ESM": ("NAS_ESM",),
}


@lru_cache(maxsize=1)
def load_cause_dictionary() -> dict[str, Any]:
    path = KNOWLEDGE_DIR / "cause_code_dictionary.release11.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_procedure_dictionary() -> dict[str, Any]:
    path = KNOWLEDGE_DIR / "procedure_dictionary.release11.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    path = KNOWLEDGE_DIR / "taxonomy.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_message_code_dictionary() -> dict[str, Any]:
    path = KNOWLEDGE_DIR / "message_code_dictionary.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_xdr_cause_dictionary() -> dict[str, Any]:
    path = KNOWLEDGE_DIR / "cause_dictionary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _protocol_matches(interface: str, protocol: str) -> bool:
    if interface == protocol:
        return True
    aliases = PROTOCOL_ALIASES.get(interface, set())
    return protocol in aliases


def lookup_cause(interface: str, cause_code: Any) -> dict[str, Any] | None:
    code = str(cause_code or "0")
    for item in load_cause_dictionary().get("causes", []):
        if str(item.get("code")) != code:
            continue
        if _protocol_matches(interface, str(item.get("protocol", ""))):
            return item
    return None


def _entry_code(entry: dict[str, Any]) -> Any:
    for key in ("value", "code", "decimal"):
        if key in entry:
            return entry.get(key)
    return None


def _lookup_entry(section: dict[str, Any] | None, code: Any) -> dict[str, Any] | None:
    if not section:
        return None
    normalized = str(code or "0")
    for entry in section.get("entries", []):
        if str(_entry_code(entry)) == normalized:
            return entry
    return None


def lookup_message(interface: str, message_code: Any) -> dict[str, Any] | None:
    for protocol_key in MESSAGE_PROTOCOL_KEYS.get(interface, ()):
        entry = _lookup_entry(load_message_code_dictionary().get(protocol_key), message_code)
        if entry:
            return {"dictionary_section": protocol_key, **entry}
    return None


def lookup_error_cause(interface: str, cause_code: Any) -> dict[str, Any] | None:
    for protocol_key in CAUSE_PROTOCOL_KEYS.get(interface, ()):
        entry = _lookup_entry(load_xdr_cause_dictionary().get(protocol_key), cause_code)
        if entry:
            return {"dictionary_section": protocol_key, **entry}

    process_entry = _lookup_entry(load_xdr_cause_dictionary().get("Process_Specific"), cause_code)
    if process_entry:
        return {"dictionary_section": "Process_Specific", **process_entry}
    return None


def lookup_taxonomy(taxonomy_id: str) -> tuple[str, dict[str, Any]] | None:
    for domain, entries in load_taxonomy().get("domains", {}).items():
        if taxonomy_id in entries:
            return domain, entries[taxonomy_id]
    return None


def lookup_procedure(call_type: str) -> dict[str, Any] | None:
    normalized = call_type.upper().replace("_MO", "").replace("_MT", "")
    aliases = {
        "ATTACH": "ATTACH",
        "TAU": "TAU",
        "SERVICE": "SERVICE_REQUEST",
        "EXTSERVICE": "SERVICE_REQUEST",
        "PAGING": "PAGING",
        "DETACH": "DETACH",
        "S1HO_INTERMME": "HANDOVER",
    }
    procedure_id = aliases.get(normalized)
    if not procedure_id:
        return None
    for item in load_procedure_dictionary().get("procedures", []):
        if item.get("id") == procedure_id:
            return item
    return None
