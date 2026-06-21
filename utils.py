from __future__ import annotations
import re
from datetime import timedelta
from typing import Optional


_UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}

_PATTERN = re.compile(r"(\d+)\s*([a-zA-Z]+)")


def parse_duration(text: str) -> Optional[int]:
    """Parse a human duration string like '30m', '2h', '1d' into seconds. Returns None on failure."""
    text = text.strip().lower()
    matches = _PATTERN.findall(text)
    if not matches:
        return None
    total = 0
    for amount, unit in matches:
        multiplier = _UNITS.get(unit)
        if multiplier is None:
            return None
        total += int(amount) * multiplier
    return total if total > 0 else None


def format_duration(seconds: int) -> str:
    """Format a seconds count into a compact human string like '2h 30m'."""
    parts = []
    for label, size in [("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]:
        if seconds >= size:
            parts.append(f"{seconds // size}{label}")
            seconds %= size
    return " ".join(parts) or "0s"


def reminder_embed_fields(reminder) -> dict:
    """Return kwargs for a discord.Embed describing a reminder."""
    from datetime import timezone
    next_fire = reminder.next_fire_at
    if next_fire.tzinfo is None:
        next_fire = next_fire.replace(tzinfo=timezone.utc)
    ts = int(next_fire.timestamp())
    return {
        "fields": [
            ("ID", str(reminder.id), True),
            ("Interval", format_duration(reminder.interval_seconds), True),
            ("Fired", str(reminder.fire_count), True),
            ("Next fire", f"<t:{ts}:R>", True),
        ]
    }
