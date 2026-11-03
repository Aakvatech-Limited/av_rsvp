from frappe import _


def get_data():
    return {
        "fieldname": "guest",
        "transactions": [
            {"label": _("Invitations"), "items": ["RSVP Invitation"]},
        ],
    }
