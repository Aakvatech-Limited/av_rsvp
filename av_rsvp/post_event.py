"""Post-event analytics reuse existing responses and active check-ins."""

from collections import Counter

import frappe
from frappe.utils import getdate

from av_rsvp.permissions import access_level, is_admin, is_event_host, require_overview
from av_rsvp.post_event_metrics import attendance_summary

HOST_FEEDBACK = "RSVP Event Host Feedback"
ASSESSMENT = "RSVP Event Organizer Assessment"
RATINGS = ("overall_satisfaction", "planning_rating", "execution_rating")


def can_view(event, user=None):
    return access_level(event, user) >= 2 or is_event_host(event, user)


def eligible_events(from_date=None, to_date=None):
    if not (
        is_admin()
        or set(frappe.get_roles()).intersection({"Event Host", "Event Manager", "Event Coordinator"})
    ):
        frappe.throw("Post-event dashboard access required.", frappe.PermissionError)
    filters = {}
    if from_date:
        filters["starts_on"] = [">=", str(getdate(from_date)) + " 00:00:00"]
    if to_date:
        if from_date and getdate(from_date) > getdate(to_date):
            frappe.throw("From date must not follow To date.")
        filters["ends_on"] = ["<=", str(getdate(to_date)) + " 23:59:59"]
    # Explicit event checks include hosts without granting them Event document access.
    return [
        row
        for row in frappe.get_all(
            "RSVP Event",
            filters=filters,
            fields=["name", "event_title", "status", "starts_on", "ends_on"],
            order_by="starts_on desc",
        )
        if can_view(row.name)
    ]


@frappe.whitelist(methods=["POST"])
def dashboard(event=None, from_date=None, to_date=None):
    from av_rsvp.api import private_response

    private_response()
    events = eligible_events(from_date, to_date)
    if event:
        require_overview(event)
        events = [row for row in events if row.name == event]
    names = [row.name for row in events]
    base = {
        "events": events,
        "selected_event": event or "",
        "totals": attendance_summary([], []),
        "responses": {},
        "functions": [],
        "arrivals": [],
        "no_shows": [],
        "host_feedback": [],
        "assessments": [],
        "can_assess": False,
        "can_give_feedback": False,
    }
    if not names:
        return base
    filters = {"event": ["in", names]}
    invitations = frappe.get_all(
        "RSVP Invitation", filters={**filters, "revoked": 0}, fields=["response_status", "max_attendees"]
    )
    responses = frappe.get_all(
        "RSVP Function Response", filters=filters, fields=["event", "function", "attendee", "allocation"]
    )
    checks = frappe.get_all(
        "RSVP Check-in",
        filters={**filters, "status": "Checked In"},
        fields=["event", "function", "attendee", "status", "checked_in_on"],
    )
    base["totals"] = attendance_summary(responses, checks)
    base["totals"].update(
        invitations=len(invitations), invited_allowance=sum(int(r.max_attendees or 0) for r in invitations)
    )
    base["responses"] = dict(Counter(r.response_status for r in invitations))
    base["provisional"] = any(row.status != "Completed" for row in events)
    for function in frappe.get_all(
        "RSVP Function", filters=filters, fields=["name", "event", "function_title", "capacity"]
    ):
        summary = attendance_summary(
            [r for r in responses if r.function == function.name],
            [r for r in checks if r.function == function.name],
        )
        base["functions"].append({**dict(function), **summary})
    # No contact details, dietary needs, entry tokens or invitation links in host analytics.
    checked = {(r.event, r.attendee) for r in checks}
    missing = {(r.event, r.attendee) for r in responses if r.allocation == "Confirmed"} - checked
    if missing:
        attendees = frappe.get_all(
            "RSVP Attendee",
            filters={**filters, "name": ["in", list({a for _, a in missing})]},
            fields=["name", "event", "attendee_name"],
        )
        base["no_shows"] = [dict(r) for r in attendees if (r.event, r.name) in missing]
    arrivals = Counter(str(r.checked_in_on)[:13] + ":00" for r in checks if r.checked_in_on)
    base["arrivals"] = [{"hour": hour, "places": count} for hour, count in sorted(arrivals.items())]
    # get_list enforces author/published visibility independently of event authorization.
    base["host_feedback"] = frappe.get_list(
        HOST_FEEDBACK,
        filters={**filters, "docstatus": 1},
        fields=[
            "name",
            "event",
            "host_user",
            "feedback_date",
            *RATINGS,
            "expectations_met",
            "what_worked_well",
            "improvements_needed",
            "comments",
        ],
        limit_page_length=0,
    )
    base["assessments"] = frappe.get_list(
        ASSESSMENT,
        filters={**filters, "docstatus": 1, "published": 1},
        fields=[
            "name",
            "event",
            "assessed_by",
            "assessment_date",
            "objectives_achieved",
            "planning_assessment",
            "execution_assessment",
            "issues_encountered",
            "successes",
            "lessons_learned",
            "recommendations",
        ],
        limit_page_length=0,
    )
    scores = [int(r.overall_satisfaction) for r in base["host_feedback"] if r.overall_satisfaction]
    base["totals"]["host_satisfaction"] = round(sum(scores) / len(scores), 1) if scores else None
    base["can_assess"] = bool(event and access_level(event) >= 2)
    base["can_give_feedback"] = bool(event and is_event_host(event))
    base["own_feedback"] = None
    if base["can_give_feedback"]:
        own = frappe.get_list(
            HOST_FEEDBACK,
            filters={"event": event, "host_user": frappe.session.user, "docstatus": ["<", 2]},
            pluck="name",
            limit_page_length=1,
        )
        base["own_feedback"] = own[0] if own else None
    return base


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def event_link_query(doctype, txt, searchfield, start, page_len, filters):
    rows = eligible_events()
    return [(r.name, r.event_title) for r in rows if txt.lower() in (r.name + " " + r.event_title).lower()][
        int(start) : int(start) + min(int(page_len), 100)
    ]
