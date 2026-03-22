"""
Shared helpers for Payhero / Safaricom STK callback payloads and result codes.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple


def normalize_stk_result_code(result_code: Any) -> str:
    """Coerce ResultCode from JSON (int, float, str) to a stable string, e.g. 1 -> '1'."""
    if result_code is None:
        return ""
    s = str(result_code).strip()
    if not s:
        return ""
    try:
        # Handles 1, "1", 1.0, "1.0"
        return str(int(float(s)))
    except (TypeError, ValueError):
        return s


def infer_insufficient_funds(result_code_str: str, result_desc: Optional[str]) -> bool:
    """True if Safaricom/Payhero indicates insufficient M-Pesa balance."""
    if result_code_str == "1":
        return True
    d = (result_desc or "").lower()
    if not d:
        return False
    needles = (
        "insufficient",
        "balance is insufficient",
        "low balance",
        "not enough money",
        "less than minimum",
        "below minimum",
    )
    return any(n in d for n in needles)
