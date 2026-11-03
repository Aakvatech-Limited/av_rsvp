frappe.pages["rsvp-organizer-dashboard"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({parent: wrapper, title: __("Organizer Dashboard"), single_column: true});
  const esc = value => frappe.utils.escape_html(String(value ?? ""));
  const field = page.add_field({fieldname: "event", label: __("Event"), fieldtype: "Link", options: "RSVP Event", change: () => refresh()});
  const body = $('<div class="p-4"></div>').appendTo(page.body);
  page.add_inner_button(__("Refresh"), () => refresh());
  page.add_inner_button(__("Event Overview"), () => {frappe.route_options = {event: field.get_value()}; frappe.set_route("rsvp-overview");});
  let charts = [];
  function chart(target, labels, values, type, height=260) {
    if (!labels.length) return;
    charts.push(new frappe.Chart(target, {title: "", data: {labels, datasets: [{name: __("People / Places"), values}]}, type, height, colors: ["#4475aa", "#e5a640", "#3e9d84", "#d66b6b"]}));
  }
  async function refresh() {
    body.html('<p class="text-muted">' + __("Loading organizer analytics...") + '</p>');
    try {
      const selected = field.get_value();
      const data = (await frappe.call({method: "av_rsvp.organizer_dashboard.organizer_dashboard", args: {event: selected || ""}, type: "POST"})).message;
      const kpis = [
        ["invitations", __("Invitations")], ["pending", __("Pending RSVPs")],
        ["attending", __("Attending RSVPs")], ["confirmed_people", __("Confirmed People")],
        ["confirmed_places", __("Confirmed Places")], ["waitlisted_places", __("Waitlisted Places")],
        ["checked_in_people", __("Checked-in People")], ["capacity", __("Limited Function Capacity")]
      ];
      const cards = kpis.map(([key, label]) => '<div class="col-lg-3 col-md-4 col-sm-6 mb-3"><div class="border rounded p-3 h-100"><div class="text-muted small">' + esc(label) + '</div><h2 class="mt-2">' + Number(data.totals[key] || 0).toLocaleString() + '</h2></div></div>').join("");
      const rows = data.functions.map(f => '<tr><td>' + esc(f.title) + '</td><td>' + (f.capacity || __("Unlimited")) + '</td><td>' + f.confirmed + '</td><td>' + f.waitlisted + '</td><td>' + f.checked_in + '</td><td><a href="/app/rsvp-function/' + encodeURIComponent(f.name) + '">' + __("Open") + '</a></td></tr>').join("");
      body.html('<p class="text-muted">' + __("Live figures for events assigned to you. Confirmed people are unique per event; function places count each allocation.") + '</p><div class="row">' + cards + '</div><div class="row mt-3"><div class="col-lg-6 mb-4"><h5>' + __("Invitation Responses") + '</h5><div id="rsvp-responses-chart"></div></div><div class="col-lg-6 mb-4"><h5>' + __("Function Attendance") + '</h5><div id="rsvp-functions-chart"></div></div></div><h5>' + __("Function Capacity & Check-in") + '</h5><div class="table-responsive"><table class="table table-bordered"><thead><tr><th>' + __("Function") + '</th><th>' + __("Capacity") + '</th><th>' + __("Confirmed") + '</th><th>' + __("Waitlisted") + '</th><th>' + __("Checked In") + '</th><th></th></tr></thead><tbody>' + (rows || '<tr><td colspan="6">' + __("No functions available") + '</td></tr>') + '</tbody></table></div>');
      charts = [];
      chart(body.find("#rsvp-responses-chart")[0], [__("Pending"), __("Attending"), __("Declined"), __("Maybe")], [data.totals.pending, data.totals.attending, data.totals.declined, data.totals.maybe], "donut");
      chart(body.find("#rsvp-functions-chart")[0], data.functions.map(f => f.title), data.functions.map(f => f.confirmed), "bar");
    } catch (err) { body.html('<p class="text-danger">' + __("Could not load organizer analytics. Check your event permissions.") + '</p>'); }
  }
  wrapper.rsvp_refresh = refresh;
  refresh();
};
frappe.pages["rsvp-organizer-dashboard"].on_page_show = wrapper => wrapper.rsvp_refresh?.();
