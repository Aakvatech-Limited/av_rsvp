(() => {
  for (const [doctype, arg] of [["RSVP Event", "event"], ["RSVP Invitation", "invitation"]]) {
    frappe.ui.form.on(doctype, {
      refresh(frm) {
        if (frm.is_new()) return;
        frm.add_custom_button(__("Preview Messages"), async () => {
          if (frm.is_dirty()) {
            frappe.msgprint(__("Save your changes before previewing messages."));
            return;
          }
          const {message: previews} = await frappe.call({
            method: "av_rsvp.api.preview_messages",
            args: {[arg]: frm.doc.name},
            type: "POST",
            freeze: true,
          });
          showPreview(previews);
        });
      },
    });
  }

  function showPreview(previews) {
    const labels = [__("Invitation Email"), __("Confirmation Email"), __("Guest Confirmation")];
    const dialog = new frappe.ui.Dialog({
      title: __("Preview Messages"),
      size: "extra-large",
      fields: [
        {fieldname: "view", fieldtype: "Select", label: __("Preview"), options: labels, default: labels[0]},
        {fieldname: "content", fieldtype: "HTML"},
      ],
    });
    dialog.fields_dict.view.df.onchange = render;

    function render() {
      const field = dialog.fields_dict.content.$wrapper.empty();
      const selection = dialog.get_value("view");
      if (selection === labels[2]) {
        const guest = previews.guest_confirmation;
        if (!guest) {
          field.text(__("The confirmation-only guest view is disabled for this event."));
          return;
        }
        const card = $("<div>").addClass("border rounded p-4 text-center").appendTo(field);
        $("<p>").css("white-space", "pre-line").text(guest.message).appendTo(card);
        $("<img>").attr({src: guest.qr, width: 150, height: 150, alt: __("Sample entry QR code")}).appendTo(card);
        return;
      }

      const email = selection === labels[1] ? previews.confirmation : previews.invitation;
      const subject = $("<p>").appendTo(field);
      $("<strong>").text(__("Subject")).appendTo(subject);
      subject.append(document.createTextNode("  " + email.subject));
      if (selection === labels[1]) {
        $("<p>").addClass("text-muted").text(__("Sample RSVP with one confirmed place.")).appendTo(field);
      }
      $("<iframe>").attr({title: selection, sandbox: "", referrerpolicy: "no-referrer"})
        .css({width: "100%", height: "55vh", border: 0})
        .prop("srcdoc", email.body.replace("<head>",
          "<head><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src data: https: http:; style-src 'unsafe-inline'\">"))
        .appendTo(field);
    }

    dialog.show();
    render();
  }
})();
