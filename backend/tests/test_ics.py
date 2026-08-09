from datetime import datetime, timezone
from app.services.ics import (
    escape_ics_text,
    fold_ics_line,
    format_ics_date,
    build_ics,
)

FIXED_DTSTAMP = datetime(2026, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
FIXED_DTSTART = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)


def test_escape_ics_text_commas():
    assert escape_ics_text("a,b") == "a\\,b"


def test_escape_ics_text_semicolons():
    assert escape_ics_text("a;b") == "a\\;b"


def test_escape_ics_text_backslashes():
    assert escape_ics_text("a\\b") == "a\\\\b"


def test_escape_ics_text_newlines():
    assert escape_ics_text("a\nb") == "a\\nb"
    assert escape_ics_text("a\r\nb") == "a\\nb"


def test_fold_ics_line_short():
    line = "SUMMARY:Hello"
    assert fold_ics_line(line) == line


def test_fold_ics_line_long():
    line = "DESCRIPTION:" + "A" * 80
    folded = fold_ics_line(line)
    parts = folded.split("\r\n")
    assert len(parts) == 2
    assert len(parts[0]) == 75
    assert parts[1].startswith(" ")


def test_format_ics_date():
    dt = datetime(2026, 6, 15, 10, 30, 45)
    assert format_ics_date(dt) == "20260615T103045Z"


def test_build_ics_structure():
    result = build_ics(
        uid="test-uid@ricotdin",
        summary="Team Sync",
        dtstart=FIXED_DTSTART,
        dtstamp=FIXED_DTSTAMP,
        description="Discuss Q3 goals",
    )
    assert "BEGIN:VCALENDAR" in result
    assert "BEGIN:VEVENT" in result
    assert "UID:test-uid@ricotdin" in result
    assert "SUMMARY:Team Sync" in result
    assert "DESCRIPTION:Discuss Q3 goals" in result
    assert "END:VEVENT" in result
    assert "END:VCALENDAR" in result
    assert result.endswith("\r\n")
