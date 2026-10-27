# Navigation coverage

All entries belong to the RSVP module, exposed through the AV RSVP Apps entry, an app-owned Dock and a curated RSVP Sidebar. Standard files are shipped as source; they were not exported from a live development site. Site/user arrangements are never reset by a patch.

| Target | Type | Workspace | Sidebar | Access |
|---|---|---|---|---|
| RSVP | Workspace | Landing | Home | App roles |
| rsvp-overview | Page | Operations/shortcut | Operations | Manager/coordinator |
| RSVP Event | DocType | Operations/shortcut | Operations | Assigned event; managers maintain |
| RSVP Invitation | DocType | Operations | Operations | Manager/coordinator |
| RSVP Attendee | DocType | Operations | Operations | Assigned event; service writes |
| RSVP Function Response | DocType | Operations | Operations | Assigned event; service writes |
| rsvp-checkin | Page | Operations/shortcut | Operations | Assigned event team |
| RSVP Guest | DocType | Masters | Masters | Manager/shared directory |
| RSVP Function | DocType | Masters | Masters | Assigned event; managers maintain |
| RSVP Guest Register | Report | Reports | Reports | Manager/coordinator |
| RSVP Catering Requirements | Report | Reports | Reports | Manager/coordinator |
| RSVP Check-in Register | Report | Reports | Reports | Assigned event team |
| RSVP Settings | Single | Settings | Settings | Administrator |
| RSVP Message Log | DocType | Settings | Settings | Manager/coordinator; service writes |
| RSVP Event Team | Child table | Excluded | Excluded | Maintained within event |

The event overview implements live KPIs directly. This release does not ship standard Dashboard, Dashboard Chart, Chart Source or Number Card records. Those are intentionally excluded; the overview page is the analytics destination.

Native export paths:

- `av_rsvp/rsvp/workspace/rsvp/rsvp.json`
- `av_rsvp/rsvp/sidebar/rsvp/rsvp.json`
- `av_rsvp/dock/av_rsvp/av_rsvp.json`

After installation/migration, verify Workspace, Sidebar and Dock exist independently. Existing personal Dock arrangements may require enabling the RSVP module. Test an administrator, event manager, coordinator and check-in operator separately; navigation visibility does not replace server permission checks.
