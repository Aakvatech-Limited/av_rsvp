from frappe import _


def get_data():
    return {
        "fieldname": "attendee",
        "transactions": [
            {"label": _("Attendance"), "items": ["RSVP Function Response", "RSVP Check-in"]},
        ],
    }
