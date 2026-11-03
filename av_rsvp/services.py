"""All state transitions share the event row lock and the caller's transaction."""

import frappe
from frappe.utils import cint, get_datetime, now_datetime

from av_rsvp.domain import allocation_for, clean_text, validate_people
from av_rsvp.questions import choices, section_order, validate_answers
from av_rsvp.security import (
    current_count,
    current_doc,
    current_rows,
    current_value,
    digest,
    display_datetime,
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
        if not event.show_dietary_preferences:
            person["dietary_requirements"] = ""
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
    for function in functions:
        for key in ["starts_on", "ends_on"]:
            function[key] = display_datetime(function[key], event.timezone)
    # Explicit projection: no team, guest directory, delivery logs or invitation secrets.
    return dict(
        event=public_event_details(event),
        notes=invitation.notes if event.show_message_to_organizer else "",
        additional_answers={
            row.question_key: row.answer
            for row in invitation.additional_answers
            if row.question_key in {q.question_key for q in event.additional_questions}
        },
        invitation=dict(
            guest_name=invitation.guest_name,
            max_attendees=invitation.max_attendees if event.allow_additional_guests else max(1, len(people)),
            response_status=invitation.response_status,
        ),
        functions=functions,
        attendees=people,
        editable=event.status == "Published" and now_datetime() <= get_datetime(event.rsvp_deadline),
    )


def public_event_details(event):
    from av_rsvp.event_pages import published_page_url

    """Safe event fields shared by private invitations and public registration."""
    return {
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
            "show_dietary_preferences",
            "dietary_options",
            "allow_additional_guests",
            "hide_first_guest_details",
            "show_event_information",
            "show_message_to_organizer",
            "contact_email",
            "contact_phone",
            "privacy_notice",
        ]
    } | {
        "event_page_url": published_page_url(event),
        "form_sections": section_order(event.form_sections),
        "additional_questions": [
            {key: row.get(key) for key in ["question_key", "question_label", "question_type", "options"]}
            for row in event.additional_questions
        ],
        "description": frappe.utils.sanitize_html(event.description or ""),
        "footer_text": frappe.utils.sanitize_html(event.footer_text or ""),
        "banner": event.banner if event.banner and event.banner.startswith("/files/") else None,
        **{
            key: display_datetime(event.get(key), event.timezone)
            for key in ["starts_on", "ends_on", "rsvp_deadline"]
        },
    }


def primary_contact_person(invitation, functions, people, response):
    """Use the trusted invitation contact for the hidden first attendee."""
    if not isinstance(people, list) or any(not isinstance(person, dict) for person in people):
        frappe.throw("Invalid attendees.")
    existing = current_rows(
        "RSVP Attendee",
        filters={"invitation": invitation.name, "active": 1},
        fields=["name", "attendee_name", "age_group", "dietary_requirements", "accessibility_requests"],
        order_by="creation, name",
    )
    primary = existing[0] if existing else None
    person = people[0] if people else {}
    if person.get("name") and (not primary or person["name"] != primary.name):
        frappe.throw("The first attendee must be the main contact.", frappe.PermissionError)
    # Guests cannot replace hidden details through a forged request. Existing
    # personal details remain stored; new attendees use the invitation contact.
    for key in ["attendee_name", "age_group", "dietary_requirements", "accessibility_requests"]:
        person[key] = (
            primary.get(key)
            if primary
            else {"attendee_name": invitation.guest_name, "age_group": "Adult"}.get(key, "")
        )
    if primary:
        person["name"] = primary.name
    if not person.get("functions"):
        previous = {
            row.function: row
            for row in current_rows(
                "RSVP Function Response",
                filters={"attendee": primary.name if primary else ""},
                fields=["function", "meal_choice"],
            )
        }
        person["functions"] = [
            dict(
                function=function.name,
                attendance=response,
                meal_choice=(previous.get(function.name, {}).get("meal_choice") or "")
                if response == "Attending"
                else "",
            )
            for function in functions.values()
        ]
    # The overall answer is sufficient for a simple event with no meal choices.
    if len(functions) == 1 and not (next(iter(functions.values())).meal_options or "").strip():
        person["functions"] = [dict(function=next(iter(functions)), attendance=response, meal_choice="")]
    return [person, *people[1:]]


def apply_response(
    invitation_name, response, people, notes="", actor=None, expected_token_hash=None, additional_answers=None
):
    event_name = frappe.db.get_value("RSVP Invitation", invitation_name, "event")
    lock_event(event_name)
    invitation = current_doc("RSVP Invitation", invitation_name)
    event = current_doc("RSVP Event", invitation.event)
    if expected_token_hash is not None and invitation.token_hash != expected_token_hash:
        frappe.throw("This invitation link has been replaced.", frappe.PermissionError)
    if invitation.revoked or event.status != "Published":
        frappe.throw("RSVP responses are closed for this event.")
    if now_datetime() > get_datetime(event.rsvp_deadline):
        frappe.throw("The RSVP deadline has passed. Contact the organiser.")
    if response not in {"Attending", "Declined", "Maybe"} or (response == "Maybe" and not event.allow_maybe):
        frappe.throw("Choose a valid attendance response.")
    functions = {f.name: f for f in functions_for(event.name)}
    if not functions:
        frappe.throw("No functions are available. Contact the organiser.")
    if event.hide_first_guest_details:
        people = primary_contact_person(invitation, functions, people, response)
    try:
        notes = clean_text(notes, 1000) if event.show_message_to_organizer else invitation.notes
        validate_people(people, cint(invitation.max_attendees), functions, bool(event.allow_maybe))
        answers = (
            validate_answers(event.additional_questions, frappe.parse_json(additional_answers))
            if additional_answers is not None
            else None
        )
        dietary_choices = choices(event.dietary_options) if event.show_dietary_preferences else []
        if dietary_choices and any(
            p.get("dietary_requirements", "").strip()
            and p["dietary_requirements"].strip() not in dietary_choices
            for p in (people[1:] if event.hide_first_guest_details else people)
        ):
            raise ValueError("Choose a dietary preference from the event options, or leave it empty.")
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
    if not event.allow_additional_guests and len(people) > 1:
        if any(not p.get("name") or not existing.get(p["name"], {}).get("active") for p in people):
            frappe.throw("Additional guests are disabled for this event.")
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
                if key == "dietary_requirements" and not event.show_dietary_preferences:
                    continue
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
        if answers is not None:
            existing_answers = {row.question_key: row for row in invitation.additional_answers}
            labels = {row.question_key: row.question_label for row in event.additional_questions}
            for key, value in answers.items():
                row = existing_answers.get(key)
                if not row:
                    row = invitation.append("additional_answers", {"question_key": key})
                row.question_label = labels[key]
                row.answer = value
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
    from av_rsvp.permissions import access_level, require_event

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
                can_reverse=access_level(event.name) >= 2,
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
        can_reverse=access_level(event.name) >= 2,
        checked_in_on=doc.checked_in_on,
    )
