import unittest
from types import SimpleNamespace as Row

from av_rsvp.post_event_metrics import attendance_summary


def response(event, function, attendee, allocation="Confirmed"):
    return Row(event=event, function=function, attendee=attendee, allocation=allocation)


def check(event, function, attendee, status="Checked In"):
    return Row(event=event, function=function, attendee=attendee, status=status)


class PostEventMetrics(unittest.TestCase):
    def test_multiple_functions_count_a_person_once_and_places_separately(self):
        result = attendance_summary(
            [response("a", "f1", "x"), response("a", "f2", "x")],
            [check("a", "f1", "x"), check("a", "f2", "x")],
        )
        self.assertEqual(result["confirmed_people"], 1)
        self.assertEqual(result["attended_people"], 1)
        self.assertEqual(result["confirmed_places"], 2)
        self.assertEqual(result["attendance_rate"], 100)

    def test_no_shows_use_set_difference_and_reversals_are_excluded(self):
        result = attendance_summary(
            [response("a", "f", "x"), response("a", "f", "y")],
            [check("a", "f", "x", "Reversed"), check("a", "f", "z")],
        )
        self.assertEqual(result["no_shows"], 2)
        self.assertEqual(result["attended_people"], 1)
        self.assertEqual(result["attendance_rate"], 0)

    def test_waitlist_is_not_a_confirmation_and_zero_denominator_is_na(self):
        result = attendance_summary([response("a", "f", "x", "Waitlisted")], [])
        self.assertIsNone(result["attendance_rate"])
        self.assertEqual(result["no_shows"], 0)

    def test_partial_function_attendance_and_multiple_events(self):
        result = attendance_summary(
            [response("a", "f1", "x"), response("a", "f2", "x"), response("b", "f3", "x")],
            [check("a", "f1", "x")],
        )
        self.assertEqual(result["confirmed_people"], 2)
        self.assertEqual(result["no_shows"], 1)
        self.assertEqual(result["no_show_places"], 2)
        self.assertEqual(result["attendance_rate"], 50)
