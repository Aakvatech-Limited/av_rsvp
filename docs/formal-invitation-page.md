# Formal invitation page

The optional `av_rsvp/templates/formal/` assets provide an ivory, navy and gold
invitation layout for an existing native Frappe Web Page. They include an uncropped
event emblem, the full personal message, event details and directions, and three
radio blocks labelled **Attending**, **Not attending**, and **May be**. The Maybe
choice follows the event's Allow Maybe setting. Pending invitations require an
explicit attendance selection.

The message, closing, questionnaire, saved answers, contact information, deadline,
and guest allowances continue to come from the event and invitation APIs. The
questionnaire supports the existing Select, Check, Long Text and text questions.
The footer closing appears beneath the personal message. Existing private links
and saved responses continue to work; the template does not contain guest tokens.

To use this design for an existing event:

1. Back up its linked Web Page's HTML, CSS and JavaScript fields.
2. Copy `av_rsvp/templates/formal/invitation.html` to the page's HTML field and
   replace `__EVENT_ID__` with that event's document name. Keep `#rsvp-root` and the
   information template bindings intact.
3. Copy `invitation.css` and `invitation.js` to the page's CSS and JavaScript fields.
   Enable Insert Style and Full Width, and disable Show Title.
4. Keep the page's existing route and Published setting. Save and clear the
   website cache, then check an existing private link on desktop and mobile.

Use a public site-relative image path, such as `/files/emblem.png`, in the event's
Banner field, as required by the public RSVP API. The page remains editable through
Web Page; installing or updating this app does not overwrite existing page designs.

## Email content and public links

Invitation emails use the event Description as the personal message and Footer Text
as the only closing. Generic wording is used when those fields are empty. The
centred, responsive 600px email includes the event emblem, dates in the event
timezone, venue, RSVP deadline, personal button and organiser contacts. Reminder
and confirmation emails retain their respective wording and allocation details;
confirmed attendance still includes the calendar attachment.

All RSVP emails include an automated-email notice and a private-link reminder.
Emails already sent are unchanged. These changes do not resend invitations or
change the bulk-send action's existing daily deduplication behaviour.

Configure `host_name` with the externally reachable site address, including HTTPS.
RSVP links now respect that address without adding an internal development port.
An explicitly configured public port is preserved; unconfigured sites retain the
normal Frappe URL fallback.

## Validation

```sh
python -m unittest discover -s tests -v
node tests/formal-page.cjs
```

The browser check uses mocked API calls and anonymous event data. It checks three
viewport widths, explicit response selection, all response mappings, questionnaire
answers, existing responses, closed invitations and horizontal overflow. It does
not submit responses to a live site or send email.
