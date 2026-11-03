"""Standard editable Web Pages for individual RSVP events."""

from html import escape
from urllib.parse import urlencode

import frappe
from frappe.utils import get_url

from av_rsvp.permissions import require_event
from av_rsvp.security import current_doc, lock_event, service_write


def published_page_url(event):
    if event.event_web_page:
        page = frappe.db.get_value("Web Page", event.event_web_page, ["route", "published"], as_dict=True)
        if page and page.published and page.route:
            return get_url("/" + page.route.lstrip("/"))
    return None


def registration_url(event):
    return published_page_url(event) or get_url("/rsvp") + "?" + urlencode({"event": event.name})


def create_page(event_name):
    require_event(event_name, 3)
    lock_event(event_name)
    event = current_doc("RSVP Event", event_name)
    if event.event_web_page:
        page = frappe.get_doc("Web Page", event.event_web_page)
        page.check_permission("read")
        return dict(name=page.name, route=page.route)
    if not frappe.has_permission("Web Page", "create"):
        frappe.throw(
            "Website Manager access is required to create an event Web Page.", frappe.PermissionError
        )
    page = frappe.get_doc(
        dict(
            doctype="Web Page",
            name="av-rsvp-" + frappe.scrub(event.name),
            title=event.event_title,
            route="events/" + frappe.scrub(event.name).replace("_", "-"),
            content_type="HTML",
            published=0,
            dynamic_template=0,
            main_section_html=frappe.read_file(
                frappe.get_app_path("av_rsvp", "templates", "event_web_page.html")
            ).replace("__EVENT_ID__", escape(event.name, quote=True)),
            javascript=frappe.read_file(frappe.get_app_path("av_rsvp", "www", "rsvp.js")),
            insert_style=1,
            css=frappe.read_file(frappe.get_app_path("av_rsvp", "www", "rsvp.css")),
            full_width=1,
            show_title=0,
            enable_comments=0,
        )
    ).insert(set_name="av-rsvp-" + frappe.scrub(event.name))
    # Never overwrite existing page HTML/CSS/JS when the event is saved or this
    # action is repeated. Website edits use normal Web Page permissions/history.
    with service_write():
        event.event_web_page = page.name
        event.save(ignore_permissions=True)
    return dict(name=page.name, route=page.route)
