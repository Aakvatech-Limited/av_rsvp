"""Event-aware email content shared by invitation and response messages."""

from datetime import datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from av_rsvp.text import event_text


def email_content(
    invitation, event, purpose, url, source_timezone, confirmed=0, waitlisted=0, banner_url=None
):
    def text(value):
        return escape(str(value or ""))

    def paragraphs(value):
        return "".join(
            paragraph("<br>".join(text(block).splitlines()))
            for block in event_text(value).split("\n\n")
            if block.strip()
        )

    def paragraph(content):
        return f'<p style="margin:0 0 18px;line-height:1.7">{content}</p>'

    def local(value):
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(source_timezone))
        return dt.astimezone(ZoneInfo(event.timezone))

    start, end = local(event.starts_on), local(event.ends_on)
    date = start.strftime("%A, %d %B %Y")
    if start.date() != end.date():
        date += " – " + end.strftime("%A, %d %B %Y")
    timezone_label = start.tzname() or event.timezone
    time = f"{start:%H:%M} – {end:%H:%M} {timezone_label}"
    title = text(event.event_title)
    description = event_text(event.get("description") or "").strip()
    footer = event_text(event.get("footer_text") or "").strip()
    body = paragraph(f"Dear {text(invitation.guest_name)},")
    if purpose == "Confirmation":
        custom_subject = " ".join((event.get("confirmation_email_subject") or "").splitlines()).strip()
        subject = custom_subject or f"Your RSVP Confirmation | {event.event_title}"
        body += paragraph(f"Thank you for responding to <strong>{title}</strong>.")
        body += paragraph(
            f"Your response: <strong>{text(invitation.response_status)}</strong>.<br>"
            f"Confirmed places across functions: {confirmed}.<br>"
            f"Waitlisted places: {waitlisted}."
        )
        action = "View Attendance Details"
    elif purpose == "Reminder":
        subject = f"RSVP Reminder | {event.event_title}"
        body += paragraph(f"A kind reminder to confirm your attendance for <strong>{title}</strong>.")
        action = "View Invitation &amp; RSVP"
    else:
        subject = f"Your Invitation | {event.event_title}"
        if not description:
            body += paragraph(f"You are cordially invited to <strong>{title}</strong>.")
        action = "View Invitation &amp; RSVP"
    if purpose != "Confirmation" and description:
        body += paragraphs(event.description)
    body += (
        '<table role="presentation" width="100%" cellpadding="6" cellspacing="0" '
        'style="width:100%;margin:22px 0;background-color:#f3f5f7;font-size:14px;line-height:1.6">'
        f"<tr><td><strong>Date</strong></td><td>{text(date)}</td></tr>"
        f"<tr><td><strong>Time</strong></td><td>{text(time)}</td></tr>"
        f"<tr><td><strong>Venue</strong></td><td>{text(event.venue)}</td></tr></table>"
    )
    if purpose != "Confirmation":
        deadline_dt = local(event.rsvp_deadline)
        deadline = deadline_dt.strftime("%A, %d %B %Y at %H:%M")
        body += paragraph(
            f"Kindly confirm your attendance by <strong>{text(deadline)} "
            f"{text(deadline_dt.tzname() or event.timezone)}</strong>."
        )
    link = escape(url, quote=True)
    body += (
        '<p style="margin:28px 0">'
        f'<a href="{link}" style="background-color:#183b56;color:#ffffff;'
        "padding:14px 24px;border-radius:6px;text-decoration:none;"
        f'display:inline-block;font-weight:bold">{action}</a></p>'
        f'<p style="margin:0 0 24px;font-size:12px;line-height:1.6;color:#5c6878">'
        f'If the button does not work, <a href="{link}" style="color:#214b75">open your invitation here</a>.</p>'
    )
    if footer:
        body += paragraphs(event.footer_text)
    elif event.get("host_name"):
        body += paragraph(f"With kind regards,<br><strong>{text(event.host_name)}</strong>")
    contacts = [text(event.get(field)) for field in ("contact_email", "contact_phone") if event.get(field)]
    if contacts:
        body += f'<p style="margin:24px 0 18px;font-size:12px;line-height:1.6">For enquiries: {" · ".join(contacts)}</p>'
    assistance = (
        "For assistance, contact the organiser using the details above."
        if contacts
        else "For assistance, contact the event organiser."
    )
    body += (
        '<p style="margin:18px 0 0;font-size:12px;line-height:1.6;color:#666666">'
        f"This is an automated email. Please do not reply to this message. {assistance}</p>"
    )
    body += '<p style="margin:18px 0 0;font-size:12px;line-height:1.6;color:#666666">This invitation link is personal to you. Please keep it private.</p>'
    emblem = ""
    if banner_url and urlsplit(banner_url).scheme in {"https", "http"} and urlsplit(banner_url).netloc:
        emblem = (
            '<tr><td align="center" style="padding:28px 24px 8px">'
            f'<img src="{escape(banner_url, quote=True)}" width="96" '
            'alt="Event emblem" style="display:block;width:96px;max-width:100%;height:auto;border:0">'
            "</td></tr>"
        )
    body = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;background-color:#f4f1ea"><tr><td align="center" style="padding:24px 8px">'
        '<!--[if mso]><table role="presentation" width="600" align="center"><tr><td><![endif]-->'
        '<table role="presentation" align="center" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:600px;margin:0 auto;background-color:#fffdf8;'
        'border-top:4px solid #a57c32;color:#1c2b40;font-family:Arial,sans-serif;font-size:14px">'
        f'{emblem}<tr><td align="center" style="padding:24px 24px 12px;'
        'font-family:Georgia,serif;font-size:25px;line-height:1.3;color:#1c2b40">'
        f'{title}</td></tr><tr><td style="padding:20px 24px 30px;overflow-wrap:anywhere">'
        f"{body}</td></tr></table><!--[if mso]></td></tr></table><![endif]-->"
        "</td></tr></table>"
    )
    body = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{text(subject)}</title></head>"
        f'<body style="margin:0;padding:0;background-color:#f4f1ea">{body}</body></html>'
    )
    return subject, body
