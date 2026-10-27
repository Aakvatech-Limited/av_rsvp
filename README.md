# AV RSVP

**Personal invitations. Reliable guest counts. Simple event entry.**

AV RSVP is a standalone Frappe app for invitation-only events, family and company invitations, multi-function programmes, meal planning, waiting lists, and QR check-in. Guests respond from a private mobile-friendly link without creating an account. Organisers manage events in Frappe Desk.

Built by **Aakvatech Limited**. No ERPNext dependency.

## What is included

- Events with a venue, timezone, deadline, banner, description and organising team.
- One default function for a simple event; separate capacities and meals for multi-function events.
- Reusable guest directory, native bulk import, and individual/family/organisation/VIP invitations.
- Guest allowances include the primary guest, rather than counting only additional people.
- Attending, Declined and optional Maybe responses, with named adults/children.
- Per-person, per-function responses, dietary needs, accessibility requests and meal choices.
- Atomic capacity allocation and FIFO individual waiting-list promotion.
- Private invitation links, revocation and link replacement; separate QR entry passes.
- Email invitations, confirmations and optional scheduled pending-response reminders.
- WhatsApp sharing links (manual sending; no automated WhatsApp provider required).
- Organiser entry of responses on behalf of guests, with the signed-in user recorded.
- Event overview with invitation/person counts, function totals and response filters.
- Camera QR scanning, manual attendee lookup, duplicate-check-in alerts and audited reversals.
- Guest register, catering requirements and check-in register reports; guest CSV and calendar downloads.
- Frappe v16 app entry, standard Dock, Sidebar and Workspace.

## Requirements

- Frappe **16.50 or later, below v17**. Use the Python/Node/database versions required by your Frappe release. CI follows current `version-16` with Python 3.14, Node 24 and MariaDB 11.8.
- A working site `encryption_key` and an externally reachable HTTPS `host_name`.
- An outgoing Email Account and running workers/scheduler for email and reminders.
- HTTPS and camera permission for phone scanning; manual lookup remains available.

## Installation

```bash
bench get-app https://github.com/Aakvatech-Limited/av_rsvp --branch feat/initial-rsvp-app
bench --site your-site install-app av_rsvp
bench --site your-site migrate
bench build --app av_rsvp
```

Use `main` after the implementation pull request is merged. Assign **RSVP Administrator** to the app administrator, or **Event Manager** to organisers. The app does not automatically assign roles to existing users.

Open **AV RSVP → RSVP** from the Apps screen. The workspace links to Event Overview, Events, Invitations, Attendees, Check-in, masters, reports and settings.

## First event walkthrough

1. Create an **RSVP Event** in Draft. Enter the dates, venue and RSVP deadline using your normal Frappe user timezone; select the timezone guests should see.
2. For a single-function event, save and open the automatically created **RSVP Function** to set capacity and meal choices. Capacity `0` means unlimited. For several functions, enable Multiple Functions and create each function within the event dates.
3. Add team members to the event and assign each the corresponding Frappe role. Roles alone do not grant access to another organiser's events.
4. Create/import **RSVP Guest** records, then create/import **RSVP Invitation** records linked to the event. Set the maximum number of people per invitation.
5. Publish the event. From **Event Overview**, choose Send email invitations, or use Share on an invitation to copy the private link or share it through WhatsApp.
6. Guests respond online. Organisers can choose **Record response** to use the same form on a guest's behalf.
7. Review confirmations and waiting-list places; export catering requirements.
8. On event day, open **Check-in**, choose the event and function, then scan a pass or search for a confirmed attendee.

## Counts and capacity

An invitation is a household/company booking; an attendee is a person; a function response is that person's place in a particular function. One person attending two functions counts once in Confirmed People and twice in Confirmed Places. Invitation response totals count invitations, not people.

Every state-changing booking/check-in operation locks the event database row. The lock is held until Frappe commits or rolls back the request. Complete API requests retry up to three times on database deadlocks/snapshot conflicts, rolling back the entire failed attempt first. Individual unique keys protect duplicate invitations, attendee/function responses and check-in records.

Waiting-list promotion is FIFO **per person per function**. A family can be partially confirmed; this release does not promise all-or-nothing group allocation. Released places promote existing waitlisted people before new requests. After increasing capacity, use **Promote waiting list** in Event Overview. Guests receive confirmation emails when their places are promoted.

## Roles

| Role | Access |
|---|---|
| System Manager / RSVP Administrator | All events and app settings |
| Event Manager | Own events and events assigned at manager level; guest directory and event setup |
| Event Coordinator | Assigned-event invitation viewing, response entry, communications and reports |
| Check-in Operator | Assigned-event function/attendee lookup and check-in; no dietary/accessibility fields |
| Public guest | Only a validated private invitation through purpose-built endpoints |

The guest directory is a shared resource for event managers. Event team rows must be paired with matching user roles. Coordinators should use response-entry and communication actions; managers maintain the guest directory and create/edit invitation details.

## Email behaviour

Invitation message logs stay **Queued** until the linked Frappe Email Queue reports **Sent**. Hourly reconciliation updates the app log. Sent means accepted by the mail transport, not proven delivery or reading. SMTP retries remain managed by Frappe's Email Queue.

Automatic reminders are disabled initially. Enable them in RSVP Settings and choose the interval. Reminders target unanswered invitations previously sent by email, while the event is published and before its deadline. Bulk send actions deduplicate per purpose/invitation/day.

## Security and privacy

No public role receives DocType CRUD access. Guest endpoints validate invitation access, use explicit response projections, enforce POST and rate limits, and set private/no-store headers. Tokens are placed in URL fragments, so normal page requests and referrers do not include them. Tokens are HMAC-derived from a random per-invitation nonce and the site encryption key; only their hashes are used for lookup. Replacing the nonce invalidates the previous link. Treat both the encryption key and database backups as sensitive.

Entry QR codes have a separate purpose and cannot edit an RSVP. The staff user must be assigned to the chosen event before validating a pass. A pass confirms eligibility; it does not prove the presenter's identity.

Datetimes are stored in the site's normal Frappe timezone. Desk date entry follows each staff user's timezone. The guest portal displays dates in the event timezone, and calendar files use UTC. The retention setting records the organiser's policy; **automatic deletion/anonymisation is not implemented**. Set the privacy notice and manage retention through your approved process.

## Validation

```bash
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
bench --site test_site run-tests --app av_rsvp
```

The CI workflow runs lightweight checks and a separate clean Frappe installation/migration with database integration tests. See [Architecture](docs/architecture.md), [Navigation coverage](docs/navigation.md), and [Acceptance checklist](docs/acceptance.md).

## Later extensions

Public registration, paid tickets/ERPNext accounting, automated WhatsApp messaging, seating plans, offline check-in, multilingual portal translations and custom-question builders are not part of this release. There are no hard-coded links to optional ERPNext DocTypes.

## License

MIT
