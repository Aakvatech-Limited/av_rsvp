from datetime import datetime, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from av_rsvp.text import event_text


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
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=zone)
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
        f"DESCRIPTION:{escape(event_text(getattr(event, 'description', None) or ''))}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"

def calendar_links(event, source_timezone):
    zone = ZoneInfo(source_timezone)

    def utc(value):
        dt = datetime.fromisoformat(str(value))
        return (dt if dt.tzinfo else dt.replace(tzinfo=zone)).astimezone(timezone.utc)

    start, end = utc(event.starts_on), utc(event.ends_on)
    description = event_text(getattr(event, "description", None) or "")
    google = dict(
        action="TEMPLATE", text=event.event_title, dates=f"{start:%Y%m%dT%H%M%SZ}/{end:%Y%m%dT%H%M%SZ}",
        details=description, location=event.venue,
    )
    outlook = dict(
        path="/calendar/action/compose", rru="addevent", subject=event.event_title,
        startdt=start.isoformat(), enddt=end.isoformat(), body=description, location=event.venue,
    )
    return {
        "Google Calendar": "https://calendar.google.com/calendar/render?" + urlencode(google),
        "Microsoft 365": "https://outlook.office.com/calendar/deeplink/compose?" + urlencode(outlook),
        "Outlook.com": "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(outlook),
    }
