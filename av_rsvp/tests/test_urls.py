"""URL regressions; no database or outgoing mail required."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from av_rsvp.event_pages import published_page_url, registration_url
from av_rsvp.security import invitation_url, token_for
from av_rsvp.urls import public_url


class TestPublicURLs(unittest.TestCase):
    def setUp(self):
        self.config = patch.object(
            frappe.local,
            "conf",
            frappe._dict(
                host_name="https://events.example.com",
                developer_mode=1,
                webserver_port=8001,
                encryption_key="test-key",
            ),
            create=True,
        )
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_public_host_does_not_inherit_internal_port(self):
        frappe.conf.http_port = 8001
        self.assertEqual(public_url("/rsvp"), "https://events.example.com/rsvp")

    def test_explicit_public_port_is_preserved(self):
        frappe.conf.host_name = "https://events.example.com:8443"
        self.assertEqual(public_url("/rsvp"), "https://events.example.com:8443/rsvp")

    def test_missing_host_uses_frappe_fallback(self):
        frappe.conf.host_name = None
        with patch("av_rsvp.urls.get_url", return_value="http://localhost:8001/rsvp") as fallback:
            self.assertEqual(public_url("/rsvp"), "http://localhost:8001/rsvp")
        fallback.assert_called_once_with("/rsvp")

    def test_registration_link_encodes_event(self):
        event = SimpleNamespace(event_web_page=None, name="Dinner & Reception")
        self.assertEqual(
            registration_url(event),
            "https://events.example.com/rsvp?event=Dinner+%26+Reception",
        )

    def test_published_page_uses_public_host(self):
        event = SimpleNamespace(event_web_page="event-page")
        page = SimpleNamespace(route="events/dinner", published=1)
        with patch.object(frappe.local, "db", Mock(), create=True) as db:
            db.get_value.return_value = page
            self.assertEqual(published_page_url(event), "https://events.example.com/events/dinner")

    def test_invitation_token_is_preserved(self):
        event = SimpleNamespace(event_web_page=None)
        invitation = SimpleNamespace(event="EVT-1", access_nonce="test-nonce")
        with patch("av_rsvp.security.current_doc", return_value=event):
            self.assertEqual(
                invitation_url(invitation),
                "https://events.example.com/rsvp#" + token_for("test-nonce", "invitation"),
            )
