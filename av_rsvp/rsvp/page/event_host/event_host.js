frappe.pages["event-host"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({parent: wrapper, title: __("Event Overview"), single_column: true});
  const esc = value => frappe.utils.escape_html(String(value ?? ""));
  const api = async (method, args = {}) => (await frappe.call({method: "av_rsvp.api." + method, args, type: "POST"})).message;
  let pageNumber = 0;
  const event = page.add_field({fieldname: "event", label: __("Event"), fieldtype: "Select", options: "\n", change: () => {pageNumber = 0; load();}});
  const status = page.add_field({fieldname: "response", label: __("Response"), fieldtype: "Select", options: "\nPending\nAttending\nDeclined\nMaybe", change: () => {pageNumber = 0; load();}});
  const search = page.add_field({fieldname: "search", label: __("Guest name"), fieldtype: "Data", change: () => {pageNumber = 0; load();}});
  const body = $('<div class="p-4"></div>').appendTo(page.body);
  async function load() {
    const selected = event.get_value();
    if (!selected) {body.text(__("No event selected.")); return;}
    const data = await api("event_overview", {event: selected, response_status: status.get_value(), search: search.get_value(), page: pageNumber});
    if (selected !== event.get_value()) return;
    const labels = {invitations:"Invitations", invited_people:"Invited people", pending:"Pending invitations", confirmed_people:"Confirmed people", waitlisted_places:"Waitlisted places", checked_in_people:"People checked in"};
    body.html(`<h4>${esc(data.event_title)}</h4><div class="row">${Object.entries(labels).map(([key,label]) => `<div class="col-lg-2 col-6 mb-3"><div class="border rounded p-3"><div class="text-muted small">${esc(__(label))}</div><h2>${Number(data.stats[key] || 0)}</h2></div></div>`).join("")}</div>
      <h5>Function attendance</h5><div class="table-responsive"><table class="table"><thead><tr><th>Function</th><th>Capacity</th><th>Confirmed</th><th>Waitlisted</th><th>Checked in</th></tr></thead><tbody>${data.functions.map(f => `<tr><td>${esc(f.function_title)}</td><td>${Number(f.capacity) || "Unlimited"}</td><td>${Number(f.confirmed)}</td><td>${Number(f.waitlisted)}</td><td>${Number(f.checked_in)}</td></tr>`).join("")}</tbody></table></div>
      <h5>Invitation responses</h5><div class="table-responsive"><table class="table"><thead><tr><th>Guest</th><th>Allowance</th><th>Response</th><th>Delivery</th></tr></thead><tbody>${data.invitations.map(i => `<tr><td>${esc(i.guest_name)}</td><td>${Number(i.max_attendees)}</td><td>${esc(i.response_status)}</td><td>${esc(i.delivery_status)}</td></tr>`).join("") || '<tr><td colspan="4">No invitations match these filters.</td></tr>'}</tbody></table></div>
      <div class="d-flex justify-content-between"><button class="btn btn-default" id="host-prev" ${pageNumber ? "" : "disabled"}>Previous</button><span>Page ${pageNumber + 1}</span><button class="btn btn-default" id="host-next" ${data.has_more ? "" : "disabled"}>Next</button></div>`);
    body.find("#host-prev").on("click", () => {pageNumber--; load();});
    body.find("#host-next").on("click", () => {pageNumber++; load();});
  }
  page.add_inner_button(__("Refresh"), load);
  api("host_events").then(events => {
    event.df.options = "\n" + events.map(e => e.name).join("\n");
    event.refresh();
    const requested = frappe.route_options?.event;
    frappe.route_options = null;
    if (requested && events.some(e => e.name === requested)) event.set_value(requested);
    else if (events.length) event.set_value(events[0].name);
    else body.text(__("No events are assigned to your Event Host account."));
  });
};
