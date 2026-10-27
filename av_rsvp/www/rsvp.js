/* Private links keep their token in the fragment, outside server/referrer URLs. */
frappe.ready(async () => {
  const root = document.getElementById("rsvp-root");
  const token = window.location.hash.slice(1);
  const staffInvitation = new URLSearchParams(window.location.search).get("invitation");
  const esc = value => frappe.utils.escape_html(String(value ?? ""));
  let state, people = [];
  const api = async (method, args) => (await frappe.call({method: `av_rsvp.api.${method}`, args, type: "POST"})).message;
  const date = value => value ? new Date(value.replace(" ", "T")).toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"}) : "";
  function error(message) {
    const box = document.createElement("div");
    box.className = "rsvp-notice rsvp-error";
    box.setAttribute("role", "alert");
    box.textContent = message;
    root.prepend(box);
  }
  function capture() {
    for (const card of root.querySelectorAll("[data-person]")) {
      const person = people[Number(card.dataset.person)];
      for (const input of card.querySelectorAll("[data-field]")) person[input.dataset.field] = input.value;
      for (const row of card.querySelectorAll("[data-function]")) {
        const answer = person.functions.find(f => f.function === row.dataset.function);
        answer.attendance = row.querySelector("[data-attendance]").value;
        answer.meal_choice = row.querySelector("[data-meal]")?.value || "";
      }
    }
  }
  function option(value, selected) { return `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`; }
  function personCard(person, index) {
    return `<section class="rsvp-card" data-person="${index}"><button type="button" class="remove" data-remove="${index}">Remove</button><h2>Guest ${index + 1}</h2>
      <label class="rsvp-label" for="name-${index}">Full name</label><input id="name-${index}" data-field="attendee_name" value="${esc(person.attendee_name)}" required maxlength="140" autocomplete="name">
      <label class="rsvp-label" for="age-${index}">Guest category</label><select id="age-${index}" data-field="age_group">${["Adult", "Child"].map(v => option(v, person.age_group)).join("")}</select>
      <div class="rsvp-row"><div><label class="rsvp-label" for="diet-${index}">Dietary requirements</label><textarea id="diet-${index}" data-field="dietary_requirements" maxlength="1000">${esc(person.dietary_requirements)}</textarea></div>
      <div><label class="rsvp-label" for="access-${index}">Accessibility requests</label><textarea id="access-${index}" data-field="accessibility_requests" maxlength="1000">${esc(person.accessibility_requests)}</textarea></div></div>
      ${state.functions.map((f, fi) => { const answer = person.functions.find(a => a.function === f.name); const meals = (f.meal_options || "").split("\n").map(s => s.trim()).filter(Boolean); return `<div class="rsvp-function" data-function="${esc(f.name)}"><strong>${esc(f.function_title)}</strong><p class="rsvp-muted">${esc(date(f.starts_on))} · ${esc(f.venue || state.event.venue)}</p>
      <label class="rsvp-label" for="attendance-${index}-${fi}">Attendance</label><select id="attendance-${index}-${fi}" data-attendance>${["Attending", "Declined", ...(state.event.allow_maybe ? ["Maybe"] : [])].map(v => option(v, answer.attendance)).join("")}</select>
      ${meals.length ? `<label class="rsvp-label" for="meal-${index}-${fi}">Meal choice</label><select id="meal-${index}-${fi}" data-meal>${option("", answer.meal_choice)}${meals.map(v => option(v, answer.meal_choice)).join("")}</select>` : ""}</div>`; }).join("")}</section>`;
  }
  function render(saved = false) {
    const e = state.event;
    root.innerHTML = `<section class="rsvp-card">${e.banner ? `<img class="rsvp-banner" src="${esc(e.banner)}" alt="">` : ""}<div class="rsvp-eyebrow">${esc(e.host_name || "You're invited")}</div><h1>${esc(e.event_title)}</h1><p>Hello ${esc(state.invitation.guest_name)}, we would love to have you with us.</p><p>${esc(e.description || "")}</p>
      <div class="rsvp-meta"><span>${esc(date(e.starts_on))}</span><span>${esc(e.venue)}</span><span>${esc(e.timezone)}</span></div>${e.map_url ? `<a href="${esc(e.map_url)}" target="_blank" rel="noopener noreferrer">Get directions ↗</a>` : ""}
      <p class="rsvp-muted">Please respond by ${esc(date(e.rsvp_deadline))}. Your invitation allows ${esc(state.invitation.max_attendees)} people, including you.</p>${staffInvitation ? '<div class="rsvp-notice">Organiser entry: this response will record your signed-in user.</div>' : ""}</section>
      ${saved ? '<div class="rsvp-notice" role="status">Your response has been saved. Check each function’s confirmation status below.</div>' : ""}
      ${!state.editable ? '<div class="rsvp-notice">Online responses are closed. Contact the organiser for changes.</div>' : ""}
      ${state.editable ? `<form id="response-form"><section class="rsvp-card"><h2>Your response</h2><label class="rsvp-label" for="overall">Will you be joining us?</label><select id="overall">${["Attending", "Declined", ...(e.allow_maybe ? ["Maybe"] : [])].map(v => option(v, state.invitation.response_status === "Pending" ? "Attending" : state.invitation.response_status)).join("")}</select></section><div id="people">${people.map(personCard).join("")}</div>
      <section class="rsvp-card"><button type="button" class="secondary" id="add-person" ${people.length >= state.invitation.max_attendees ? "disabled" : ""}>+ Add guest</button><label class="rsvp-label" for="notes">Message to the organiser</label><textarea id="notes" maxlength="1000">${esc(state.notes || "")}</textarea><p class="rsvp-muted">${esc(e.privacy_notice || "Your information is used to organise this event. Share only the details needed for your attendance.")}</p><div class="rsvp-actions"><button type="submit" id="save-response">Save response</button></div></section></form>` : ""}
      ${state.attendees.length ? `<section class="rsvp-card"><h2>Your attendance details</h2>${state.attendees.map(p => `<div class="rsvp-pass">${p.entry_qr ? `<img src="${p.entry_qr}" alt="Entry QR code for ${esc(p.attendee_name)}">` : ""}<div><strong>${esc(p.attendee_name)}</strong>${p.functions.map(a => `<div>${esc(state.functions.find(f => f.name === a.function)?.function_title || "")} <span class="rsvp-badge">${esc(a.allocation)}</span></div>`).join("")}${p.entry_token ? '<small>Present this pass at the event.</small>' : ""}</div></div>`).join("")}<div class="rsvp-actions"><button type="button" class="secondary" id="print-passes">Print passes</button>${token ? '<button type="button" class="secondary" id="calendar">Add to calendar</button>' : ""}</div></section>` : ""}
      <p class="rsvp-muted">${esc(e.contact_email || "")} ${esc(e.contact_phone || "")}</p>`;
    root.querySelector("#add-person")?.addEventListener("click", () => {
      capture(); state.notes = root.querySelector("#notes").value; state.invitation.response_status = root.querySelector("#overall").value;
      people.push({attendee_name: "", age_group: "Adult", dietary_requirements: "", accessibility_requests: "", functions: state.functions.map(f => ({function: f.name, attendance: "Attending", meal_choice: ""}))}); render();
    });
    root.querySelectorAll("[data-remove]").forEach(button => button.addEventListener("click", () => {capture(); state.notes = root.querySelector("#notes").value; state.invitation.response_status = root.querySelector("#overall").value; people.splice(Number(button.dataset.remove), 1); render();}));
    root.querySelector("#response-form")?.addEventListener("submit", async event => {
      event.preventDefault(); capture(); const button = root.querySelector("#save-response"); button.disabled = true;
      try {
        const response = root.querySelector("#overall").value;
        const submitted = structuredClone(people);
        if (response !== "Attending") submitted.forEach(p => p.functions.forEach(f => {f.attendance = response; f.meal_choice = "";}));
        const notes = root.querySelector("#notes").value;
        state = await api(staffInvitation ? "record_response" : "respond", {...(staffInvitation ? {invitation: staffInvitation} : {token}), response, people: JSON.stringify(submitted), notes});
        people = structuredClone(state.attendees); render(true);
      } catch (_) {error("Your response could not be saved. Review the message shown and try again."); button.disabled = false;}
    });
    root.querySelector("#print-passes")?.addEventListener("click", () => window.print());
    root.querySelector("#calendar")?.addEventListener("click", async () => { const file = await api("calendar", {token}); const url = URL.createObjectURL(new Blob([file.content], {type:"text/calendar;charset=utf-8"})); const a = document.createElement("a"); a.href=url; a.download=file.filename; a.click(); URL.revokeObjectURL(url); });
  }
  try {
    if (!token && !staffInvitation) {root.innerHTML = '<div class="rsvp-card"><h1>Your invitation awaits</h1><p>Open the private invitation link sent by your organiser.</p></div>'; return;}
    state = await api(staffInvitation ? "staff_invitation" : "get_invitation", staffInvitation ? {invitation: staffInvitation} : {token});
    people = structuredClone(state.attendees);
    if (!people.length && state.invitation.response_status === "Pending") people.push({attendee_name: state.invitation.guest_name, age_group:"Adult", dietary_requirements:"", accessibility_requests:"", functions:state.functions.map(f => ({function:f.name, attendance:"Attending", meal_choice:""}))});
    render();
  } catch (_) {root.innerHTML = '<div class="rsvp-card"><h1>Invitation unavailable</h1><p>This invitation may have expired, or you may need to sign in as an organiser. Contact the event organiser for help.</p></div>';}
});
