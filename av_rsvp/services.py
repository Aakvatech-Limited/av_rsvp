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
        notes=invitation.notes,
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
            "contact_email",
            "contact_phone",
            "privacy_notice",
        ]
    } | {
        "form_sections": section_order(event.form_sections),
        "additional_questions": [
            {key: row.get(key) for key in ["question_key", "question_label", "question_type", "options"]}
            for row in event.additional_questions
        ],
        "description": frappe.utils.sanitize_html(event.description or ""),
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
        notes = clean_text(notes, 1000)
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
   …283 tokens truncated…datetime() + timedelta(days=31),
                rsvp_deadline=now_datetime() + timedelta(days=29),
                timezone="Africa/Dar_es_Salaam",
                venue="Dar es Salaam",
                enable_waitlist=1,
                allow_maybe=1,
            )
        ).insert()
        self.function = frappe.get_doc("RSVP Function", {"event": self.event.name})
        self.function.capacity = 1
        self.function.save()
        self.event.status = "Published"
        self.event.save()
        self.invitation = self.invite("Asha")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def invite(self, name):
        guest = frappe.get_doc(dict(doctype="RSVP Guest", guest_name=name)).insert()
        return frappe.get_doc(
            dict(
                doctype="RSVP Invitation",
                event=self.event.name,
                guest=guest.name,
                guest_name=name,
                max_attendees=2,
            )
        ).insert()

    def people(self, name="Asha", attendee=None, attendance="Attending"):
        person = dict(
            attendee_name=name,
            age_group="Adult",
            functions=[dict(function=self.function.name, attendance=attendance, meal_choice="")],
        )
        if attendee:
            person["name"] = attendee
        return [person]

    def test_response_token_scope_and_replay(self):
        token = token_for(self.invitation.access_nonce, "invitation")
        doc, _event = check_token(token)
        self.assertEqual(doc.name, self.invitation.name)
        result = apply_response(doc.name, "Attending", self.people())
        self.assertEqual(result["attendees"][0]["functions"][0]["allocation"], "Confirmed")
        person = result["attendees"][0]
        replay = apply_response(doc.name, "Attending", self.people(attendee=person.name))
        self.assertEqual(len(replay["attendees"]), 1)
        self.assertEqual(frappe.db.count("RSVP Function Response", {"invitation": doc.name}), 1)
        self.assertNotIn("access_nonce", str(result))
        self.assertNotIn("entry_nonce", str(result))
        self.assertTrue(person.entry_qr.startswith("data:image/svg+xml;base64,"))
        api.revoke_invitation(doc.name)
        with self.assertRaises(frappe.PermissionError):
            check_token(token)

    def test_waitlist_and_cancellation_promotes(self):
        first = apply_response(self.invitation.name, "Attending", self.people())
        other = self.invite("Juma")
        second = apply_response(other.name, "Attending", self.people("Juma"))
        self.assertEqual(second["attendees"][0]["functions"][0]["allocation"], "Waitlisted")
        apply_response(
            self.invitation.name,
            "Declined",
            self.people(attendee=first["attendees"][0].name, attendance="Declined"),
        )
        self.assertEqual(
            frappe.db.get_value("RSVP Function Response", {"invitation": other.name}, "allocation"),
            "Confirmed",
        )

    def test_no_waitlist_rejects_full_booking(self):
        apply_response(self.invitation.name, "Attending", self.people())
        self.event.enable_waitlist = 0
        self.event.save()
        other = self.invite("Juma")
        frappe.db.savepoint("full_booking")
        with self.assertRaises(frappe.ValidationError):
            apply_response(other.name, "Attending", self.people("Juma"))
        frappe.db.rollback(save_point="full_booking")
        self.assertEqual(frappe.db.count("RSVP Attendee", {"invitation": other.name}), 0)

    def test_foreign_attendee_and_over_allowance_rejected(self):
        first = apply_response(self.invitation.name, "Attending", self.people())
        other = self.invite("Juma")
        with self.assertRaises(frappe.PermissionError):
            apply_response(other.name, "Attending", self.people(attendee=first["attendees"][0].name))
        with self.assertRaises(frappe.ValidationError):
            apply_response(other.name, "Attending", self.people() * 3)

    def test_duplicate_checkin_and_reversal(self):
        result = apply_response(self.invitation.name, "Attending", self.people())
        person = result["attendees"][0]
        first = check_in(self.function.name, entry_token=person.entry_token)
        second = check_in(self.function.name, entry_token=person.entry_token)
        self.assertTrue(second["already_checked_in"])
        self.assertEqual(first["name"], second["name"])
        with self.assertRaises(frappe.ValidationError):
            apply_response(self.invitation.name, "Declined", [])
        with self.assertRaises(frappe.ValidationError):
            api.revoke_invitation(self.invitation.name)
        api.reverse_checkin(first["name"], "Wrong person scanned")
        third = check_in(self.function.name, attendee_name=person.name)
        self.assertFalse(third["already_checked_in"])
        self.assertEqual(first["name"], third["name"])

    def test_direct_operational_write_denied(self):
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                dict(
                    doctype="RSVP Attendee",
                    event=self.event.name,
                    invitation=self.invitation.name,
                    attendee_name="Bypass",
                )
            ).insert(ignore_permissions=True)

    def test_deadline_and_cancelled_event(self):
        frappe.db.set_value(
            "RSVP Event", self.event.name, "rsvp_deadline", now_datetime() - timedelta(days=1)
        )
        with self.assertRaises(frappe.ValidationError):
            apply_response(self.invitation.name, "Attending", self.people())
        frappe.db.set_value("RSVP Event", self.event.name, "status", "Cancelled")
        with self.assertRaises(frappe.PermissionError):
            check_token(token_for(self.invitation.access_nonce, "invitation"))

    def test_guest_cannot_access_desk_documents(self):
        frappe.set_user("Guest")
        self.assertEqual(access_level(self.event.name), 0)
        self.assertFalse(document_access(self.event, user="Guest", ptype="read"))
        with self.assertRaises(frappe.PermissionError):
            api.event_overview(self.event.name)

    def test_navigation_imported(self):
        for dt, name in [
            ("Workspace", "RSVP"),
            ("Sidebar", "RSVP"),
            ("Dock", "av_rsvp"),
            ("Page", "rsvp-overview"),
            ("Page", "rsvp-checkin"),
            ("Report", "RSVP Catering Requirements"),
        ]:
            self.assertTrue(frappe.db.exists(dt, name), f"Missing {dt}: {name}")

    def test_replaced_link_and_entry_pass_are_separate(self):
        old = token_for(self.invitation.access_nonce, "invitation")
        api.renew_invitation(self.invitation.name)
        with self.assertRaises(frappe.PermissionError):
            check_token(old)
        self.invitation.reload()
        result = apply_response(self.invitation.name, "Attending", self.people())
        with self.assertRaises(frappe.PermissionError):
            check_token(result["attendees"][0].entry_token)

    def test_coordinator_role_cannot_read_sensitive_data_in_checkin_assignment(self):
        email = f"rsvp-{frappe.generate_hash(length=10)}@example.com"
        user = frappe.get_doc(
            dict(
                doctype="User",
                email=email,
                first_name="RSVP Operator",
                send_welcome_email=0,
                roles=[dict(role="Event Coordinator"), dict(role="Check-in Operator")],
            )
        ).insert()
        self.event.append("team", dict(user=user.name, access_level="Check-in Operator"))
        self.event.save()
        result = apply_response(self.invitation.name, "Attending", self.people())
        person = frappe.get_doc("RSVP Attendee", result["attendees"][0].name)
        frappe.set_user(user.name)
        self.assertEqual(access_level(self.event.name), 1)
        self.assertFalse(document_access(person, ptype="read"))
        with self.assertRaises(frappe.PermissionError):
            api.event_overview(self.event.name)
        # Explicit check-in lookup is deliberately limited to name/category.
        rows = api.find_attendees(self.function.name)
        self.assertEqual(set(rows[0]), {"name", "attendee_name", "age_group"})
        with self.assertRaises(frappe.PermissionError):
            api.staff_invitation(self.invitation.name)

    def test_foreign_function_is_rejected(self):
        other_event = frappe.get_doc(
            dict(
                doctype="RSVP Event",
                event_title="Other",
                starts_on=now_datetime() + timedelta(days=30),
                ends_on=now_datetime() + timedelta(days=31),
                rsvp_deadline=now_datetime() + timedelta(days=29),
                timezone="Africa/Dar_es_Salaam",
                venue="Other venue",
            )
        ).insert()
        other_function = frappe.db.get_value("RSVP Function", {"event": other_event.name})
        people = self.people()
        people[0]["functions"][0]["function"] = other_function
        with self.assertRaises(frappe.ValidationError):
            apply_response(self.invitation.name, "Attending", people)

    def test_message_queue_deduplicates_each_delivery(self):
        from unittest.mock import patch

        from av_rsvp.messaging import queue_message
        from av_rsvp.security import lock_event

        lock_event(self.event.name)
        with patch("frappe.enqueue") as enqueue:
            self.assertTrue(queue_message(self.invitation, "Invitation", "one-test-delivery"))
            self.assertFalse(queue_message(self.invitation, "Invitation", "one-test-delivery"))
            self.assertEqual(enqueue.call_count, 1)

    def test_portal_and_calendar_convert_site_timestamps(self):
        from zoneinfo import ZoneInfo

        from frappe.utils import get_system_timezone

        from av_rsvp.services import snapshot

        result = snapshot(self.invitation, self.event)
        expected = (
            self.event.starts_on.replace(tzinfo=ZoneInfo(get_system_timezone()))
            .astimezone(ZoneInfo(self.event.timezone))
            .replace(tzinfo=None)
        )
        self.assertEqual(result["event"]["starts_on"], expected.isoformat(sep=" "))
        calendar = api.calendar(token_for(self.invitation.access_nonce, "invitation"))
        expected_utc = self.event.starts_on.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(
            ZoneInfo("UTC")
        )
        self.assertIn("DTSTART:" + expected_utc.strftime("%Y%m%dT%H%M%SZ"), calendar["content"])

    def test_event_questions_round_trip_reorder_and_scope(self):
        self.event.append(
            "additional_questions",
            dict(question_label="Transport", question_type="Select", options="Bus\nCar"),
        )
        self.event.append("additional_questions", dict(question_label="Comments", question_type="Long Text"))
        self.event.save()
        key = self.event.additional_questions[0].question_key
        token = token_for(self.invitation.access_nonce, "invitation")
        frappe.set_user("Guest")
        result = api.respond(token, "Attending", self.people(), additional_answers={key: "Bus"})
        self.assertEqual(result["additional_answers"], {key: "Bus"})
        saved = frappe.get_doc("RSVP Invitation", self.invitation.name)
        self.assertEqual(saved.additional_answers[0].question_label, "Transport")
        frappe.set_user("Administrator")
        self.event.additional_questions.reverse()
        for idx, question in enumerate(self.event.additional_questions, 1):
            question.idx = idx
        self.event.save()
        result = api.get_invitation(token)
        self.assertEqual(result["event"]["additional_questions"][1]["question_key"], key)
        self.assertEqual(result["additional_answers"][key], "Bus")
        with self.assertRaises(frappe.ValidationError):
            api.respond(token, "Attending", self.people(), additional_answers={key: "Train"})
        with self.assertRaises(frappe.ValidationError):
            api.respond(token, "Attending", self.people(), additional_answers={"other-event": "secret"})
        self.event.set("additional_questions", [])
        self.event.save()
        self.assertEqual(api.get_invitation(token)["additional_answers"], {})
        self.assertEqual(
            frappe.get_doc("RSVP Invitation", self.invitation.name).additional_answers[0].answer, "Bus"
        )

    def test_dietary_preferences_are_optional_configurable_and_hidden(self):
        self.event.dietary_options = "Vegetarian\nStandard"
        self.event.save()
        people = self.people()
        people[0]["dietary_requirements"] = "Vegetarian"
        result = apply_response(self.invitation.name, "Attending", people)
        attendee = result["attendees"][0].name
        people = self.people(attendee=attendee)
        people[0]["dietary_requirements"] = "Invalid choice"
        with self.assertRaises(frappe.ValidationError):
            apply_response(self.invitation.name, "Attending", people)
        self.event.show_dietary_preferences = 0
        self.event.save()
        result = apply_response(self.invitation.name, "Attending", people)
        self.assertEqual(result["attendees"][0].dietary_requirements, "")
        self.assertEqual(frappe.db.get_value("RSVP Attendee", attendee, "dietary_requirements"), "Vegetarian")
        self.event.show_dietary_preferences = 1
        self.event.save()
        result = apply_response(self.invitation.name, "Attending", self.people(attendee=attendee))
        self.assertEqual(result["attendees"][0].dietary_requirements, "")

    def test_disabled_additional_guests_enforced_for_private_and_public(self):
        self.open_registration()
        self.event.allow_additional_guests = 0
        self.event.save()
        self.assertEqual(api.get_registration(self.event.name)["invitation"]["max_attendees"], 1)
        with self.assertRaises(frappe.ValidationError):
            apply_response(self.invitation.name, "Attending", self.people() + self.people("Extra"))
        frappe.db.savepoint("no_extra_public")
        with self.assertRaises(frappe.ValidationError):
            self.registration(people=self.people() + self.people("Extra"))
        frappe.db.rollback(save_point="no_extra_public")
        result = self.registration()
        self.assertEqual(len(result["registration"]["attendees"]), 1)

    def test_disabling_extra_guests_keeps_existing_group_editable(self):
        group = apply_response(self.invitation.name, "Attending", self.people() + self.people("Extra"))
        self.event.allow_additional_guests = 0
        self.event.save()
        people = [
            dict(
                attendee_name=p.attendee_name,
                name=p.name,
                age_group="Adult",
                functions=[dict(function=self.function.name, attendance="Attending", meal_choice="")],
            )
            for p in group["attendees"]
        ]
        result = apply_response(self.invitation.name, "Attending", people)
        self.assertEqual(len(result["attendees"]), 2)
        people[1].pop("name")
        with self.assertRaises(frappe.ValidationError):
            apply_response(self.invitation.name, "Attending", people)

    def test_additional_answers_require_response_service(self):
        self.invitation.append(
            "additional_answers", dict(question_key="forged", question_label="Forged", answer="value")
        )
        with self.assertRaises(frappe.ValidationError):
            self.invitation.save()

    def test_hidden_first_guest_uses_contact_without_guest_input(self):
        self.open_registration()
        self.event.hide_first_guest_details = 1
        self.event.allow_additional_guests = 0
        self.event.save()
        frappe.set_user("Guest")
        result = self.registration(people=[])
        person = result["registration"]["attendees"][0]
        self.assertEqual(person.attendee_name, "Public guest")
        self.assertTrue(person.entry_token)
        token = result["token"]
        result = api.respond(token, "Declined", [])
        self.assertEqual(result["attendees"][0].name, person.name)
        self.assertEqual(result["attendees"][0].functions[0]["attendance"], "Declined")
        result = api.respond(token, "Attending", [])
        self.assertEqual(result["attendees"][0].functions[0]["allocation"], "Confirmed")

    def test_hidden_first_guest_cannot_be_replaced_or_duplicate_attendees_created(self):
        self.event.hide_first_guest_details = 1
        self.event.save()
        person = apply_response(self.invitation.name, "Attending", [])["attendees"][0]
        result = apply_response(self.invitation.name, "Attending", self.people("Forged name"))
        self.assertEqual(result["attendees"][0].name, person.name)
        self.assertEqual(result["attendees"][0].attendee_name, "Asha")
        self.assertEqual(frappe.db.count("RSVP Attendee", {"invitation": self.invitation.name}), 1)
        other = self.invite("Juma")
        foreign = apply_response(other.name, "Attending", [])["attendees"][0]
        with self.assertRaises(frappe.PermissionError):
            apply_response(self.invitation.name, "Attending", self.people(attendee=foreign.name))
        self.event.allow_additional_guests = 0
        self.event.save()
        with self.assertRaises(frappe.ValidationError):
            apply_response(self.invitation.name, "Attending", self.people() + self.people("Extra"))

    def test_hidden_first_guest_still_supports_function_meal_choices(self):
        self.function.reload()
        self.function.meal_options = "Vegetarian\nStandard"
        self.function.save()
        self.event.hide_first_guest_details = 1
        self.event.save()
        people = self.people("Ignored name")
        people[0]["functions"][0]["meal_choice"] = "Vegetarian"
        result = apply_response(self.invitation.name, "Attending", people)
        self.assertEqual(result["attendees"][0].attendee_name, "Asha")
        self.assertEqual(result["attendees"][0].functions[0]["meal_choice"], "Vegetarian")

    def test_event_form_section_order_is_saved_and_projected(self):
        self.open_registration()
        self.event.set("form_sections", [dict(section="Response"), dict(section="Contact Details")])
        self.event.save()
        self.assertEqual(len(self.event.form_sections), 5)
        expected = [row.section for row in self.event.form_sections]
        self.assertEqual(expected[:2], ["Response", "Contact Details"])
        self.assertEqual(api.get_registration(self.event.name)["event"]["form_sections"], expected)
        token = token_for(self.invitation.access_nonce, "invitation")
        self.assertEqual(api.get_invitation(token)["event"]["form_sections"], expected)
        self.event.append("form_sections", dict(section="Response"))
        with self.assertRaises(frappe.ValidationError):
            self.event.save()

    def open_registration(self):
        self.event.allow_public_registration = 1
        self.event.public_max_attendees = 2
        self.event.save()

    def registration(self, key="a" * 64, **overrides):
        args = dict(
            event=self.event.name,
            guest_name="Public guest",
            email="public@example.com",
            registration_key=key,
            response="Attending",
            people=self.people("Public guest"),
        )
        args.update(overrides)
        return api.register(**args)

    def test_event_registration_qr_is_public_link_png_and_event_scoped(self):
        import base64
        from urllib.parse import parse_qs, urlparse

        self.open_registration()
        result = api.event_registration_qr(self.event.name)
        self.assertEqual(parse_qs(urlparse(result["url"]).query), {"event": [self.event.name]})
        self.assertEqual(urlparse(result["url"]).path, "/rsvp")
        self.assertFalse(urlparse(result["url"]).fragment)
        self.assertTrue(result["image"].startswith("data:image/png;base64,"))
        self.assertTrue(base64.b64decode(result["image"].split(",", 1)[1]).startswith(b"\x89PNG\r\n\x1a\n"))
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.event_registration_qr(self.event.name)
        frappe.set_user("Administrator")
        self.event.allow_public_registration = 0
        self.event.save()
        with self.assertRaises(frappe.PermissionError):
            api.event_registration_qr(self.event.name)

    def test_public_guest_registers_without_account_and_retries(self):
        self.open_registration()
        frappe.set_user("Guest")
        public = api.get_registration(self.event.name)
        self.assertNotIn("team", public["event"])
        self.assertEqual(public["attendees"], [])
        first = self.registration()
        second = self.registration()
        self.assertEqual(first["token"], second["token"])
        self.assertEqual(
            first["registration"]["attendees"][0].name, second["registration"]["attendees"][0].name
        )
        invitation, _ = check_token(first["token"])
        guest = frappe.get_doc("RSVP Guest", invitation.guest)
        self.assertEqual(guest.guest_name, "Public guest")
        self.assertEqual(invitation.response_status, "Attending")
        self.assertEqual(invitation.response_by, "Guest via public registration")
        self.assertEqual(frappe.db.count("RSVP Invitation", {"event": self.event.name}), 2)
        self.assertTrue(first["registration"]["attendees"][0].entry_token)
        self.assertFalse(frappe.db.exists("User", "public@example.com"))

    def test_public_registration_is_opt_in_and_respects_closure(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.get_registration(self.event.name)
        with self.assertRaises(frappe.PermissionError):
            self.registration()
        frappe.set_user("Administrator")
        self.open_registration()
        for status in ["Draft", "Registration Closed", "Completed", "Cancelled"]:
            frappe.db.set_value("RSVP Event", self.event.name, "status", status)
            with self.assertRaises(frappe.PermissionError):
                self.registration()
        frappe.db.set_value("RSVP Event", self.event.name, "status", "Published")
        frappe.db.set_value(
            "RSVP Event", self.event.name, "rsvp_deadline", now_datetime() - timedelta(days=1)
        )
        with self.assertRaises(frappe.PermissionError):
            self.registration()

    def test_public_registration_contact_does_not_grant_existing_access(self):
        self.open_registration()
        first = self.registration()
        second = self.registration(key="b" * 64)
        self.assertNotEqual(first["token"], second["token"])
        a, _ = check_token(first["token"])
        b, _ = check_token(second["token"])
        self.assertNotEqual(a.guest, b.guest)
        self.assertEqual(second["registration"]["attendees"][0].functions[0]["allocation"], "Waitlisted")
        api.revoke_invitation(a.name)
        self.assertFalse(frappe.db.get_value("RSVP Invitation", a.name, "registration_key"))
        with self.assertRaises(frappe.PermissionError):
            api.get_invitation(first["token"])

    def test_public_registration_rejects_invalid_payload_without_orphans(self):
        self.open_registration()
        for overrides in [
            dict(guest_name=""),
            dict(email="invalid"),
            dict(registration_key="guess"),
            dict(people=self.people() * 3),
            dict(people=self.people(attendee="foreign")),
        ]:
            frappe.db.savepoint("public_invalid")
            before = frappe.db.count("RSVP Guest")
            with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
                self.registration(**overrides)
            frappe.db.rollback(save_point="public_invalid")
            self.assertEqual(frappe.db.count("RSVP Guest"), before)
            self.assertEqual(frappe.db.count("RSVP Invitation", {"event": self.event.name}), 1)

    def test_public_registration_capacity_failure_rolls_back_guest_and_invitation(self):
        self.open_registration()
        self.event.enable_waitlist = 0
        self.event.save()
        apply_response(self.invitation.name, "Attending", self.people())
        before = frappe.db.count("RSVP Guest")
        frappe.db.savepoint("public_capacity")
        with self.assertRaises(frappe.ValidationError):
            self.registration()
        frappe.db.rollback(save_point="public_capacity")
        self.assertEqual(frappe.db.count("RSVP Guest"), before)
        self.assertEqual(frappe.db.count("RSVP Invitation", {"event": self.event.name}), 1)


class TestConcurrentCapacity(IntegrationTestCase):
    def test_last_place_cannot_be_confirmed_twice(self):
        import os
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from av_rsvp.security import current_count, lock_event

        frappe.set_user("Administrator")
        event = frappe.get_doc(
            dict(
                doctype="RSVP Event",
                event_title="Concurrent capacity test",
                starts_on=now_datetime() + timedelta(days=30),
                ends_on=now_datetime() + timedelta(days=31),
                rsvp_deadline=now_datetime() + timedelta(days=29),
                timezone="Africa/Dar_es_Salaam",
                venue="Test venue",
                enable_waitlist=1,
            )
        ).insert()
        function = frappe.get_doc("RSVP Function", {"event": event.name})
        function.capacity = 1
        function.save()
        event.status = "Published"
        event.save()
        guests, invitations = [], []
        for name in ["Concurrent A", "Concurrent B"]:
            guest = frappe.get_doc(dict(doctype="RSVP Guest", guest_name=name)).insert()
            guests.append(guest.name)
            invitations.append(
                frappe.get_doc(
                    dict(
                        doctype="RSVP Invitation",
                        event=event.name,
                        guest=guest.name,
                        guest_name=name,
                        max_attendees=1,
                    )
                )
                .insert()
                .name
            )
        # Independent HTTP requests only see committed fixtures.
        frappe.db.commit()
        site, sites_path = frappe.local.site, os.path.abspath(frappe.local.sites_path)
        barrier = threading.Barrier(2, timeout=20)

        def book(invitation):
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                # Establish a snapshot before contending for the event lock.
                frappe.db.get_value("RSVP Invitation", invitation, "response_status")
                barrier.wait()
                result = api.record_response(
                    invitation,
                    "Attending",
                    [
                        dict(
                            attendee_name=invitation,
                            age_group="Adult",
                            functions=[dict(function=function.name, attendance="Attending", meal_choice="")],
                        )
                    ],
                )
                frappe.db.commit()
                return result["attendees"][0]["functions"][0]["allocation"]
            except Exception:
                frappe.db.rollback()
                raise
            finally:
                frappe.destroy()

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(book, invitations))
            lock_event(event.name)
            self.assertEqual(sorted(results), ["Confirmed", "Waitlisted"])
            self.assertEqual(
                current_count("RSVP Function Response", {"event": event.name, "allocation": "Confirmed"}), 1
            )
        finally:
            frappe.db.rollback()
            # This test deliberately commits across connections; remove only its fixtures.
            for dt in [
                "RSVP Check-in",
                "RSVP Function Response",
                "RSVP Attendee",
                "RSVP Message Log",
                "RSVP Invitation",
                "RSVP Function",
            ]:
                frappe.db.delete(dt, {"event": event.name})
            frappe.db.delete("RSVP Event Team", {"parent": event.name})
            frappe.db.delete("RSVP Form Section", {"parent": event.name})
            frappe.db.delete("RSVP Event", {"name": event.name})
            frappe.db.delete("RSVP Guest", {"name": ["in", guests]})
            frappe.db.commit()
