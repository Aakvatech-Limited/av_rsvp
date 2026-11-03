"""Run with bench --site test_site run-tests --app av_rsvp."""

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from av_rsvp import api
from av_rsvp.permissions import access_level, document_access
from av_rsvp.security import check_token, token_for
from av_rsvp.services import apply_response, check_in


class TestRSVP(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.event = frappe.get_doc(
            dict(
                doctype="RSVP Event",
                event_title="Test reception",
                host_name="Aakvatech",
                starts_on=now_datetime() + timedelta(days=30),
                ends_on=now_datetime() + timedelta(days=31),
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
        self.assertEqual(len(self.event.form_sections), 6)
        expected = [row.section for row in self.event.form_sections]
        self.assertEqual(expected[:3], ["Event Information", "Response", "Contact Details"])
        self.assertEqual(api.get_registration(self.event.name)["event"]["form_sections"], expected)
        token = token_for(self.invitation.access_nonce, "invitation")
        self.assertEqual(api.get_invitation(token)["event"]["form_sections"], expected)
        self.event.append("form_sections", dict(section="Response"))
        with self.assertRaises(frappe.ValidationError):
            self.event.save()

    def test_event_web_page_creation_preserves_custom_code_and_changes_links(self):
        from av_rsvp.event_pages import registration_url
        from av_rsvp.security import invitation_url

        self.open_registration()
        result = api.create_event_web_page(self.event.name)
        self.event.reload()
        page = frappe.get_doc("Web Page", result["name"])
        self.assertEqual(self.event.event_web_page, page.name)
        self.assertEqual(page.content_type, "HTML")
        self.assertFalse(page.published)
        self.assertIn('data-event="' + self.event.name + '"', page.main_section_html)
        self.assertIn("data-rsvp-event-information", page.main_section_html)
        self.assertIn("frappe.ready", page.javascript)
        self.assertIn(".rsvp-shell", page.css)
        original_js = page.javascript
        page.main_section_html += "<p>Our custom footer</p>"
        page.css += "\n.event-information {color: navy;}"
        page.javascript += "\n/* event-specific script */"
        page.published = 1
        page.save()
        api.create_event_web_page(self.event.name)
        page.reload()
        self.assertIn("Our custom footer", page.main_section_html)
        self.assertEqual(page.javascript, original_js + "\n/* event-specific script */")
        self.assertTrue(registration_url(self.event).endswith("/" + page.route))
        self.assertTrue(api.event_registration_qr(self.event.name)["url"].endswith("/" + page.route))
        self.assertIn("/" + page.route + "#", invitation_url(self.invitation))
        self.assertTrue(
            api.get_registration(self.event.name)["event"]["event_page_url"].endswith("/" + page.route)
        )
        page.published = 0
        page.save()
        self.assertIn("/rsvp?event=", registration_url(self.event))
        self.assertIsNone(api.get_registration(self.event.name)["event"].get("event_page_url"))

    def test_event_web_page_creation_requires_event_and_website_access(self):
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            api.create_event_web_page(self.event.name)

    def test_event_information_can_be_moved_or_hidden(self):
        from av_rsvp.questions import FORM_SECTIONS

        self.open_registration()
        self.event.set(
            "form_sections", [dict(section=name) for name in [*FORM_SECTIONS[1:], "Event Information"]]
        )
        self.event.show_event_information = 0
        self.event.save()
        result = api.get_registration(self.event.name)
        self.assertEqual(result["event"]["form_sections"][-1], "Event Information")
        self.assertEqual(result["event"]["show_event_information"], 0)
        self.assertEqual(
            frappe.db.get_value("RSVP Event", self.event.name, "event_title"), self.event.event_title
        )

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
