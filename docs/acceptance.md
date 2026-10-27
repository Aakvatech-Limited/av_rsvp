# Acceptance checklist

Run on a disposable Frappe v16 site before production use.

1. Install, migrate, build assets and verify AV RSVP appears on Apps, Dock and Sidebar. Open each shipped report and page.
2. Create a single-function event and verify the default function inherits its dates/venue. Enter a capacity and meals.
3. Import guests and invitations, including a family with an allowance of four. Verify duplicate event/guest invitations are rejected.
4. Publish and open a private invitation in an incognito session without a user account. Verify the form at phone and desktop widths.
5. Confirm three people. Check per-function allocations, meal totals, passes and calendar timezone conversion. Change one person to Maybe or Declined.
6. At capacity, submit two invitations concurrently from separate browser sessions. Verify capacity is never exceeded and the excess request is waitlisted or rejected according to settings.
7. Cancel a confirmed place and verify FIFO promotion. Verify no whole-family allocation is implied.
8. Verify one invitation cannot edit another's attendee IDs, an expired/replaced/revoked token fails, and public generic DocType APIs are inaccessible.
9. Create users for each staff role. Verify unrelated events are inaccessible through lists, forms, reports and direct API calls. Verify a check-in operator cannot read dietary/accessibility fields or invitation details.
10. Send actual test emails through the configured outgoing account. Verify Queued/Sent status follows Email Queue and repeated daily bulk actions do not duplicate messages. Exercise a missing/invalid outgoing account and retry through Frappe Email Queue.
11. Enable reminders and run the daily scheduler on eligible pending invitations. Confirm no reminders for responded, expired, revoked or cancelled events.
12. Scan an entry pass on an HTTPS phone browser, scan it twice, reverse with a reason, then check in again. Inspect Version history. Verify waitlisted/foreign-function passes cannot enter.
13. Change an RSVP after check-in and verify cancellation requires reversal. Cancel the event and verify check-in closes.
14. Review CSV formula escaping, guest counts versus invitation counts, report exports, privacy notice and operational retention policy.

Lightweight local tests validate business rules, calendar output and metadata without Frappe. Database integration tests are run by the dedicated CI job; a mocked browser check is useful for UI behaviour but does not replace installed-site acceptance or a concurrent-user load test.
