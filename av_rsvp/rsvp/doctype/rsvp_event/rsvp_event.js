frappe.ui.form.on("RSVP Event", {
  refresh(frm) {
    if(frm.is_new())return;
    frm.add_custom_button(__("Event Overview"),()=>{frappe.route_options={event:frm.doc.name};frappe.set_route("rsvp-overview");});
    frm.add_custom_button(__("Check-in"),()=>{frappe.route_options={event:frm.doc.name};frappe.set_route("rsvp-checkin");});
    if(frappe.model.can_create("RSVP Invitation"))frm.add_custom_button(__("Add invitation"),()=>frappe.new_doc("RSVP Invitation",{event:frm.doc.name}));
  }
});
