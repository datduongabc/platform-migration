from datetime import datetime, timedelta
import re

DEFAULT_DURATION_MINUTES = 60


def escape_ics_text(value: str) -> str:
    if not value:
        return ""
    # Escape backslash, comma, semicolon, and newlines
    value = value.replace("\\", "\\\\")
    value = value.replace(",", "\\,")
    value = value.replace(";", "\\;")
    value = re.sub(r"\r\n|\r|\n", r"\\n", value)
    return value


def fold_ics_line(line: str) -> str:
    fold_at = 75
    if len(line) <= fold_at:
        return line
    parts = []
    pos = 0
    first = True
    while pos < len(line):
        limit = fold_at if first else fold_at - 1
        parts.append(line[pos : pos + limit])
        pos += limit
        first = False
    return "\r\n ".join(parts)


def format_ics_date(dt: datetime) -> str:
    # Ensure dt is in UTC if possible, or just format as basic iCalendar datetime UTC format (ending in Z)
    # The database timestamps are offset-aware or naive. Let's convert to UTC.
    if dt.tzinfo is not None:
        dt = dt.astimezone(None).replace(
            tzinfo=None
        )  # Simplification or convert to UTC
    return dt.strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    uid: str,
    summary: str,
    dtstart: datetime,
    dtstamp: datetime,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    description: str = "",
) -> str:
    dtend = dtstart + timedelta(minutes=duration_minutes)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ricotdin//Meeting Assistant//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{format_ics_date(dtstamp)}",
        f"DTSTART:{format_ics_date(dtstart)}",
        f"DTEND:{format_ics_date(dtend)}",
        fold_ics_line(f"SUMMARY:{escape_ics_text(summary)}"),
        fold_ics_line(f"DESCRIPTION:{escape_ics_text(description)}"),
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    return "\r\n".join(lines) + "\r\n"
