import unittest
from datetime import datetime
from types import SimpleNamespace

from av_rsvp.calendar import calendar_content
from av_rsvp.domain import allocation_for, clean_text, event_now, validate_people


class BookingRules(unittest.TestCase):
    def test_last_seat_and_waiting_list(self):
        self.assertEqual(allocation_for("Attending", False, 10, 9, True), "Confirmed")
        self.assertEqual(allocation_for("Attending", False, 10, 10, True), "Waitlisted")
        with self.assertRaises(ValueError):
            allocation_for("Attending", False, 10, 10, False)

    def test_existing_booking_keeps_its_place_at_capacity(self):
        self.assertEqual(allocation_for("Attending", True, 10, 10, False), "Confirmed")

    def test_nonattendance_never_consumes_capacity(self):
        self.assertEqual(allocation_for("Declined", True, 10, 10, True), "Cancelled")
        self.assertEqual(allocation_for("Maybe", False, 1, 1, False), "Unallocated")

    def test_zero_capacity_is_unlimited(self):
        self.assertEqual(allocation_for("Attending", False, 0, 10000, False), "Confirmed")

    def person(self, **extra):
        return dict(
            attendee_name="Asha",
            functions=[dict(function="dinner", attendance="Attending", meal_choice="Vegetarian")],
            **extra,
        )

    def test_guest_limit_duplicate_identity_and_missing_function(self):
        functions = {"dinner": {"meal_options": "Vegetarian\nStandard"}}
        with self.assertRaises(ValueError):
            validate_people([self.person(), self.person()], 1, functions, True)
        with self.assertRaises(ValueError):
            validate_people([self.person(name="A"), self.person(name="A")], 2, functions, True)
        person = self.person()
        person["functions"] = []
        with self.assertRaises(ValueError):
            validate_people([person], 1, functions, True)

    def test_meals_and_maybe_setting(self):
        functions = {"dinner": {"meal_options": "Vegetarian"}}
        person = self.person()
        validate_people([person], 1, functions, True)
        person["functions"][0]["meal_choice"] = "Unknown"
        with self.assertRaises(ValueError):
            validate_people([person], 1, functions, True)
        person["functions"][0].update(attendance="Maybe", meal_choice="")
        with self.assertRaises(ValueError):
            validate_people([person], 1, functions, False)

    def test_malformed_payload(self):
        for people in [None, "bad", [{}], [None]]:
            with self.assertRaises(ValueError):
                validate_people(people, 2, {"dinner": {}}, True)
        with self.assertRaises(ValueError):
            clean_text("x\x00")

    def test_event_clock_and_calendar_conversion(self):
        self.assertIsInstance(event_now("Africa/Dar_es_Salaam"), datetime)
        event = SimpleNamespace(
            name="EVT-1",
            timezone="Africa/Dar_es_Salaam",
            starts_on="2027-01-01 18:00:00",
            ends_on="2027-01-01 20:00:00",
            event_title="Dinner, friends\nBEGIN:BAD",
            venue="Dar es Salaam",
        )
        calendar = calendar_content(event)
        self.assertIn("DTSTART:20270101T150000Z", calendar)
        self.assertNotIn("\r\nBEGIN:BAD", calendar)
        self.assertIn("SUMMARY:Dinner\\, friends\\nBEGIN:BAD", calendar)
        event.event_title = "é" * 200
        self.assertTrue(all(len(line.encode()) <= 75 for line in calendar_content(event).split("\r\n")))


if __name__ == "__main__":
    unittest.main()
