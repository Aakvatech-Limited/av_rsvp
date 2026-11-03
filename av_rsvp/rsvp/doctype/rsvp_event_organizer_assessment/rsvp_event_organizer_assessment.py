from av_rsvp.post_event_feedback import EventReview


class RSVPEventOrganizerAssessment(EventReview):
    author_field = "assessed_by"
    date_field = "assessment_date"
