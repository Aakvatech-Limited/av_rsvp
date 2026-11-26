import frappe


def execute():
    meta = frappe.get_meta("RSVP Event")
    for row in frappe.get_all("RSVP Event", fields=["name", "confirmation_email_subject", "confirmation_email_message"]):
        updates = {}
        for field in ("confirmation_email_subject", "confirmation_email_message"):
            if not (row.get(field) or "").strip():
                updates[field] = meta.get_field(field).default
        if updates:
            frappe.db.set_value("RSVP Event", row.name, updates, update_modified=False)
