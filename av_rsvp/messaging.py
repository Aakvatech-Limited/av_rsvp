from html import escape

import frappe
from frappe.utils import add_days, get_datetime, now_datetime

from av_rsvp.domain import event_now
from av_rsvp.security import current_doc, digest, invitation_url, lock_event, service_write


def queue_message(invitation, purpose, dedup_key):
    key = digest(dedup_key)
    if frappe.db.exists("RSVP Message Log", {"dedup_key": key}):
        return False
    with service_write():
        doc = frappe.get_doc(
            dict(
                doctype="RSVP Message Log",
                event=invitation.event,
                invitation=invitation.name,
                purpose=purpose,
                recipient=invitation.email,
                dedup_key=key,
            )
        ).insert(ignore_permissions=True)
    frappe.enqueue("av_rsvp.messaging.deliver_message", log_name=doc.name, enqueue_after_commit=True)
    return True


def deliver_message(log_name):
    log = frappe.get_doc("RSVP Message Log", log_name)
    lock_event(log.event)
    log = current_doc("RSVP Message Log", log_name)
    if log.get("email_queue") or log.status == "Sent":
        return
    invitation = current_doc("RSVP Invitation", log.invitation)
    event = current_doc("RSVP Event", log.event)
    if invitation.revoked or event.status in {"Draft", "Cancelled", "Completed"}:
        with service_write():
            log.status, log.error = "Failed", "Invitation or event is no longer active."
            log.save(ignore_permissions=True)
        return
    try:
        sender_account = frappe.db.get_single_value("RSVP Settings", "default_sender")
        sender = frappe.db.get_value("Email Account", sender_account, "email_id") if sender_account else None
        body = f"<p>Hello {escape(invitation.guest_name)},</p><p>{escape(event.event_title)}</p>"
        if log.purpose == "Confirmation":
            answers = frappe.get_all(
                "RSVP Function Response",
                filters={"invitation": invitation.name},
                fields=["allocation"],
                order_by="creation",
            )
            body += f"<p>Your response: {escape(invitation.response_status)}. Confirmed places across functions: {sum(r.allocation == 'Confirmed' for r in answers)}. Waitlisted places: {sum(r.allocation == 'Waitlisted' for r in answers)}.</p>"
        body += f'<p><a href="{escape(invitation_url(invitation), quote=True)}">View invitation and attendance details</a></p>'
        queue = frappe.sendmail(
            recipients=[invitation.email],
            sender=sender or "",
            subject=f"{log.purpose}: {event.event_title}",
            message=body,
            reference_doctype="RSVP Message Log",
            reference_name=log.name,
            add_unsubscribe_link=0,
        )
        with service_write():
            log.email_queue = queue.name if queue else None
            log.error = ""
            log.save(ignore_permissions=True)
            if log.purpose == "Reminder":
                frappe.db.set_value("RSVP Invitation", invitation.name, "last_reminded_on", now_datetime())
            if log.purpose == "Invitation":
                frappe.db.set_value("RSVP Invitation", invitation.name, "delivery_status", "Queued")
    except Exception:
        # No bodies, tokens or SMTP credentials are copied into the user-facing log.
        with service_write():
            log.status, log.error = (
                "Failed",
                "Email could not be queued. Check the outgoing Email Account and Frappe Error Log.",
            )
            log.save(ignore_permissions=True)
            if log.purpose == "Invitation":
                frappe.db.set_value("RSVP Invitation", invitation.name, "delivery_status", "Failed")
        frappe.log_error(title="AV RSVP email queue failure")


def sync_delivery_status():
    for row in frappe.get_all(
        "RSVP Message Log",
        filters={"status": "Queued", "email_queue": ["is", "set"]},
        fields=["name", "invitation", "purpose", "email_queue"],
    ):
        status = frappe.db.get_value("Email Queue", row.email_queue, "status")
        mapped = "Sent" if status == "Sent" else "Failed" if status in {"Error", "Not Sent"} else None
        if not mapped or status == "Not Sent":
            continue
        with service_write():
            log = frappe.get_doc("RSVP Message Log", row.name)
            log.status = mapped
            if mapped == "Sent":
                log.sent_on = now_datetime()
            log.save(ignore_permissions=True)
        if row.purpose == "Invitation":
            frappe.db.set_value("RSVP Invitation", row.invitation, "delivery_status", mapped)


def send_due_reminders():
    if not frappe.db.get_single_value("RSVP Settings", "enable_reminders"):
        return
    interval = int(frappe.db.get_single_value("RSVP Settings", "reminder_days") or 3)
    for event_name in frappe.get_all("RSVP Event", filters={"status": "Published"}, pluck="name"):
        lock_event(event_name)
        event = frappe.get_doc("RSVP Event", event_name)
        if event_now(event.timezone) > get_datetime(event.rsvp_deadline):
            continue
        for name in frappe.get_all(
            "RSVP Invitation",
            filters={
                "event": event.name,
                "response_status": "Pending",
                "revoked": 0,
                "delivery_status": "Sent",
            },
            pluck="name",
        ):
            invitation = frappe.get_doc("RSVP Invitation", name)
            baseline = invitation.last_reminded_on or invitation.creation
            if get_datetime(add_days(baseline, interval)) > now_datetime():
                continue
            if invitation.email:
                queue_message(invitation, "Reminder", f"Reminder:{name}:{event_now(event.timezone).date()}")
