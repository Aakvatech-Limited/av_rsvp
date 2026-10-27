from av_rsvp.reporting import execute_report


def execute(filters=None):
    return execute_report("catering", filters or {})
