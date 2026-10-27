"""Provisional generation-time token estimates, never measured usage."""

ESTIMATOR = {"name": "utf8-bytes-div4", "sha256": None}


def estimate_tokens(text: str) -> int:
    """Estimate UTF-8 text size using R03's provisional byte-count rule."""
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    try:
        return (len(text.encode("utf-8")) + 3) // 4
    except UnicodeEncodeError as error:
        raise ValueError("text must be UTF-8 encodable") from error


def sprint_floor(window: int) -> int:
    """Minimum estimated history tokens for a 1.25-window sprint."""
    return -(-window * 5 // 4)


def meets_sprint(tokens: int, window: int) -> bool:
    return tokens >= sprint_floor(window)
