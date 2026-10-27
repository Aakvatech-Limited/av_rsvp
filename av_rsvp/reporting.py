from collections import Counter

import frappe

from av_rsvp.permissions import require_event


def col(label, fieldname, fieldtype="Data", options=None, width=160):
    return dict(label=label, fieldname=fieldname, fieldtype=fieldtype, options=options, width=width)


def execute_report(kind, filters):
    event = filters.get("event")
    if not event:
        frappe.throw("Select an event.")
    require_event(event, 1 if kind == "checkins" else 2)
    if kind == "guests":
        columns = [
            col("Invitation", "name", "Link", "RSVP Invitation"),
            col("Guest", "guest_name"),
            col("Email", "email"),
            col("Phone", "phone"),
            col("Allowance", "max_attendees", "Int"),
            col("Response", "response_status"),
            col("Revoked", "revoked", "Check"),
        ]
        return columns, frappe.get_all(
            "RSVP Invitation",
            filters={"event": event},
            fields=["name", "guest_name", "email", "phone", "max_attendees", "response_status", "revoked"],
            order_by="guest_name",
        )
    if kind == "checkins":
        columns = [
            col("Function", "function", "Link", "RSVP Function"),
            col("Attendee", "attendee", "Link", "RSVP Attendee"),
            col("Status", "status"),
            col("Checked in on", "checked_in_on", "Datetime"),
            col("Checked in by", "checked_in_by", "Link", "User"),
            col("Reversed on", "reversed_on", "Datetime"),
            col("Reversal reason", "reversal_reason"),
        ]
        return columns, frappe.get_all(
            "RSVP Check-in",
            filters={"event": event},
            fields=[c["fieldname"] for c in columns],
            order_by="checked_in_on desc",
        )
    columns = [
        col("Function", "function", "Link", "RSVP Function"),
        col("Meal", "meal_choice"),
        col("Age group", "age_group"),
        col("Dietary requirements", "dietary_requirements", width=240),
        col("People", "people", "Int"),
    ]
    attendees = {
        a.name: a
        for a in frappe.get_all(
            "RSVP Attendee",
            filters={"event": event, "active": 1},
            fields=["name", "age_group", "dietary_requirements"],
        )
    }
    totals = Counter()
    for row in frappe.get_all(
        "RSVP Function Response",
        filters={"event": event, "allocation": "Confirmed"},
        fields=["function", "attendee", "meal_choice"],
    ):
        person = attendees.get(row.attendee)
        if person:
            totals[
                (
                    row.function,
                    row.meal_choice or "Unspecified",
                    person.age_group,
                    person.dietary_requirements or "None specified",
                )
            ] += 1
    return columns, [
        dict(function=key[0], meal_choice=key[1], age_group=key[2], dietary_requirements=key[3], people=value)
        for key, value in sorted(totals.items())
    ]
