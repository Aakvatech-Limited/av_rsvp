from av_rsvp.post_event_feedback import EventReview


class RSVPEventHostFeedback(EventReview):
    author_field = "host_user"
    date_field = "feedback_date"
