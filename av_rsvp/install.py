import frappe


def after_install():
    from frappe.utils.password import get_encryption_key

    get_encryption_key()
    # Roles are fixtures; never assign broad roles to existing users automatically.
    frappe.clear_cache()
