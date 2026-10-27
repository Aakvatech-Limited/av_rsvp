from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def escape(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\r", "")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold(line):
    # RFC 5545 limits content lines to 75 octets, not 75 Unicode characters.
    chunks, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            chunks.append(current)
            current = " "
        current += char
    return "\r\n".join(chunks + [current])


def calendar_content(event, source_timezone=None):
    zone = ZoneInfo(source_timezone or event.timezone)

    def utc(value):
        dt = datetime.fromisoformat(str(value)).replace(tzinfo=zone)
        return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Aakvatech//AV RSVP//EN",
        "BEGIN:VEVENT",
        f"UID:{escape(event.name)}@av-rsvp",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{utc(event.starts_on)}",
        f"DTEND:{utc(event.ends_on)}",
        f"SUMMARY:{escape(event.event_title)}",
        f"LOCATION:{escape(event.venue)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
