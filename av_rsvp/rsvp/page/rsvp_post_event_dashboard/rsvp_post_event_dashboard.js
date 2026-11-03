frappe.pages["rsvp-post-event-dashboard"].on_page_load = function(wrapper) {
  const page = frappe.ui.make_app_page({parent: wrapper, title: __("Post-Event Dashboard"), single_column: true});
  const esc = v => frappe.utils.escape_html(String(v ?? ""));
  const body = $('<div class="p-4"></div>').appendTo(page.body);
  let sequence = 0;
  const event = page.add_field({fieldname: "event", label: __("Event"), fieldtype: "Select", options: "\n", change: () => refresh()});
  const from = page.add_field({fieldname: "from_date", label: __("From Date"), fieldtype: "Date", change: () => refresh()});
  const to = page.add_field({fieldname: "to_date", label: __("To Date"), fieldtype: "Date", change: () => refresh()});
  const chart = (id, labels, datasets, type="bar") => {
    if (labels.length) new frappe.Chart(body.find(`[data-chart="${id}"]`)[0], {data: {labels, datasets}, type, height: 260, colors: ["#368b85", "#517bc2", "#d99a48", "#ce6670"]});
  };
  const table = (title, headers, rows) => `<h5 class="mt-4">${esc(__(title))}</h5><div class="table-responsive"><table class="table table-bordered"><thead><tr>${headers.map(h => `<th>${esc(__(h))}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(v => `<td>${esc(v)}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${headers.length}">${esc(__("No records"))}</td></tr>`}</tbody></table></div>`;
  const reviews = (title, rows, fields) => `<h5 class="mt-4">${esc(__(title))}</h5>${rows.map(r => `<div class="border rounded p-3 mb-3"><strong>${esc(r.event)}</strong>${fields.map(([key,label]) => `<div class="mt-2"><span class="text-muted">${esc(__(label))}: </span><span style="white-space:pre-wrap">${esc(r[key] || "—")}</span></div>`).join("")}</div>`).join("") || `<p class="text-muted">${esc(__("Not received / not published"))}</p>`}`;
  async function refresh() {
    const current = ++sequence;
    body.text(__("Loading post-event results..."));
    try {
      const data = (await frappe.call({method: "av_rsvp.post_event.dashboard", type: "POST", args: {event: event.get_value(), from_date: from.get_value(), to_date: to.get_value()}})).message;
      if (current !== sequence) return;
      page.clear_inner_toolbar();
      page.add_inner_button(__("Refresh"), refresh);
      page.clear_primary_action();
      page.clear_secondary_action();
      if (data.can_give_feedback) page.set_primary_action(__("Host Feedback"), () => data.own_feedback ? frappe.set_route("Form", "RSVP Event Host Feedback", data.own_feedback) : frappe.new_doc("RSVP Event Host Feedback", {event: event.get_value()}));
      if (data.can_assess) page.set_secondary_action(__("Organizer Assessment"), () => frappe.new_doc("RSVP Event Organizer Assessment", {event: event.get_value()}));
      if (data.can_assess) page.add_inner_button(__("Manage Assessments"), () => frappe.set_route("List", "RSVP Event Organizer Assessment", {event: event.get_value()}));
      const kpis = [["invitations","Invitations"],["invited_allowance","Invited People Allowance"],["confirmed_people","Confirmed People"],["attended_people","Actual Attendees"],["no_shows","No-Shows"],["attendance_rate","Attendance Rate (%)"],["host_satisfaction","Host Satisfaction / 5"]];
      body.html(`<p class="text-muted">${esc(__(data.provisional ? "Provisional attendance: one or more events are not marked Completed." : "Attendance for completed events. Figures reflect current records and any audited corrections."))}</p><p class="text-muted">${esc(__("People count once per event. Allowance is invitation capacity, not named invitees. Attendance rate is confirmed people checked in / confirmed people. Arrival times use the site timezone and count function check-ins."))}</p><div class="row">${kpis.map(([key,label]) => `<div class="col-lg-3 col-sm-6 mb-3"><div class="border rounded p-3"><div class="text-muted">${esc(__(label))}</div><h2>${esc(data.totals[key] == null ? __(key === "host_satisfaction" ? "Not received" : "N/A") : data.totals[key])}</h2></div></div>`).join("")}</div><div class="row"><div class="col-lg-6"><h5>${esc(__("Invitation Responses"))}</h5><div data-chart="responses"></div></div><div class="col-lg-6"><h5>${esc(__("Confirmed vs Attended by Function"))}</h5><div data-chart="attendance"></div></div><div class="col-lg-6"><h5>${esc(__("Arrivals by Hour"))}</h5><div data-chart="arrivals"></div></div><div class="col-lg-6"><h5>${esc(__("Host Ratings"))}</h5><div data-chart="ratings"></div></div></div>`
        + table("Event Summary", ["Event","Title","Status"], data.events.map(r => [r.name,r.event_title,r.status]))
        + table("Function Attendance", ["Event","Function","Capacity","Confirmed People","Attendees","No-Shows"], data.functions.map(r => [r.event,r.function_title,r.capacity || __("Unlimited"),r.confirmed_people,r.attended_people,r.no_shows]))
        + table("Confirmed People Who Did Not Attend", ["Event","Attendee"], data.no_shows.map(r => [r.event,r.attendee_name]))
        + reviews("Host Experience Feedback", data.host_feedback, [["host_user","Host"],["feedback_date","Date"],["overall_satisfaction","Overall Satisfaction / 5"],["planning_rating","Planning / 5"],["execution_rating","Execution / 5"],["expectations_met","Expectations Met"],["what_worked_well","What Worked Well"],["improvements_needed","Improvements Needed"],["comments","Comments"]])
        + reviews("Published Organizer Assessments", data.assessments, [["assessed_by","Assessed By"],["assessment_date","Date"],["objectives_achieved","Objectives Achieved"],["planning_assessment","Planning"],["execution_assessment","Execution"],["issues_encountered","Issues"],["successes","Successes"],["lessons_learned","Lessons Learned"],["recommendations","Recommendations"]]));
      chart("responses", Object.keys(data.responses), [{name: __("Invitations"), values: Object.values(data.responses)}], "donut");
      chart("attendance", data.functions.map(r => r.function_title), [{name: __("Confirmed"),values: data.functions.map(r => r.confirmed_people)},{name: __("Attended"),values: data.functions.map(r => r.attended_people)}]);
      chart("arrivals", data.arrivals.map(r => r.hour), [{name: __("Function Check-ins"),values: data.arrivals.map(r => r.places)}], "line");
      const keys = ["overall_satisfaction","planning_rating","execution_rating"];
      if (data.host_feedback.length) chart("ratings", [__("Overall"),__("Planning"),__("Execution")], [{name: __("Average / 5"), values: keys.map(k => data.host_feedback.reduce((s,r) => s + Number(r[k]), 0) / data.host_feedback.length)}]);
      else body.find('[data-chart="ratings"]').text(__("Not received"));
    } catch(error) {
      if (current === sequence) body.text(__("Unable to load results. Check event access and date filters."));
    }
  }
  page.add_inner_button(__("Refresh"), refresh);
  async function show() {
    const data = (await frappe.call({method: "av_rsvp.post_event.dashboard", type: "POST"})).message;
    const selected = frappe.route_options?.event || event.get_value();
    frappe.route_options = null;
    event.df.options = [{value: "",label: __("All Accessible Events")}, ...data.events.map(r => ({value:r.name,label:r.event_title + " (" + r.name + ")"}))];
    event.refresh();
    if (selected && data.events.some(r => r.name === selected)) await event.set_value(selected);
    await refresh();
  }
  wrapper.post_event_show = show;
};
frappe.pages["rsvp-post-event-dashboard"].on_page_show = wrapper => wrapper.post_event_show?.();
