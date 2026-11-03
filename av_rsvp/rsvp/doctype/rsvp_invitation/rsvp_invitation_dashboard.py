from frappe import _


def get_data():
    return {
        "fieldname": "invitation",
        "transactions": [
            {"label": _("Attendees"), "items": ["RSVP Attendee", "RSVP Function Response"]},
            {"label": _("Communication"), "items": ["RSVP Message Log"]},
        ],
    }
