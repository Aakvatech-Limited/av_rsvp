from av_rsvp.controllers import RSVPInvitationBase
from av_rsvp.permissions import access_level


class RSVPInvitation(RSVPInvitationBase):
    def onload(self):
        self.set_onload("rsvp_access_level", access_level(self.event))
