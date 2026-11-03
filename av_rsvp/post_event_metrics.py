"""Pure attendance calculations shared by post-event reporting and tests."""


def attendance_summary(responses, checkins):
    """Use sets: people once per event, places once per function; reversals excluded."""
    confirmed = {(r.event, r.attendee) for r in responses if r.allocation == "Confirmed"}
    checked = {(r.event, r.attendee) for r in checkins if r.status == "Checked In"}
    confirmed_places = {(r.event, r.function, r.attendee) for r in responses if r.allocation == "Confirmed"}
    checked_places = {(r.event, r.function, r.attendee) for r in checkins if r.status == "Checked In"}
    return {
        "confirmed_people": len(confirmed),
        "attended_people": len(checked),
        "no_shows": len(confirmed - checked),
        "attendance_rate": round(100 * len(confirmed & checked) / len(confirmed), 1) if confirmed else None,
        "confirmed_places": len(confirmed_places),
        "attended_places": len(checked_places),
        "no_show_places": len(confirmed_places - checked_places),
    }
