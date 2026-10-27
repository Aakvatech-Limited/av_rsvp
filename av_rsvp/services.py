"""All state transitions share the event row lock and the caller's transaction."""

import frappe
from frappe.utils import cint, get_datetime, now_datetime

from av_rsvp.domain import allocation_for, clean_text, event_now, validate_people
from av_rsvp.security import (
    current_count,
    current_doc,
    current_rows,
    current_value,
    digest,
    lock_event,
    service_write,
    token_for,
)


def save_doc(doc):
    return doc.insert(ignore_permissions=True) if doc.is_new() else doc.save(ignore_permissions=True)


def functions_for(event):
    return current_rows(
        "RSVP Function",
        filters={"event": event, "enabled": 1},
        fields=["name", "function_title", "starts_on", "ends_on", "venue", "capacity", "meal_options"],
        order_by="starts_on, name",
    )


def snapshot(invitation, event):
    lock_event(event.name)
    invitation = current_doc("RSVP Invitation", invitation.name)
    event = current_doc("RSVP Event", event.name)
    if invitation.revoked or event.status in {"Draft", "Cancelled"}:
        frappe.throw("This invitation is unavailable.", frappe.PermissionError)
    functions = functions_for(event.name)
    people = current_rows(
        "RSVP Attendee",
        filters={"invitation": invitation.name, "active": 1},
        fields=[
            "name",
            "attendee_name",
            "age_group",
            "dietary_requirements",
            "accessibility_requests",
            "entry_nonce",
        ],
        order_by="creation, name",
    )
    responses = current_rows(
        "RSVP Function Response",
        filters={"invitation": invitation.name},
        fields=["attendee", "function", "attendance", "allocation", "meal_choice"],
    )
    for person in people:
        nonce = person.pop("entry_nonce")
        person["functions"] = [
            dict(function=f.name, attendance="Declined", allocation="Unallocated", meal_choice="")
            for f in functions
        ]
        for answer in person["functions"]:
            existing = next(
                (r for r in responses if r.attendee == person.name and r.function == answer["function"]), None
            )
            if existing:
                answer.update({k: existing[k] for k in ["attendance", "allocation", "meal_choice"]})
        person["entry_token"] = (
            token_for(nonce, "entry")
            if any(r["allocation"] == "Confirmed" for r in person["functions"])
            else None
        )
        from frappe.utils.print_format_generator import get_qr_code

        person["entry_qr"] = get_qr_code(person["entry_token"]) if person["entry_token"] else None
    # Explicit projection: no team, guest directory, delivery logs or invitation secrets.
    return dict(
        event={
            k: event.get(k)
            for k in [
                "event_title",
                "host_name",
                "starts_on",
                "ends_on",
                "timezone",
                "rsvp_deadline",
                "venue",
                "map_url",
                "allow_maybe",
                "contact_email",
                "contact_phone",
                "privacy_notice",
            ]
        }
        | {
            "description": frappe.utils.strip_html(event.description or ""),
            "banner": event.banner if event.banner and event.banner.startswith("/files/") else None,
        },
        notes=invitation.notes,
        invitation=dict(
            guest_name=invitation.guest_name,
            max_attendees=invitation.max_attendees,
            response_status=invitation.response_status,
        ),
        functions=functions,
        attendees=people,
        editable=event.status == "Published"
        and event_now(event.timezone) <= get_datetime(event.rsvp_deadline),
    )


def apply_response(invitation_name, response, people, notes="", actor=None, expected_token_hash=None):
    event_name = frappe.db.get_value("RSVP Invitation", invitation_name, "event")
    lock_event(event_name)
    invitation = current_doc("RSVP Invitation", invitation_name)
    event = current_doc("RSVP Event", invitation.event)
    if expected_token_hash is not None and invitation.token_hash != expected_token_hash:
        frappe.throw("This invitation link has been replaced.", frappe.PermissionError)
    if invitation.revoked or event.status != "Published":
        frappe.throw("RSVP responses are closed for this event.")
    if event_now(event.timezone) > get_datetime(event.rsvp_deadline):
        frappe.throw("The RSVP deadline has passed. Contact the organiser.")
    if response not in {"Attending", "Declined", "Maybe"} or (response == "Maybe" and not event.allow_maybe):
        frappe.throw("Choose a valid attendance response.")
    functions = {f.name: f for f in functions_for(event.name)}
    if not functions:
        frappe.throw("No functions are available. Contact the organiser.")
    try:
        notes = clean_text(notes, 1000)
        validate_people(people, cint(invitation.max_attendees), functions, bool(event.allow_maybe))
    except (ValueError, TypeError) as error:
        frappe.throw(str(error))
    if response == "Attending" and (
        not people or not any(a["attendance"] == "Attending" for p in people for a in p["functions"])
    ):
        frappe.throw("Add at least one person attending a function.")
    if response != "Attending" and any(
        a["attendance"] == "Attending" for p in people for a in p["functions"]
    ):
        frappe.throw("Attending people require an Attending invitation response.")
    existing = {
        p.name: p
        for p in current_rows(
            "RSVP Attendee", filters={"invitation": invitation.name}, fields=["name", "active"]
        )
    }
    if any(p.get("name") and p["name"] not in existing for p in people):
        frappe.throw("An attendee does not belong to this invitation.", frappe.PermissionError)
    keep = {p.get("name") for p in people if p.get("name")}
    checked = current_rows(
        "RSVP Check-in",
        filters={"event": event.name, "status": "Checked In", "attendee": ["in", list(existing) or [""]]},
        fields=["attendee", "function"],
    )
    for check in checked:
        person = next((p for p in people if p.get("name") == check.attendee), None)
        answer = (
            next((a for a in person["functions"] if a["function"] == check.function), None)
            if person
            else None
        )
        if not answer or answer["attendance"] != "Attending" or response != "Attending":
            frappe.throw("Ask the organiser to reverse check-in before cancelling this attendee.")
    with service_write():
        # Release removed/declined places before computing availability, inside one transaction.
        for name in existing:
            if name not in keep:
                frappe.db.set_value("RSVP Attendee", name, "active", 0)
                for row in current_rows("RSVP Function Response", filters={"attendee": name}, pluck="name"):
                    doc = current_doc("RSVP Function Response", row)
                    doc.attendance = "Declined"
                    doc.allocation = "Cancelled"
                    doc.save(ignore_permissions=True)
        for person in people:
            if not person.get("name"):
                doc = current_doc(dict(doctype="RSVP Attendee", event=event.name, invitation=invitation.name))
            else:
                doc = current_doc("RSVP Attendee", person["name"])
            for key in ["attendee_name", "age_group", "dietary_requirements", "accessibility_requests"]:
                doc.set(key, person.get(key, "Adult" if key == "age_group" else "").strip())
            doc.active = 1
            save_doc(doc)
            person["name"] = doc.name
        # First cancel non-attendance so a single edit can move places between people.
        for person in people:
            for answer in person["functions"]:
                name = current_value(
                    "RSVP Function Response", {"attendee": person["name"], "function": answer["function"]}
                )
                if name and answer["attendance"] != "Attending":
                    row = current_doc("RSVP Function Response", name)
                    row.attendance = answer["attendance"]
                    row.allocation = "Cancelled" if answer["attendance"] == "Declined" else "Unallocated"
                    row.meal_choice = ""
                    row.save(ignore_permissions=True)
        # Existing waitlisted people have priority over newly requested places.
        promote_waitlist(event)
        for person in people:
            for answer in person["functions"]:
                function = functions[answer["function"]]
                name = current_value(
                    "RSVP Function Response", {"attendee": person["name"], "function": function.name}
                )
                row = (
                    current_doc("RSVP Function Response", name)
                    if name
                    else current_doc(
                        dict(
                            doctype="RSVP Function Response",
                            event=event.name,
                            invitation=invitation.name,
                            attendee=person["name"],
                            function=function.name,
                        )
                    )
                )
                used = current_count(
                    "RSVP Function Response", {"function": function.name, "allocation": "Confirmed"}
                )
                try:
                    allocation = allocation_for(
                        answer["attendance"],
                        row.get("allocation") == "Confirmed",
                        cint(function.capacity),
                        used,
                        event.enable_waitlist,
                    )
                except ValueError as error:
                    frappe.throw(str(error))
                if allocation == "Waitlisted" and row.get("allocation") != "Waitlisted":
                    row.waitlisted_on = now_datetime()
                row.attendance = answer["attendance"]
                row.allocation = allocation
                row.meal_choice = answer.get("meal_choice", "") if answer["attendance"] == "Attending" else ""
                save_doc(row)
        invitation.response_status = response
        invitation.responded_on = now_datetime()
        invitation.response_by = actor or frappe.session.user
        invitation.notes = notes
        invitation.save(ignore_permissions=True)
        promote_waitlist(event)
    from av_rsvp.messaging import queue_message

    if invitation.email:
        queue_message(
            invitation, "Confirmation", dedup_key=f"confirmation:{invitation.name}:{invitation.modified}"
        )
    return snapshot(invitation, event)


def promote_waitlist(event):
    """Caller holds the event lock. FIFO individual allocation; no promise of group seating."""
    if event.status not in {"Published", "Registration Closed"}:
        return 0
    promoted = 0
    for function in functions_for(event.name):
        used = current_count("RSVP Function Response", {"function": function.name, "allocation": "Confirmed"})
        rows = current_rows(
            "RSVP Function Response",
            filters={"function": function.name, "allocation": "Waitlisted", "attendance": "Attending"},
            fields=["name", "invitation", "attendee"],
            order_by="waitlisted_on, creation, name",
        )
        for row in rows:
            if function.capacity and used >= function.capacity:
                break
            if current_value("RSVP Invitation", row.invitation, "revoked") or not current_value(
                "RSVP Attendee", row.attendee, "active"
            ):
                continue
            doc = current_doc("RSVP Function Response", row.name)
            doc.allocation = "Confirmed"
            doc.save(ignore_permissions=True)
            used += 1
            promoted += 1
            invitation = current_doc("RSVP Invitation", row.invitation)
            if invitation.email:
                from av_rsvp.messaging import queue_message

                queue_message(invitation, "Confirmation", dedup_key=f"promotion:{row.name}:{doc.modified}")
    return promoted


def check_in(function_name, attendee_name=None, entry_token=None):
    from av_rsvp.permissions import require_event

    event_name = frappe.db.get_value("RSVP Function", function_name, "event")
    require_event(event_name, 1)
    lock_event(event_name)
    function = current_doc("RSVP Function", function_name)
    event = current_doc("RSVP Event", function.event)
    if event.status not in {"Published", "Registration Closed"} or not function.enabled:
        frappe.throw("Check-in is not available for this event or function.")
    if entry_token:
        if not isinstance(entry_token, str) or len(entry_token) != 64:
            frappe.throw("Invalid entry pass.")
        attendee_name = current_value(
            "RSVP Attendee", {"entry_hash": digest(entry_token), "event": event.name, "active": 1}
        )
    if not attendee_name:
        frappe.throw("Attendee not found.")
    attendee = current_doc("RSVP Attendee", attendee_name)
    if attendee.event != event.name or not attendee.active:
        frappe.throw("This attendee is not active for this event.")
    if current_value("RSVP Invitation", attendee.invitation, "revoked"):
        frappe.throw("This invitation has been revoked.")
    response = current_value(
        "RSVP Function Response",
        {"attendee": attendee.name, "function": function.name, "allocation": "Confirmed"},
        "name",
    )
    if not response:
        frappe.throw("This attendee has no confirmed place for this function.")
    name = current_value("RSVP Check-in", {"response": response}, "name")
    with service_write():
        doc = (
            current_doc("RSVP Check-in", name)
            if name
            else current_doc(
                dict(
                    doctype="RSVP Check-in",
                    event=event.name,
                    function=function.name,
                    attendee=attendee.name,
                    response=response,
                )
            )
        )
        if name and doc.status == "Checked In":
            return dict(
                name=doc.name,
                attendee_name=attendee.attendee_name,
                already_checked_in=True,
                checked_in_on=doc.checked_in_on,
            )
        doc.status = "Checked In"
        doc.checked_in_on = now_datetime()
        doc.checked_in_by = frappe.session.user
        doc.reversed_on = doc.reversed_by = doc.reversal_reason = None
        save_doc(doc)
    return dict(
        name=doc.name,
        attendee_name=attendee.attendee_name,
        already_checked_in=False,
        checked_in_on=doc.checked_in_on,
    )
