from __future__ import annotations

from typing import Any


CAUSE_DICTIONARY: dict[str, dict[str, dict[str, str]]] = {
    "S6a_Diameter": {
        "15001": {
            "semantic": "DIAMETER_ERROR_USER_UNKNOWN",
            "description": "Subscriber unknown in HSS",
            "domain": "authentication",
        },
        "5001": {
            "semantic": "AUTHENTICATION_DATA_UNAVAILABLE",
            "description": "Authentication data unavailable from HSS/AuC",
            "domain": "authentication",
        },
    },
    "S11_GTPv2C": {
        "64": {
            "semantic": "CONTEXT_NOT_FOUND",
            "description": "Bearer/session context not found or cleanup-related GTP-C failure",
            "domain": "bearer_session",
        },
        "90": {
            "semantic": "BEARER_SESSION_ESTABLISHMENT_FAILURE",
            "description": "Bearer/session establishment related failure",
            "domain": "bearer_session",
        },
    },
    "S1MME_NAS-EMM": {
        "8": {
            "semantic": "EPS_SERVICES_NOT_ALLOWED",
            "description": "EPS services not allowed",
            "domain": "mobility_management",
        },
        "15": {
            "semantic": "NO_SUITABLE_CELLS_IN_TRACKING_AREA",
            "description": "No suitable cells in tracking area or mobility restriction",
            "domain": "mobility_management",
        },
        "31": {
            "semantic": "REQUEST_REJECTED_UNSPECIFIED",
            "description": "Request rejected, unspecified",
            "domain": "mobility_management",
        },
    },
    "S1MME_S1AP": {
        "900": {
            "semantic": "S1AP_MESSAGE_TIMEOUT",
            "description": "S1AP procedure message timeout",
            "domain": "transport",
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
            "known": True,
        }

    return {
        "cause_code": int(code) if code.isdigit() else code,
        "message": str(message or "0"),
        "semantic": f"CAUSE_{code}",
        "description": "Unknown cause code; raw value preserved",
        "domain": "unknown",
        "known": False,
    }
