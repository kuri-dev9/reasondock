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
    "S1MME_NAS-EMM": {"NAS-EMM"},
    "S1MME_NAS-ESM": {"NAS-ESM"},
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

