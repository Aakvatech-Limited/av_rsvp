frappe.ui.form.on("RSVP Invitation", {
  refresh(frm) {
    if (frm.is_new()) return;
    if (frm.doc.__onload?.rsvp_can_resend && frm.doc.email && !frm.doc.revoked) {
      frm.add_custom_button(__("Resend Invitation"), () => {
        frappe.confirm(__("Resend the invitation to the email address on this record?"), async () => {
          const {message} = await frappe.call({
            method: "av_rsvp.api.resend_invitation",
            args: {invitation: frm.doc.name},
            type: "POST",
            freeze: true,
          });
          frappe.msgprint(message.queued
            ? __("Invitation email queued.")
            : __("A resend has already been requested for this invitation today."));
        });
      });
    }
    const access = frm.doc.__onload?.rsvp_access_level || 0;
    if (access < 2) return;
    frm.add_custom_button(__("Record response"),()=>window.open(`/rsvp?invitation=${encodeURIComponent(frm.doc.name)}`,"_blank","noopener"));
    frm.add_custom_button(__("Share invitation"),async()=>{const r=await frappe.call({method:"av_rsvp.api.share_invitation",args:{invitation:frm.doc.name},type:"POST"});const e=frappe.utils.escape_html;frappe.msgprint({title:__("Private invitation"),message:`<p><a href="${e(r.message.whatsapp_url)}" target="_blank" rel="noopener">Share using WhatsApp</a></p><input class="form-control" readonly value="${e(r.message.url)}" onclick="this.select()">`});});
    if (access >= 3) {
      frm.add_custom_button(__("Revoke invitation"),()=>frappe.confirm(__("Revoke access and cancel this invitation's places?"),async()=>{await frappe.call({method:"av_rsvp.api.revoke_invitation",args:{invitation:frm.doc.name},type:"POST"});frm.reload_doc();}),__("Access"));
      frm.add_custom_button(__("Renew private link"),()=>frappe.confirm(__("Replace the private link? The previous link will stop working."),async()=>{await frappe.call({method:"av_rsvp.api.renew_invitation",args:{invitation:frm.doc.name},type:"POST"});frm.reload_doc();}),__("Access"));
    }
  }
});
