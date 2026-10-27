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
    event_name = frappe.db.get_value("RSVP Invitation", name, "event")
    lock_event(event_name)
    invitation = current_doc("RSVP Invitation", name)
    event = current_doc("RSVP Event", invitation.event)
    if (
        invitation.revoked
        or invitation.token_hash != digest(token)
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


def current_rows(doctype, filters=None, fields=None, order_by=None, pluck=None):
    """Locking reads see committed rows after waiting, including under REPEATABLE READ.

    The caller must hold the event lock; do not use a snapshot count for allocation.
    """
    rows = frappe.qb.get_query(
        table=doctype,
        filters=filters,
        fields=fields or [pluck or "name"],
        order_by=order_by,
        for_update=True,
        ignore_permissions=True,
    ).run(as_dict=True)
    return [row[pluck] for row in rows] if pluck else rows


def current_count(doctype, filters):
    return len(current_rows(doctype, filters=filters))


def current_value(doctype, filters, fieldname="name"):
    return frappe.db.get_value(doctype, filters, fieldname, for_update=True)


def current_doc(*args):
    if len(args) == 1 and isinstance(args[0], dict):
        return frappe.get_doc(args[0])
    return frappe.get_doc(*args, for_update=True)
