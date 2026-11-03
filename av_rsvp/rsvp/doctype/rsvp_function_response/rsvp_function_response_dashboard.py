from frappe import _


def get_data():
    return {
        "fieldname": "response",
        "transactions": [
            {"label": _("Entry"), "items": ["RSVP Check-in"]},
        ],
    }
