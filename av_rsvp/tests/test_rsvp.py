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
            frappe.db.delete("RSVP Event", {"name": event.name})
            frappe.db.delete("RSVP Guest", {"name": ["in", guests]})
            frappe.db.commit()
