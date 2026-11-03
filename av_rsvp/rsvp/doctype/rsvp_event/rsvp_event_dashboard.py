from frappe import _


def get_data():
    return {
        "fieldname": "event",
        "transactions": [
            {
                "label": _("Post-Event"),
                "items": ["RSVP Event Host Feedback", "RSVP Event Organizer Assessment"],
            },
            {"label": _("Programme"), "items": ["RSVP Function"]},
            {"label": _("Invitations & Guests"), "items": ["RSVP Invitation", "RSVP Attendee"]},
            {"label": _("Attendance"), "items": ["RSVP Function Response", "RSVP Check-in"]},
            {"label": _("Communication"), "items": ["RSVP Message Log"]},
        ],
    }
