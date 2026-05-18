from __future__ import annotations

from typing import Any


CAUSE_DICTIONARY: dict[str, dict[str, dict[str, str]]] = {
    "S6a_Diameter": {
        "15001": {
            "semantic": "DIAMETER_ERROR_USER_UNKNOWN",
            "description": "Diameter subscriber lookup/authentication related failure",
            "domain": "authentication",
            "safe_label": "Diameter subscriber lookup 관련 실패",
        },
        "5001": {
            "semantic": "AUTHENTICATION_DATA_UNAVAILABLE",
            "description": "Diameter authentication data availability related failure",
            "domain": "authentication",
            "safe_label": "Diameter 인증 데이터 조회 관련 실패",
        },
    },
    "S11_GTPv2C": {
        "64": {
            "semantic": "CONTEXT_NOT_FOUND",
            "description": "Bearer/session context not found or cleanup-related GTP-C failure",
            "domain": "bearer_session",
            "safe_label": "Bearer/session context 관련 실패",
        },
        "90": {
            "semantic": "BEARER_SESSION_ESTABLISHMENT_FAILURE",
            "description": "Bearer/session establishment related failure",
            "domain": "bearer_session",
            "safe_label": "Bearer/session establishment 관련 실패",
        },
    },
    "S1MME_NAS-EMM": {
        "8": {
            "semantic": "EPS_SERVICES_NOT_ALLOWED",
            "description": "EPS services not allowed",
            "domain": "mobility_management",
            "safe_label": "EPS service 허용 상태 관련 실패",
        },
        "15": {
            "semantic": "NO_SUITABLE_CELLS_IN_TRACKING_AREA",
            "description": "No suitable cells in tracking area or mobility restriction",
            "domain": "mobility_management",
            "safe_label": "TA/셀 선택 또는 mobility restriction 관련 실패",
        },
        "31": {
            "semantic": "REQUEST_REJECTED_UNSPECIFIED",
            "description": "Request rejected, unspecified",
            "domain": "mobility_management",
            "safe_label": "NAS request reject 관련 실패",
        },
    },
    "S1MME_S1AP": {
        "900": {
            "semantic": "S1AP_MESSAGE_TIMEOUT",
            "description": "S1AP procedure message timeout",
            "domain": "transport",
            "safe_label": "S1AP message timeout",
        },
    },
}


VENDOR_CAUSE_DICTIONARY: dict[str, dict[str, dict[str, str]]] = {}


def resolve_cause(interface: str, message: Any, cause_code: Any) -> dict[str, Any]:
    code = str(cause_code or "0")
    mapping = (
        VENDOR_CAUSE_DICTIONARY.get(interface, {}).get(code)
        or CAUSE_DICTIONARY.get(interface, {}).get(code)
    )
    if mapping:
        return {
            "cause_code": int(code) if code.isdigit() else code,
            "message": str(message or "0"),
            "semantic": mapping["semantic"],
            "description": mapping["description"],
            "domain": mapping["domain"],
            "safe_label": mapping.get("safe_label", mapping["description"]),
            "known": True,
        }

    return {
        "cause_code": int(code) if code.isdigit() else code,
        "message": str(message or "0"),
        "semantic": f"CAUSE_{code}",
        "description": "Unknown cause code; raw value preserved",
        "domain": "unknown",
        "safe_label": f"원시 cause code {code}",
        "known": False,
    }
