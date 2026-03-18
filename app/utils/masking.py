"""Utilities for masking sensitive identity fields in API responses.

Masking must be applied only at response construction time; never to stored data.
All functions are defensive: they accept a string or None and never raise.
"""

from __future__ import annotations


def mask_generic(value: str | None, *, keep_start: int = 0, keep_end: int = 4, mask_char: str = "*") -> str | None:
    """Mask a value by keeping a prefix/suffix and masking the middle.

    - Never raises
    - Returns None when input is None (or not a string)
    - For very short strings, masks everything except possibly the last char
    """

    try:
        if value is None:
            return None
        if not isinstance(value, str):
            return None

        raw = value.strip()
        if raw == "":
            return value  # preserve empty/whitespace-only as-is

        n = len(raw)
        if n <= 1:
            return mask_char * n

        # Clamp keep sizes to sensible bounds
        ks = max(0, int(keep_start))
        ke = max(0, int(keep_end))

        # If we'd reveal the whole value, fall back to masking most of it.
        if ks + ke >= n:
            # Keep only the last character (if any) to avoid returning raw.
            return (mask_char * (n - 1)) + raw[-1]

        start = raw[:ks] if ks else ""
        end = raw[-ke:] if ke else ""
        middle_len = n - len(start) - len(end)
        if middle_len < 0:
            middle_len = 0
        return f"{start}{mask_char * middle_len}{end}"
    except Exception:
        # Absolute last resort: never leak raw, never raise.
        try:
            if value is None:
                return None
            if isinstance(value, str):
                raw = value.strip()
                return "*" * len(raw) if raw else value
        except Exception:
            return None
        return None


def mask_pan(value: str | None) -> str | None:
    """Mask PAN, typically 10 chars: keep first 5 and last 1 (ABCDE****F)."""

    try:
        return mask_generic(value, keep_start=5, keep_end=1)
    except Exception:
        return None if value is None else mask_generic(str(value), keep_start=5, keep_end=1)


def mask_aadhaar(value: str | None) -> str | None:
    """Mask UID/Aadhaar: keep only last 4 (********1234)."""

    try:
        return mask_generic(value, keep_start=0, keep_end=4)
    except Exception:
        return None if value is None else mask_generic(str(value), keep_start=0, keep_end=4)


def mask_passport(value: str | None) -> str | None:
    """Mask passport number: keep first 2 and last 2."""

    try:
        return mask_generic(value, keep_start=2, keep_end=2)
    except Exception:
        return None if value is None else mask_generic(str(value), keep_start=2, keep_end=2)


def mask_driving_license(value: str | None) -> str | None:
    """Mask driving license number: keep first 2 and last 4."""

    try:
        return mask_generic(value, keep_start=2, keep_end=4)
    except Exception:
        return None if value is None else mask_generic(str(value), keep_start=2, keep_end=4)

