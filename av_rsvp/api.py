import csv
import io
from copy import deepcopy
from urllib.parse import quote

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime

from av_rsvp.permissions import access_level, require_event
from av_rsvp.security import (
    check_token,
    current_doc,
    current_rows,
    current_value,
    digest,
    invitation_url,
    lock_event,
    new_nonce,
    retry_transaction,
    service_write,
    token_for,
)
from av_rsvp.services import apply_response, check_in, functions_for, promote_waitlist, snapshot


def private_response():
    if frappe.local.response is not None:
        frappe.local.response_headers.update(
            {"Cache-Control": "no-store, private", "Referrer-Policy": "no-referrer"}
        )


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=60, seconds=60)
@retry_transaction
def get_invitation(token):
    private_response()
    invitation, event = check_token(token)
    return snapshot(invitation, event)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60)
@retry_transaction
def respond(token, response, people, notes=""):
    private_response()
    invitation, _event = check_token(token)
    return apply_response(
        invitation.name,
        response,
        deepcopy(frappe.parse_json(people)),
        notes,
        actor="Guest via private invitation",
        expected_token_hash=digest(token),
    )


@frappe.whitelist(methods=["POST"])
@retry_transaction
def staff_invitation(invitation):
    private_response()
    doc = frappe.get_doc("RSVP Invitation", invitation)
    require_event(doc.event)
    return snapshot(doc, frappe.get_doc("RSVP Event", doc.event))


@frappe.whitelist(methods=["POST"])
@retry_transaction
def record_response(invitation, response, people, notes=""):
    doc = frappe.get_doc("RSVP Invitation", invitation)
    require_event(doc.event)
    return apply_response(doc.name, response, deepcopy(frappe.parse_json(people)), notes)


@frappe.whitelist(methods=["POST"])
@retry_transaction
def share_invitation(invitation):
    private_response()
    doc = frappe.get_doc("RSVP Invitation", invitation)
    require_event(doc.event)
    if doc.revoked:
        frappe.throw("This invitation has been revoked.")
    return share_details(doc)


def share_details(doc):
    lock_event(doc.event)
    doc = current_doc("RSVP Invitation", doc.name)
    if doc.revoked:
        frappe.throw("This invitation has been revoked.")
    event = current_doc("RSVP Event", doc.event)
    if event.status != "Published":
        frappe.throw("Publish the event before sharing invitations.")
    url = invitation_url(doc)
    message = f"Hello {doc.guest_name}, you are invited to {event.event_title}. Please RSVP: {url}"
    return dict(url=url, whatsapp_url="https://wa.me/?text=" + quote(message))


@frappe.whitelist(methods=["POST"])
@retry_transaction
def revoke_invitation(invitation):
    doc = frappe.get_doc("RSVP Invitation", invitation)
    require_event(doc.event, 3)
    lock_event(doc.event)
    if current_value(
        "RSVP Check-in",
        {
            "attendee": [
                "in",
                current_rows("RSVP Attendee", filters={"invitation": doc.name}, pluck="name") or [""],
            ],
            "status": "Checked In",
        },
    ):
        frappe.throw("Reverse attendee check-ins before revoking this invitation.")
    with service_write():
        doc = current_doc("RSVP Invitation", invitation)
        doc.registration_key = None
        doc.revoked = 1
        doc.save(ignore_permissions=True)
        for name in current_rows("RSVP Function Response", filters={"invitation": doc.name}, pluck="name"):
            row = current_doc("RSVP Function Response", name)
            row.attendance, row.allocation = "Declined", "Cancelled"
            row.save(ignore_permissions=True)
        promote_waitlist(current_doc("RSVP Event", doc.event))
    return {"revoked": True}


@frappe.whitelist(methods=["POST"])
@retry_transaction
def renew_invitation(invitation):
    doc = frappe.get_doc("RSVP Invitation", invitation)
    require_event(doc.event, 3)
    lock_event(doc.event)
    with service_write():
        doc = current_doc("RSVP Invitation", invitation)
        doc.registration_key = None
        doc.access_nonce = new_nonce()
        doc.token_hash = digest(token_for(doc.access_nonce, "invitation"))
        doc.revoked = 0
        doc.save(ignore_permissions=True)
    return share_details(doc)


@frappe.whitelist(methods=["POST"])
@retry_transaction
def send_invitations(event, pending_only=0):
    from av_rsvp.messaging import queue_message

    require_event(event, 2)
    lock_event(event)
    if current_value("RSVP Event", event, "status") != "Published":
        frappe.throw("Publish the event before sending invitations.")
    filters = {"event": event, "revoked": 0}
    if int(pending_only):
        filters["response_status"] = "Pending"
    count, skipped = 0, 0
    for name in current_rows("RSVP Invitation", filters=filters, pluck="name"):
        doc = current_doc("RSVP Invitation", name)
        if not doc.email:
            skipped += 1
            continue
        purpose = "Reminder" if int(pending_only) else "Invitation"
        # Explicit daily resend: double-clicks do not create duplicate deliveries.
        key = f"{purpose}:{doc.name}:{now_datetime().date()}"
        count += int(queue_message(doc, purpose, key))
    return dict(queued=count, skipped_without_email=skipped)


@frappe.whitelist(methods=["POST"])
@retry_transaction
def promote(event):
    require_event(event, 2)
    lock_event(event)
    with service_write():
        return {"promoted": promote_waitlist(current_doc("RSVP Event", event))}


@frappe.whitelist(methods=["POST"])
@retry_transaction
def register_checkin(function, attendee=None, entry_token=None):
    return check_in(function, attendee, entry_token)


@frappe.whitelist(methods=["POST"])
@retry_transaction
def reverse_checkin(checkin, reason):
    from av_rsvp.domain import clean_text

    doc = frappe.get_doc("RSVP Check-in", checkin)
    require_event(doc.event, 2)
    lock_event(doc.event)
    reason = clean_text(reason, 1000)
    if not reason:
        frappe.throw("A reversal reason is required.")
    with service_write():
        doc = current_doc("RSVP Check-in", checkin)
        if doc.status == "Checked In":
            doc.status = "Reversed"
            doc.reversed_on = now_datetime()
            doc.reversed_by = frappe.session.user
            doc.reversal_reason = reason
            doc.save(ignore_permissions=True)
    return {"status": doc.status}


@frappe.whitelist(methods=["POST"])
@retry_transaction
def event_overview(event, search="", response_status="", page=0):
    require_event(event, 2)
    event_doc = frappe.get_doc("RSVP Event", event)
    filters = {"event": event, "revoked": 0}
    stats = {"invitations": frappe.db.count("RSVP Invitation", filters)}
    for status in ["Pending", "Attending", "Declined", "Maybe"]:
        stats[status.lower()] = frappe.db.count("RSVP Invitation", {**filters, "response_status": status})
    stats["invited_people"] = sum(frappe.get_all("RSVP Invitation", filters=filters, pluck="max_attendees"))
    stats["confirmed_places"] = frappe.db.count(
        "RSVP Function Response", {"event": event, "allocation": "Confirmed"}
    )
    stats["confirmed_people"] = len(
        set(
            frappe.get_all(
                "RSVP Function Response",
                filters={"event": event, "allocation": "Confirmed"},
                pluck="attendee",
            )
        )
    )
    stats["waitlisted_places"] = frappe.db.count(
        "RSVP Function Response", {"event": event, "allocation": "Waitlisted"}
    )
    stats["checked_in_people"] = len(
        set(
            frappe.get_all(
                "RSVP Check-in", filters={"event": event, "status": "Checked In"}, pluck="attendee"
            )
        )
    )
    if response_status:
        if response_status not in {"Pending", "Attending", "Declined", "Maybe"}:
            frappe.throw("Invalid response status.")
        filters["response_status"] = response_status
    if search:
        filters["guest_name"] = ["like", "%" + str(search)[:140] + "%"]
    rows = frappe.get_all(
        "RSVP Invitation",
        filters=filters,
        fields=[
            "name",
            "guest_name",
            "email",
            "phone",
            "max_attendees",
            "response_status",
            "delivery_status",
        ],
        order_by="creation desc",
        limit_start=max(0, int(page)) * 50,
        limit_page_length=50,
    )
    functions = functions_for(event)
    for function in functions:
        function["confirmed"] = frappe.db.count(
            "RSVP Function Response", {"function": function.name, "allocation": "Confirmed"}
        )
        function["waitlisted"] = frappe.db.count(
            "RSVP Function Response", {"function": function.name, "allocation": "Waitlisted"}
        )
        function["checked_in"] = frappe.db.count(
            "RSVP Check-in", {"function": function.name, "status": "Checked In"}
        )
    return dict(
        event_title=event_doc.event_title,
        stats=stats,
        invitations=rows,
        functions=functions,
        access_level=access_level(event),
        has_more=len(rows) == 50,
    )


@frappe.whitelist(methods=["POST"])
@retry_transaction
def find_attendees(function, search=""):
    function_doc = frappe.get_doc("RSVP Function", function)
    require_event(function_doc.event, 1)
    confirmed = frappe.get_all(
        "RSVP Function Response", filters={"function": function, "allocation": "Confirmed"}, pluck="attendee"
    )
    if not confirmed:
        return []
    return frappe.get_all(
        "RSVP Attendee",
        filters={
            "event": function_doc.event,
            "name": ["in", confirmed],
            "active": 1,
            "attendee_name": ["like", "%" + str(search)[:140] + "%"],
        },
        fields=["name", "attendee_name", "age_group"],
        order_by="attendee_name",
        limit_page_length=30,
    )


@frappe.whitelist(methods=["POST"])
@retry_transaction
def export_guests(event):
    require_event(event, 2)
    rows = frappe.get_all(
        "RSVP Invitation",
        filters={"event": event},
        fields=[
            "name",
            "guest_name",
            "email",
            "phone",
            "max_attendees",
            "response_status",
            "delivery_status",
            "revoked",
        ],
        order_by="guest_name",
    )
    output = io.StringIO()
    writer = csv.writer(output)
    columns = [
        "name",
        "guest_name",
        "email",
        "phone",
        "max_attendees",
        "response_status",
        "delivery_status",
        "revoked",
    ]
    writer.writerow(columns)
    for row in rows:
        # Protect spreadsheet applications from treating guest-entered text as formulas.
        writer.writerow(
            [
                ("'" + str(row.get(c)))
                if str(row.get(c) or "").lstrip().startswith(("=", "+", "-", "@"))
                else row.get(c)
                for c in columns
            ]
        )
    return {"filename": "rsvp_guests.csv", "content": output.getvalue()}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=60)
@retry_transaction
def calendar(token):
    from av_rsvp.calendar import calendar_content

    private_response()
    _invitation, event = check_token(token)
    from frappe.utils import get_system_timezone

    return {
        "filename": "event.ics",
        "content": calendar_content(event, source_timezone=get_system_timezone()),
    }


def public_registration_event(event):
    """Explicit opt-in; do not disclose draft or invitation-only events."""
    from frappe.utils import get_datetime

    lock_event(event)
    doc = current_doc("RSVP Event", event)
    if (
        not doc.allow_public_registration
        or doc.status != "Published"
        or now_datetime() > get_datetime(doc.rsvp_deadline)
    ):
        frappe.throw(
            "Public registration is unavailable or closed. Contact the organiser.", frappe.PermissionError
        )
    return doc


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=60, seconds=60)
@retry_transaction
def get_registration(event):
    from av_rsvp.security import display_datetime
    from av_rsvp.services import public_event_details

    private_response()
    doc = public_registration_event(event)
    functions = functions_for(doc.name)
    if not functions:
        frappe.throw("No functions are available. Contact the organiser.")
    for function in functions:
        for key in ["starts_on", "ends_on"]:
            function[key] = display_datetime(function[key], doc.timezone)
    return dict(
        event=public_event_details(doc),
        invitation=dict(guest_name="", max_attendees=doc.public_max_attendees, response_status="Pending"),
        functions=functions,
        attendees=[],
        editable=True,
    )


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=60)
@retry_transaction
def register(
    event, guest_name, email, registration_key, response, people, phone="", organisation="", notes=""
):
    """Create guest + booking + response atomically, with a client-generated retry secret.

    Contact details are unverified: never use them to return or alter an existing
    guest/invitation. Only the random retry secret can recover this submission.
    """
    import re

    from frappe.utils import validate_email_address

    from av_rsvp.domain import clean_text

    private_response()
    doc = public_registration_event(event)
    if not isinstance(registration_key, str) or not re.fullmatch(r"[a-f0-9]{64}", registration_key):
        frappe.throw("Invalid registration request. Reload the page and try again.")
    key = digest(f"{doc.name}:{registration_key}")
    existing = current_value("RSVP Invitation", {"event": doc.name, "registration_key": key})
    if existing:
        invitation = current_doc("RSVP Invitation", existing)
        token = token_for(invitation.access_nonce, "invitation")
        invitation, event_doc = check_token(token)
        return dict(token=token, registration=snapshot(invitation, event_doc))
    try:
        guest_name = clean_text(guest_name)
        email = clean_text(email).lower()
        phone = clean_text(phone)
        organisation = clean_text(organisation)
    except ValueError as error:
        frappe.throw(str(error))
    if not guest_name or not email or validate_email_address(email) != email:
        frappe.throw("Enter your full name and a valid email address.")
    # A real HTTP POST rolls the entire request back on validation/capacity errors.
    with service_write():
        guest = frappe.get_doc(
            dict(
                doctype="RSVP Guest",
                guest_name=guest_name,
                email=email,
                phone=phone,
                organisation=organisation,
            )
        ).insert(ignore_permissions=True)
        invitation = frappe.get_doc(
            dict(
                doctype="RSVP Invitation",
                event=doc.name,
                guest=guest.name,
                guest_name=guest_name,
                email=email,
                phone=phone,
                max_attendees=doc.public_max_attendees,
                registration_key=key,
            )
        ).insert(ignore_permissions=True)
        result = apply_response(
            invitation.name,
            response,
            deepcopy(frappe.parse_json(people)),
            notes,
            actor="Guest via public registration",
        )
    return dict(token=token_for(invitation.access_nonce, "invitation"), registration=result)
