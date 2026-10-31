"""Payment method vocabulary shared by challan creation and admin-recorded payments."""
from typing import Optional

from fastapi import HTTPException

PAYMENT_METHODS = ("cash", "bank_transfer", "upi", "cheque", "other")
REFERENCE_REQUIRED_METHODS = ("bank_transfer", "upi", "cheque")
NOTES_REQUIRED_METHODS = ("cash", "other")


def normalize_payment_method(value: Optional[str]) -> Optional[str]:
    """Lower-case known methods ("Bank Transfer" -> "bank_transfer"); other legacy free text is only trimmed."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    key = cleaned.lower().replace("-", "_").replace(" ", "_")
    return key if key in PAYMENT_METHODS else cleaned


def validate_payment_method(value: Optional[str]) -> str:
    """Strict check used when an admin records a payment."""
    method = normalize_payment_method(value)
    if method not in PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"payment_method must be one of: {', '.join(PAYMENT_METHODS)}",
        )
    return method
