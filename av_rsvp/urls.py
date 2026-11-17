"""Public RSVP links must use the configured external site address."""

from urllib.parse import urljoin

import frappe
from frappe.utils import get_url


def public_url(path):
    host = frappe.conf.get("host_name") or frappe.conf.get("hostname")
    if not host:
        return get_url(path)
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    # Frappe's get_url may append the internal webserver port in developer mode.
    # An explicit public host is authoritative, including any intentional port.
    return urljoin(host, path)
