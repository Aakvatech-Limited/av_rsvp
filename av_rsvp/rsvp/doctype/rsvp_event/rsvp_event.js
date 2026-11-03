frappe.ui.form.on("RSVP Event", {
  refresh(frm) {
    if (frm.perm?.some(permission=>permission.write)) {
      frm.add_custom_button(__("Attendance Before Contact Details"),()=>{
        frm.clear_table("form_sections");
        ["Event Information", "Response", "Contact Details", "Guest Details", "Additional Questions", "Message to Organiser"].forEach(section=>frm.add_child("form_sections", {section}));
        frm.refresh_field("form_sections");
        frm.dirty();
        frappe.show_alert({message:__("Section order updated. Save the event to apply it."),indicator:"green"});
      }, __("Guest Form"));
    }
    if(frm.is_new())return;
    if (frm.doc.event_web_page) {
      frm.add_custom_button(__("Edit Event Web Page"),()=>frappe.set_route("Form", "Web Page", frm.doc.event_web_page), __("Guest Form"));
    } else if (frappe.model.can_create("Web Page")) {
      frm.add_custom_button(__("Create Event Web Page"),async()=>{
        if (frm.is_dirty()) {frappe.msgprint(__("Save the event first."));return;}
        const {message} = await frappe.call({method:"av_rsvp.api.create_event_web_page",args:{event:frm.doc.name},type:"POST",freeze:true});
        await frm.reload_doc();
        frappe.set_route("Form", "Web Page", message.name);
      }, __("Guest Form"));
    }
    frm.add_custom_button(__("Event Overview"),()=>{frappe.route_options={event:frm.doc.name};frappe.set_route("rsvp-overview");});
    frm.add_custom_button(__("Check-in"),()=>{frappe.route_options={event:frm.doc.name};frappe.set_route("rsvp-checkin");});
    if(frm.doc.allow_public_registration && frm.doc.status === "Published") {
      frm.add_custom_button(__("Registration QR Code"),()=>av_rsvp_show_registration_qr(frm));
      frm.add_custom_button(__("Public Registration Page"),async()=>{const {message}=await frappe.call({method:"av_rsvp.api.event_registration_link",args:{event:frm.doc.name},type:"POST"});window.open(message.url,"_blank","noopener,noreferrer");});
    }
    if(frappe.model.can_create("RSVP Invitation"))frm.add_custom_button(__("Add invitation"),()=>frappe.new_doc("RSVP Invitation",{event:frm.doc.name}));
  }
});


async function av_rsvp_show_registration_qr(frm) {
  if (frm.is_dirty()) {
    frappe.msgprint(__("Save the event before generating its registration QR code."));
    return;
  }
  const {message: data} = await frappe.call({
    method: "av_rsvp.api.event_registration_qr",
    args: {event: frm.doc.name},
    type: "POST",
    freeze: true,
  });
  const esc = value => frappe.utils.escape_html(String(value || ""));
  const dialog = new frappe.ui.Dialog({
    title: __("Event Registration QR Code"),
    fields: [{fieldname: "preview", fieldtype: "HTML"}],
  });
  dialog.fields_dict.preview.$wrapper.html(`
    <div style="text-align:center">
      <h4>${esc(data.event_title)}</h4>
      <img src="${esc(data.image)}" alt="${esc(__("Event registration QR code"))}" style="width:100%;max-width:320px;height:auto;background:white">
      <p>${esc(__("Scan to register for this event. No login required."))}</p>
      <p style="overflow-wrap:anywhere"><a href="${esc(data.url)}" target="_blank" rel="noopener noreferrer">${esc(data.url)}</a></p>
    </div>
    <div class="rsvp-qr-actions" style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center">
      <button type="button" class="btn btn-primary" data-copy-qr>${esc(__("Copy QR Image"))}</button>
      <button type="button" class="btn btn-default" data-download-qr>${esc(__("Download PNG"))}</button>
      <button type="button" class="btn btn-default" data-copy-link>${esc(__("Copy Registration Link"))}</button>
    </div>
    <p class="text-muted" style="margin-top:12px">${esc(__("Paste the image into an email, WhatsApp, invitation or poster. If image copying is unavailable, download the PNG instead."))}</p>
  `);
  const download = () => {
    const link = document.createElement("a");
    link.href = data.image;
    link.download = data.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  };
  dialog.$wrapper.find("[data-download-qr]").on("click", download);
  dialog.$wrapper.find("[data-copy-link]").on("click", () => frappe.utils.copy_to_clipboard(data.url));
  dialog.$wrapper.find("[data-copy-qr]").on("click", async () => {
    if (!window.isSecureContext || !navigator.clipboard?.write || !window.ClipboardItem) {
      frappe.msgprint(__("Image copying is unavailable in this browser. Use Download PNG to save and share the QR code."));
      return;
    }
    try {
      // Keep clipboard.write in the click gesture; do not wait for image loading.
      const bytes = Uint8Array.from(atob(data.image.split(",")[1]), char => char.charCodeAt(0));
      const blob = new Blob([bytes], {type: "image/png"});
      await navigator.clipboard.write([new ClipboardItem({"image/png": blob})]);
      frappe.show_alert({message: __("QR image copied. You can now paste it into your communication."), indicator: "green"});
    } catch (_) {
      frappe.msgprint(__("The browser could not copy the image. Use Download PNG to save and share the QR code."));
    }
  });
  dialog.show();
}
