"""Regression checks for optional organiser notes, event footer and calendar confirmation."""

import json
import unittest
from datetime import datetime
from pathlib import Path

from av_rsvp.calendar import calendar_content

ROOT = Path(__file__).resolve().parents[1] / "av_rsvp"


class EventPresentation(unittest.TestCase):
    def test_event_fields_exist_with_safe_defaults(self):
        data = json.loads((ROOT / "rsvp/doctype/rsvp_event/rsvp_event.json").read_text())
        fields = {item["fieldname"]: item for item in data["fields"]}
        self.assertNotIn("show_message_to_organizer", fields)
        form_section = json.loads((ROOT / "rsvp/doctype/rsvp_form_section/rsvp_form_section.json").read_text())
        self.assertIn("hide", [field["fieldname"] for field in form_section["fields"]])
        self.assertEqual(fields["footer_text"]["fieldtype"], "Text Editor")

    def test_private_projection_sanitizes_footer(self):
        source = (ROOT / "services.py").read_text()
        self.assertIn('frappe.utils.sanitize_html(event.footer_text or "")', source)
        self.assertIn('"Message to Organiser" not in hidden_sections(event.form_sections)', source)

    def test_confirmation_attachment_is_conditioned_on_confirmed_attendance(self):
        source = (ROOT / "messaging.py").read_text()
        self.assertIn('log.purpose == "Confirmation" and invitation.response_status == "Attending"', source)
        self.assertIn('r.allocation == "Confirmed"', source)
        self.assertIn('"fname": "event-invitation.ics"', source)
        self.assertIn('attachments=attachments', source)

    def test_calendar_is_standard_utc_ics(self):
        class Event:
            name = "RSVP-TEST"
            timezone = "Africa/Dar_es_Salaam"
            starts_on = datetime(2026, 11, 10, 18)
            ends_on = datetime(2026, 11, 10, 21)
            event_title = "Dinner & Reception"
            venue = "Dar es Salaam"

        content = calendar_content(Event(), source_timezone="Africa/Dar_es_Salaam")
        self.assertIn("BEGIN:VCALENDAR\\r\\n", content)
        self.assertIn("BEGIN:VEVENT\\r\\n", content)
        self.assertIn("DTSTART:20261110T150000Z", content)
        self.assertIn("DTEND:20261110T180000Z", content)
        self.assertIn("SUMMARY:Dinner & Reception", content)
        self.assertTrue(content.endswith("END:VCALENDAR\\r\\n"))


if __name__ == "__main__":
    unittest.main()
