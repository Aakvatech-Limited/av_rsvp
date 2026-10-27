import frappe

no_cache = 1
sitemap = 0


def get_context(context):
    context.no_cache = 1
    context.no_header = 1
    context.no_footer = 1
    context.title = "Your invitation | AV RSVP"
    frappe.local.response_headers.update(
        {
            "Cache-Control": "no-store, private",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        }
    )
