from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, cint, get_datetime

from av_rsvp.permissions import require_event
from av_rsvp.security import digest, lock_event, new_nonce, require_service, service_write, token_for


class RSVPEventTeamBase(Document):
    pass


class RSVPSettingsBase(Document):
    def validate(self):
        if cint(self.reminder_days) < 1 or cint(self.retention_days) < 1:
            frappe.throw("Reminder and retention days must be positive.")


class RSVPEventBase(Document):
    def validate(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            frappe.throw("Enter a valid IANA timezone, for example Africa/Dar_es_Salaam.")
        if get_datetime(self.ends_on) <= get_datetime(self.starts_on):
            frappe.throw("Event end must follow its start.")
        if get_datetime(self.rsvp_deadline) > get_datetime(self.ends_on):
            frappe.throw("The RSVP deadline must not follow the event end.")
        if self.map_url and not self.map_url.startswith("https://"):
            frappe.throw("The map link must use HTTPS.")
        if len({row.user for row in self.team}) != len(self.team):
            frappe.throw("Assign each team member only once.")
        if not self.is_new():
            require_event(self.name, 3)
            lock_event(self.name)
            old = self.get_doc_before_save()
            if old and old.timezone != self.timezone:
                frappe.throw("The timezone cannot be changed after creation. Create a new event if needed.")
            if old and old.multiple_functions and not self.multiple_functions:
                if frappe.db.count("RSVP Function", {"event": self.name}) > 1:
                    frappe.throw("Multiple functions cannot be disabled while several functions exist.")
            if old and not old.multiple_functions:
                default = frappe.db.get_value("RSVP Function", {"event": self.name}, "name")
                if default and not frappe.db.exists("RSVP Function Response", {"event": self.name}):
                    frappe.db.set_value(
                        "RSVP Function",
                        default,
                        {
                            "function_title": self.event_title,
                            "starts_on": self.starts_on,
                            "ends_on": self.ends_on,
                            "venue": self.venue,
                        },
                    )

    def after_insert(self):
        if not self.multiple_functions:
            with service_write():
                frappe.get_doc(
                    dict(
                        doctype="RSVP Function",
                        event=self.name,
                        function_title=self.event_title,
                        starts_on=self.starts_on,
                        ends_on=self.ends_on,
                        venue=self.venue,
                    )
                ).insert(ignore_permissions=True)

    def on_trash(self):
        if frappe.db.exists("RSVP Invitation", {"event": self.name}):
            frappe.throw("Events with invitations must be cancelled, not deleted.")


class RSVPFunctionBase(Document):
    def validate(self):
        require_event(self.event, 3) if not frappe.flags.av_rsvp_service else None
        lock_event(self.event)
        event = frappe.get_doc("RSVP Event", self.event)
        if not self.is_new() and self.has_value_changed("event"):
            frappe.throw("A function cannot be moved to another event.")
        if (
            self.is_new()
            and not event.multiple_functions
            and frappe.db.exists("RSVP Function", {"event": self.event})
        ):
            frappe.throw("Enable Multiple Functions before adding another function.")
        if get_datetime(self.ends_on) <= get_datetime(self.starts_on):
            frappe.throw("Function end must follow its start.")
        if get_datetime(self.starts_on) < get_datetime(event.starts_on) or get_datetime(
            self.ends_on
        ) > get_datetime(event.ends_on):
            frappe.throw("The function must fall within the event dates.")
        if cint(self.capacity) < 0:
            frappe.throw("Capacity cannot be negative.")
        confirmed = (
            frappe.db.count("RSVP Function Response", {"function": self.name, "allocation": "Confirmed"})
            if not self.is_new()
            else 0
        )
        if self.capacity and cint(self.capacity) < confirmed:
            frappe.throw("Capacity cannot be lower than the number already confirmed.")
        if not self.enabled and (
            confirmed
            or (
                not self.is_new()
                and frappe.db.exists(
                    "RSVP Function Response", {"function": self.name, "allocation": "Waitlisted"}
                )
            )
        ):
            frappe.throw("Cancel confirmed and waitlisted responses before disabling this function.")

    def on_trash(self):
        lock_event(self.event)
        if frappe.db.exists("RSVP Function Response", {"function": self.name}):
            frappe.throw("Functions with responses cannot be deleted.")


class RSVPGuestBase(Document):
    pass


class RSVPInvitationBase(Document):
    def validate(self):
        if not frappe.flags.av_rsvp_service:
            require_event(self.event, 2)
        lock_event(self.event)
        if not 1 <= cint(self.max_attendees) <= 100:
            frappe.throw("An invitation must allow between 1 and 100 people.")
        if self.is_new():
            self.invite_key = digest(f"{self.event}:{self.guest}")
            self.access_nonce = new_nonce()
            self.token_hash = digest(token_for(self.access_nonce, "invitation"))
            event = frappe.get_doc("RSVP Event", self.event)
            self.token_expires_on = add_days(get_datetime(event.ends_on), 7)
            self.response_status = "Pending"
            self.delivery_status = "Not Sent"
            self.revoked = 0
        elif not frappe.flags.av_rsvp_service:
            old = self.get_doc_before_save()
            protected = [
                "event",
                "guest",
                "access_nonce",
                "token_hash",
                "token_expires_on",
                "invite_key",
                "response_status",
                "delivery_status",
                "responded_on",
                "response_by",
                "last_reminded_on",
                "revoked",
                "notes",
            ]
            if old and any(self.get(key) != old.get(key) for key in protected):
                frappe.throw("Use RSVP actions to change responses or invitation access.")
            count = frappe.db.count("RSVP Attendee", {"invitation": self.name, "active": 1})
            if cint(self.max_attendees) < count:
                frappe.throw("The allowance cannot be lower than the active attendee count.")

    def on_trash(self):
        frappe.throw("Revoke invitations instead of deleting their audit history.")


class OperationalDocument(Document):
    def validate(self):
        require_service()

    def on_trash(self):
        require_service()


class RSVPAttendeeBase(OperationalDocument):
    def validate(self):
        super().validate()
        if self.is_new():
            self.entry_nonce = new_nonce()
            self.entry_hash = digest(token_for(self.entry_nonce, "entry"))


class RSVPFunctionResponseBase(OperationalDocument):
    def validate(self):
        super().validate()
        self.response_key = digest(f"{self.attendee}:{self.function}")
        attendee_event = frappe.db.get_value("RSVP Attendee", self.attendee, "event")
        function_event = frappe.db.get_value("RSVP Function", self.function, "event")
        if attendee_event != self.event or function_event != self.event:
            frappe.throw("Attendee and function must belong to the same event.")


class RSVPCheckInBase(OperationalDocument):
    pass


class RSVPMessageLogBase(OperationalDocument):
    pass
