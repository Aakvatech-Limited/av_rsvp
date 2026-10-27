app_name = "av_rsvp"
app_title = "AV RSVP"
app_publisher = "Aakvatech Limited"
app_description = "Invitations, guest responses and event attendance"
app_email = "info@aakvatech.com"
app_license = "MIT"
app_logo_url = "/assets/av_rsvp/images/logo.svg"
required_apps = ["frappe"]
fixtures = [
    {
        "dt": "Role",
        "filters": [
            ["name", "in", ["RSVP Administrator", "Event Manager", "Event Coordinator", "Check-in Operator"]]
        ],
    }
]
after_install = "av_rsvp.install.after_install"
add_to_apps_screen = [
    {
        "name": "av_rsvp",
        "logo": app_logo_url,
        "title": "AV RSVP",
        "route": "/app/rsvp",
        "has_permission": "av_rsvp.permissions.app_access",
    }
]
scheduler_events = {
    "daily": ["av_rsvp.messaging.send_due_reminders"],
    "hourly": ["av_rsvp.messaging.sync_delivery_status"],
}
permission_query_conditions = {
    "RSVP Event": "av_rsvp.permissions.event_query",
    **{
        dt: "av_rsvp.permissions." + fn
        for dt, fn in {
            "RSVP Function": "function_query",
            "RSVP Invitation": "invitation_query",
            "RSVP Attendee": "attendee_query",
            "RSVP Function Response": "response_query",
            "RSVP Check-in": "checkin_query",
            "RSVP Message Log": "message_query",
        }.items()
    },
}
has_permission = {
    dt: "av_rsvp.permissions.document_access"
    for dt in [
        "RSVP Event",
        "RSVP Function",
        "RSVP Invitation",
        "RSVP Attendee",
        "RSVP Function Response",
        "RSVP Check-in",
        "RSVP Message Log",
    ]
}
