import frappe


def after_install():
    # Roles are fixtures; never assign broad roles to existing users automatically.
    frappe.clear_cache()
