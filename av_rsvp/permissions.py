import frappe

ADMIN_ROLES = {"System Manager", "RSVP Administrator"}
LEVELS = {"Event Manager": 3, "Event Coordinator": 2, "Check-in Operator": 1}


def is_admin(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or bool(ADMIN_ROLES.intersection(frappe.get_roles(user)))


def app_access():
    return bool(set(frappe.get_roles()).intersection(ADMIN_ROLES | set(LEVELS)))


def access_level(event, user=None):
    user = user or frappe.session.user
    if user == "Guest":
        return 0
    if is_admin(user):
        return 4
    roles = set(frappe.get_roles(user))
    if "Event Manager" in roles and frappe.db.get_value("RSVP Event", event, "owner") == user:
        return 3
    assignments = frappe.get_all(
        "RSVP Event Team",
        filters={"parent": event, "parenttype": "RSVP Event", "user": user},
        pluck="access_level",
    )
    return max([LEVELS.get(role, 0) for role in assignments if role in roles] or [0])


def require_event(event, minimum=2):
    if access_level(event) < minimum:
        frappe.throw("You do not have access to this event.", frappe.PermissionError)


def document_access(doc, user=None, ptype=None):
    user = user or frappe.session.user
    if user == "Guest":
        return False
    if is_admin(user):
        return True
    if doc.doctype == "RSVP Event" and doc.is_new():
        return "Event Manager" in frappe.get_roles(user)
    event = doc.name if doc.doctype == "RSVP Event" else doc.get("event")
    minimum = 1 if doc.doctype in {"RSVP Function", "RSVP Check-in", "RSVP Event"} else 2
    if ptype in {"write", "create", "delete"}:
        minimum = 3 if doc.doctype in {"RSVP Event", "RSVP Function"} else 2
    return access_level(event, user) >= minimum


def query_for(doctype, user=None, minimum=1):
    user = user or frappe.session.user
    if is_admin(user):
        return ""
    roles = set(frappe.get_roles(user))
    levels = [role for role, level in LEVELS.items() if level >= minimum and role in roles]
    if not levels:
        return "1=0"
    escaped = frappe.db.escape(user)
    owner = f" OR e.owner={escaped}" if "Event Manager" in roles else ""
    role_sql = ",".join(frappe.db.escape(role) for role in levels)
    key = "name" if doctype == "RSVP Event" else "event"
    return f"""`tab{doctype}`.`{key}` IN (
        SELECT e.name FROM `tabRSVP Event` e WHERE
        EXISTS (SELECT 1 FROM `tabRSVP Event Team` t WHERE t.parent=e.name
        AND t.parenttype='RSVP Event' AND t.user={escaped} AND t.access_level IN ({role_sql})){owner})"""


def event_query(user=None):
    return query_for("RSVP Event", user)


def function_query(user=None):
    return query_for("RSVP Function", user)


def invitation_query(user=None):
    return query_for("RSVP Invitation", user, 2)


def attendee_query(user=None):
    return query_for("RSVP Attendee", user, 2)


def response_query(user=None):
    return query_for("RSVP Function Response", user, 2)


def checkin_query(user=None):
    return query_for("RSVP Check-in", user)


def message_query(user=None):
    return query_for("RSVP Message Log", user, 2)
