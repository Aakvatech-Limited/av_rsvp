frappe.pages["rsvp-overview"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({parent: wrapper, title: __("Event Overview"), single_column: true});
  const api = async (method, args) => (await frappe.call({method:`av_rsvp.api.${method}`, args, type:"POST"})).message;
  const esc = value => frappe.utils.escape_html(String(value ?? ""));
  let offset = 0, current;
  const event = page.add_field({fieldname:"event", label:__("Event"), fieldtype:"Link", options:"RSVP Event", change:() => {offset=0; load();}});
  const status = page.add_field({fieldname:"response", label:__("Response"), fieldtype:"Select", options:"\nPending\nAttending\nDeclined\nMaybe", change:() => {offset=0; load();}});
  const search = page.add_field({fieldname:"search", label:__("Guest name"), fieldtype:"Data", change:() => {offset=0; load();}});
  const body = $('<div class="p-4"></div>').appendTo(page.body);
  function download(file) {const url=URL.createObjectURL(new Blob([file.content],{type:"text/csv;charset=utf-8"})); const a=document.createElement("a");a.href=url;a.download=file.filename;a.click();URL.revokeObjectURL(url);}
  async function load() {
    const selected=event.get_value(); if(!selected) {body.html('<p class="text-muted">Select an event to manage invitations and attendance.</p>');return;}
    const data=await api("event_overview",{event:selected,response_status:status.get_value(),search:search.get_value(),page:offset});
    if(selected!==event.get_value()) return;
    current=data;
    const labels={invitations:"Invitations",invited_people:"Invited people",pending:"Pending invitations",confirmed_people:"Confirmed people",waitlisted_places:"Waitlisted places",checked_in_people:"People checked in"};
    body.html(`<div class="row">${Object.entries(labels).map(([key,label])=>`<div class="col-lg-2 col-6 mb-3"><div class="border rounded p-3"><div class="text-muted small">${__(label)}</div><h2 class="mt-2">${Number(data.stats[key])}</h2></div></div>`).join("")}</div><h4>${esc(data.event_title)}</h4><p class="text-muted">People are counted once per event. Function places are counted separately.</p>
      <div class="table-responsive"><table class="table"><thead><tr><th>Function</th><th>Capacity</th><th>Confirmed</th><th>Waitlisted</th><th>Checked in</th></tr></thead><tbody>${data.functions.map(f=>`<tr><td>${esc(f.function_title)}</td><td>${Number(f.capacity)||"Unlimited"}</td><td>${Number(f.confirmed)}</td><td>${Number(f.waitlisted)}</td><td>${Number(f.checked_in)}</td></tr>`).join("")}</tbody></table></div>
      <h4 class="mt-4">Invitations</h4><div class="table-responsive"><table class="table"><thead><tr><th>Guest</th><th>Allowance</th><th>Response</th><th>Email</th><th>Actions</th></tr></thead><tbody>${data.invitations.map(i=>`<tr><td><a href="/app/rsvp-invitation/${encodeURIComponent(i.name)}">${esc(i.guest_name)}</a></td><td>${Number(i.max_attendees)}</td><td><span class="indicator-pill ${i.response_status==="Attending"?"green":i.response_status==="Declined"?"red":"orange"}">${esc(i.response_status)}</span></td><td>${esc(i.delivery_status)}</td><td><button class="btn btn-xs btn-default" data-action="respond" data-name="${esc(i.name)}">Record response</button> <button class="btn btn-xs btn-default" data-action="share" data-name="${esc(i.name)}">Share</button></td></tr>`).join("")||'<tr><td colspan="5">No invitations match these filters.</td></tr>'}</tbody></table></div><div class="d-flex justify-content-between"><button id="previous" class="btn btn-default" ${offset?"":"disabled"}>Previous</button><span>Page ${offset+1}</span><button id="next" class="btn btn-default" ${data.has_more?"":"disabled"}>Next</button></div>`);
    body.find("#previous").on("click",()=>{offset--;load();});body.find("#next").on("click",()=>{offset++;load();});
    body.find("[data-action]").on("click",async function(){const name=this.dataset.name;if(this.dataset.action==="respond")window.open(`/rsvp?invitation=${encodeURIComponent(name)}`,"_blank","noopener");else {const link=await api("share_invitation",{invitation:name});frappe.msgprint({title:__("Share invitation"),message:`<p><a href="${esc(link.url)}" target="_blank" rel="noopener">Open private invitation</a></p><p><a href="${esc(link.whatsapp_url)}" target="_blank" rel="noopener">Share using WhatsApp</a></p><input class="form-control" readonly value="${esc(link.url)}" onclick="this.select()">`});}});
  }
  page.set_primary_action(__("Add invitation"),()=>{if(!event.get_value())return frappe.msgprint(__("Select an event first."));frappe.new_doc("RSVP Invitation",{event:event.get_value()});});
  page.add_inner_button(__("Refresh"),load);
  page.add_inner_button(__("Check-in"),()=>{frappe.route_options={event:event.get_value()};frappe.set_route("rsvp-checkin");});
  page.add_menu_item(__("Import guests"),()=>frappe.new_doc("Data Import",{reference_doctype:"RSVP Guest",import_type:"Insert New Records"}));
  page.add_menu_item(__("Import invitations"),()=>frappe.new_doc("Data Import",{reference_doctype:"RSVP Invitation",import_type:"Insert New Records"}));
  page.add_menu_item(__("Send email invitations"),()=>send(0));
  page.add_menu_item(__("Remind pending guests"),()=>send(1));
  page.add_menu_item(__("Export guest list"),async()=>{if(event.get_value())download(await api("export_guests",{event:event.get_value()}));});
  page.add_menu_item(__("Promote waiting list"),async()=>{if(event.get_value()){const result=await api("promote",{event:event.get_value()});frappe.show_alert(`${result.promoted} places confirmed`);load();}});
  async function send(pending) {if(!event.get_value())return;frappe.confirm(pending?__("Email a reminder to guests who have not responded?"):__("Email invitations to this event's guests?"),async()=>{const r=await api("send_invitations",{event:event.get_value(),pending_only:pending});frappe.msgprint(`${r.queued} emails queued. ${r.skipped_without_email} invitations have no email address.`);load();});}
  wrapper.rsvp_load = () => {if(frappe.route_options?.event){event.set_value(frappe.route_options.event);frappe.route_options=null;}else load();};
  load();
};
frappe.pages["rsvp-overview"].on_page_show = wrapper => wrapper.rsvp_load?.();
