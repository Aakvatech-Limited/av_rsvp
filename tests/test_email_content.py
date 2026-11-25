import unittest

from av_rsvp.email_content import email_content


class Record(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class EmailContent(unittest.TestCase):
    def setUp(self):
        self.event = Record(
            event_title="Installation & Dinner",
            starts_on="2026-11-20 15:00:00",
            ends_on="2026-11-20 18:00:00",
            rsvp_deadline="2026-11-19 12:00:00",
            timezone="Africa/Dar_es_Salaam",
            venue="Lodge Hall",
            host_name="Guiding Star Lodge No. 5299",
            description="<p>Dress code: Formal</p>",
        )
        self.invitation = Record(guest_name="Asha", response_status="Attending")
        self.url = "https://events.example.com/rsvp#private-token"

    def render(self, purpose="Invitation", **kwargs):
        return email_content(self.invitation, self.event, purpose, self.url, "UTC", **kwargs)

    def test_invitation_details_and_timezone(self):
        subject, body = self.render()
        self.assertEqual(subject, "Your Invitation | Installation & Dinner")
        for value in (
            "Dear Asha",
            "18:00 – 21:00 EAT",
            "19 November 2026 at 15:00",
            "Lodge Hall",
            "Guiding Star Lodge No. 5299",
            "Dress code: Formal",
            self.url,
        ):
            self.assertIn(value, body)
        self.assertIn("View Invitation &amp; RSVP", body)

    def test_user_content_is_escaped(self):
        self.invitation.guest_name = '<img src=x onerror="alert(1)">'
        self.event.venue = "<script>bad()</script>"
        _, body = self.render()
        self.assertNotIn("<img", body)
        self.assertNotIn("<script", body)
        self.assertIn("&lt;img", body)

    def test_confirmation_preserves_response_counts(self):
        subject, body = self.render("Confirmation", confirmed=2, waitlisted=1)
        self.assertIn("Confirmation", subject)
        self.assertIn("<strong>Attending</strong>", body)
        self.assertIn("Confirmed places across functions: 2", body)
        self.assertIn("Waitlisted places: 1", body)
        self.assertNotIn("Please confirm your attendance by", body)

    def test_custom_confirmation_email_subject(self):
        self.event.confirmation_email_subject = "  Your anniversary pass\r\nTCC & Guests  "
        subject, body = self.render("Confirmation")
        self.assertEqual(subject, "Your anniversary pass TCC & Guests")
        self.assertIn("<title>Your anniversary pass TCC &amp; Guests</title>", body)
        self.assertEqual(self.render("Invitation")[0], "Your Invitation | Installation & Dinner")
        self.assertEqual(self.render("Reminder")[0], "RSVP Reminder | Installation & Dinner")

        self.event.confirmation_email_subject = " "
        self.assertEqual(self.render("Confirmation")[0], "Your RSVP Confirmation | Installation & Dinner")

    def test_reminder_and_optional_details(self):
        self.event.host_name = None
        self.event.description = None
        subject, body = self.render("Reminder")
        self.assertIn("RSVP Reminder", subject)
        self.assertIn("A kind reminder", body)
        self.assertNotIn("None", body)

    def test_multiday_event_shows_end_date(self):
        self.event.ends_on = "2026-11-21 18:00:00"
        _, body = self.render()
        self.assertIn("Friday, 20 November 2026 – Saturday, 21 November 2026", body)

    def test_personal_message_and_footer_replace_generic_copy(self):
        self.event.description = "<p>My personal invitation.</p><p>Join us for dinner.</p>"
        self.event.host_name = "Example Organiser"
        self.event.footer_text = "<p>Brotherly Love, Truth and Relief,</p><p>Example Organiser</p>"
        _, body = self.render()
        self.assertEqual(body.count("My personal invitation."), 1)
        self.assertEqual(body.count("Example Organiser"), 1)
        self.assertNotIn("You are cordially invited", body)
        self.assertNotIn("With kind regards", body)
        self.assertLess(body.index("Brotherly Love"), body.index("personal to you"))

    def test_fallback_for_empty_editor_fields(self):
        self.event.description = "<p><br></p>"
        self.event.footer_text = "<p><br></p>"
        _, body = self.render()
        self.assertIn("You are cordially invited", body)
        self.assertIn("With kind regards", body)

    def test_centred_email_layout_and_emblem(self):
        _, body = self.render(banner_url="https://events.example.com/files/logo.png")
        self.assertIn('align="center"', body)
        self.assertIn("max-width:600px", body)
        self.assertIn('src="https://events.example.com/files/logo.png"', body)
        self.assertIn('width="96"', body)

    def test_unsafe_emblem_url_is_omitted(self):
        _, body = self.render(banner_url="javascript:alert(1)")
        self.assertNotIn("<img", body)
