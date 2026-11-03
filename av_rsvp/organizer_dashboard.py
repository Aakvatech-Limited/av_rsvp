"""Permission-scoped organizer analytics for the RSVP landing page."""

import frappe

from av_rsvp.permissions import access_level, is_admin


def _eligible_events():
    roles = set(frappe.get_roles())
    if not (is_admin() or roles.intersection({"Event Manager", "Event Coordinator"})):
        frappe.throw("Organizer access required.", frappe.PermissionError)
    # get_list applies the RSVP Event permission-query condition.
    return frappe.get_list(
        "RSVP Event",
        fields=["name", "event_title", "status", "starts_on"],
        order_by="starts_on desc",
        limit_page_length=500,
    )


@frappe.whitelist(methods=["POST"])
def organizer_dashboard(event=None):
    events = _eligible_events()
    names = {row.name for row in events if access_level(row.name) >= 2}
    events = [row for row in events if row.name in names]
    if event:
        if event not in names:
            frappe.throw("You do not have access to this event.", frappe.PermissionError)
        selected = [event]
    else:
        selected = [row.name for row in events]
    totals = {
        key: 0
        for key in (
            "invitations",
            "pending",
            "attending",
            "declined",
            "maybe",
            "confirmed_people",
            "confirmed_places",
            "waitlisted_places",
            "checked_in_people",
            "capacity",
        )
    }
    functions = []
    if selected:
        invitations = frappe.get_all(
            "RSVP Invitation",
            filters={"event": ["in", selected], "revoked": 0},
            fields=["event", "response_status"],
        )
        totals["invitations"] = len(invitations)
        for row in invitations:
            status = (row.response_status or "").lower()
            if status in ("pending", "attending", "declined", "maybe"):
                totals[status] += 1
        response_rows = frappe.get_all(
            "RSVP Function Response",
            filters={"event": ["in", selected], "allocation": ["in", ["Confirmed", "Waitlisted"]]},
            fields=["event", "function", "attendee", "allocation"],
        )
        totals["confirmed_places"] = sum(row.allocation == "Confirmed" for row in response_rows)
        totals["waitlisted_places"] = sum(row.allocation == "Waitlisted" for row in response_rows)
        totals["confirmed_people"] = len(
            {(row.event, row.attendee) for row in response_rows if row.allocation == "Confirmed"}
        )
        checked = frappe.get_all(
            "RSVP Check-in",
            filters={"event": ["in", selected], "status": "Checked In"},
            fields=["event", "function", "attendee"],
        )
        totals["checked_in_people"] = len({(row.event, row.attendee) for row in checked})
        confirmed_counts = {}
        waiting_counts = {}
        checkin_counts = {}
        for row in response_rows:
            target = confirmed_counts if row.allocation == "Confirmed" else waiting_counts
            target[row.function] = target.get(row.function, 0) + 1
        for row in checked:
            checkin_counts[row.function] = checkin_counts.get(row.function, 0) + 1
        for row in frappe.get_all(
            "RSVP Function",
            filters={"event": ["in", selected], "enabled": 1},
            fields=["name", "event", "function_title", "capacity"],
            order_by="starts_on asc",
        ):
            capacity = int(row.capacity or 0)
            if capacity:
                totals["capacity"] += capacity
            functions.append(
                {
                    "name": row.name,
                    "event": row.event,
                    "title": row.function_title,
                    "capacity": capacity,
                    "confirmed": confirmed_counts.get(row.name, 0),
                    "waitlisted": waiting_counts.get(row.name, 0),
                    "checked_in": checkin_counts.get(row.name, 0),
                }
            )
    return {"events": events, "selected_event": event or "", "totals": totals, "functions": functions}
