from av_rsvp.controllers import RSVPInvitationBase
from av_rsvp.permissions import access_level, is_event_host


class RSVPInvitation(RSVPInvitationBase):
    def onload(self):
        access = access_level(self.event)
        self.set_onload("rsvp_access_level", access)
        self.set_onload("rsvp_can_resend", access >= 2 or is_event_host(self.event))
