frappe.ui.form.on("RSVP Event Organizer Assessment", {
  setup(frm) {
    frm.set_query("event", () => ({query: "av_rsvp.post_event.event_link_query"}));
  },
  refresh(frm) {
    frm.add_custom_button(__("Post-Event Dashboard"), () => {
      frappe.route_options = {event: frm.doc.event};
      frappe.set_route("rsvp-post-event-dashboard");
    });
  }
});
