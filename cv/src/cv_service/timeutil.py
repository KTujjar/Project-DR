from datetime import datetime, timezone


def iso_from_epoch(seconds: float) -> str:
    """UTC ISO 8601 with milliseconds and 'Z', identical to JS Date.toISOString()."""
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now() -> str:
    return iso_from_epoch(datetime.now(tz=timezone.utc).timestamp())


def parse_iso(value: str) -> float:
    """Epoch seconds from an ISO 8601 string ('Z' or offset)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
