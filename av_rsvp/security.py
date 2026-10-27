import hashlib
import hmac
import secrets
from contextlib import contextmanager

import frappe
from frappe.utils import get_datetime

from av_rsvp.domain import event_now


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def new_nonce():
    return secrets.token_urlsafe(32)


def token_for(nonce, purpose):
    key = frappe.conf.get("encryption_key")
    if not key:
        frappe.throw("Site encryption_key is required before issuing invitations.")
    return hmac.new(key.encode(), f"av_rsvp:{purpose}:{nonce}".encode(), hashlib.sha256).hexdigest()


def invitation_url(invitation):
    from frappe.utils import get_url

    return get_url("/rsvp") + "#" + token_for(invitation.access_nonce, "invitation")


def check_token(token):
    if not isinstance(token, str) or len(token) != 64:
        invalid_token()
    name = frappe.db.get_value("RSVP Invitation", {"token_hash": digest(token)})
    if not name:
        invalid_token()
    invitation = frappe.get_doc("RSVP Invitation", name)
    event = frappe.get_doc("RSVP Event", invitation.event)
    if (
        invitation.revoked
        or not invitation.token_expires_on
        or get_datetime(invitation.token_expires_on) < event_now(event.timezone)
    ):
        invalid_token()
    if event.status in {"Draft", "Cancelled"}:
        invalid_token()
    return invitation, event


def invalid_token():
    frappe.throw(
        "This invitation is unavailable or has expired. Contact the organiser.", frappe.PermissionError
    )


def lock_event(event):
    table = frappe.qb.DocType("RSVP Event")
    if not frappe.qb.from_(table).select(table.name).where(table.name == event).for_update().run():
        frappe.throw("Event not found.", frappe.DoesNotExistError)


@contextmanager
def service_write():
    previous = frappe.flags.av_rsvp_service
    frappe.flags.av_rsvp_service = True
    try:
        yield
    finally:
        frappe.flags.av_rsvp_service = previous


def require_service():
    if not frappe.flags.av_rsvp_service:
        frappe.throw("Use the RSVP actions to update this record.", frappe.PermissionError)
