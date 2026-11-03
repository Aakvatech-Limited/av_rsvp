"""Author controls and publication rules for event reviews."""

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from av_rsvp.permissions import access_level, is_admin, is_event_host, require_event
from av_rsvp.post_event import ASSESSMENT, HOST_FEEDBACK, RATINGS

READ_TYPES = {"read", "select", "print", "email", "export", "report"}


def document_access(doc, user=None, ptype=None):
    user = user or frappe.session.user
    if user == "Guest":
        return False
    organizer = access_level(doc.event, user) >= 2
    host = is_event_host(doc.event, user)
    if doc.doctype == HOST_FEEDBACK:
        if ptype in READ_TYPES or ptype is None:
            return organizer or (host and doc.host_user == user)
        return host and (doc.is_new() or doc.host_user == user) and ptype in {"create", "write", "submit"}
    if ptype in READ_TYPES or ptype is None:
        return organizer or (host and doc.docstatus == 1 and bool(doc.published))
    return organizer and ptype in {"create", "write", "submit"}


def query_for(doctype, user=None):
    from av_rsvp.permissions import query_for as organizer_query

    user = user or frappe.session.user
    if is_admin(user):
        return ""
    organizer = organizer_query(doctype, user, 2)
    if "Event Host" not in frappe.get_roles(user):
        return organizer
    escaped = frappe.db.escape(user)
    host_events = f"`tab{doctype}`.event IN (SELECT parent FROM `tabRSVP Event Team` WHERE parenttype='RSVP Event' AND user={escaped} AND access_level='Event Host')"
    restriction = (
        f"`tab{doctype}`.host_user={escaped}"
        if doctype == HOST_FEEDBACK
        else f"`tab{doctype}`.docstatus=1 AND `tab{doctype}`.published=1"
    )
    return f"(({organizer}) OR ({host_events} AND {restriction}))"


def host_query(user=None):
    return query_for(HOST_FEEDBACK, user)


def assessment_query(user=None):
    return query_for(ASSESSMENT, user)


class EventReview(Document):
    author_field = None
    date_field = None

    def validate(self):
        old = self.get_doc_before_save()
        if old and (old.event != self.event or old.get(self.author_field) != self.get(self.author_field)):
            frappe.throw("Event and review author cannot be changed.")
        if self.is_new():
            self.set(self.author_field, frappe.session.user)
            self.set(self.date_field, now_datetime())
        elif old and old.get(self.date_field) != self.get(self.date_field):
            frappe.throw("The review date cannot be changed.")
        event = frappe.get_doc("RSVP Event", self.event)
        if event.status == "Cancelled" or get_datetime(event.ends_on) > now_datetime():
            frappe.throw("Reviews are available after the event has ended.")
        if self.doctype == HOST_FEEDBACK:
            if self.host_user != frappe.session.user or not is_event_host(self.event):
                frappe.throw("Only the assigned host can write their feedback.", frappe.PermissionError)
            # One review per host/event, enforced by a database unique key.
            from av_rsvp.security import digest

            self.review_key = digest(f"{self.event}:{self.host_user}")
            for key in RATINGS:
                if self.get(key) not in ("1", "2", "3", "4", "5"):
                    frappe.throw("Choose a rating between 1 and 5.")
        else:
            require_event(self.event, 2)
            if self.published and (self.docstatus != 1 or not old or old.docstatus != 1):
                frappe.throw("Submit the assessment before publishing it.")

    def before_cancel(self):
        frappe.throw("Submitted reviews cannot be cancelled. Record corrections through your organizer.")

    def on_trash(self):
        frappe.throw("Reviews retain their audit history and cannot be deleted.")

    def before_update_after_submit(self):
        if self.doctype != ASSESSMENT:
            frappe.throw("Submitted host feedback cannot be edited.", frappe.PermissionError)
        require_event(self.event, 2)
