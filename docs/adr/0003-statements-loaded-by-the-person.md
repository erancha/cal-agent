# 0003. Statements are PDFs the person loads into a folder of their own

- Status: Accepted
- Date: 2026-10-27

## Context

Cal publishes each monthly statement as a Hebrew, right-to-left PDF on its site, behind the
cardholder's own login. The agent needs one person's statement for one billing month, and the
caller asks for it by month, not by file. Logging in to the card site on a person's behalf would
mean holding their card-site credentials. Several replicas must see the same files, and a file
loaded while a task waits must be found when the task continues.

## Decision

- A statements root, `STATEMENTS_DIR`, mounted into every replica, with one folder per person,
  named by their Google account id.
- A static page of the agent, `/statements.html`, where a person signs in with Google and loads
  or deletes their own PDFs; each upload is checked, then stored under the billing month its
  content declares, whatever the file was called.
- Every lookup rescans the person's folder and maps each PDF to the month it declares; a file is
  parsed again only when it changes.
- The parser reads pdfplumber's words by their positions, and a month's rows must add up to the
  total the statement prints, or the request fails.
- A missing statement pauses the task with a link to the page, rather than failing it.

## Consequences

- The agent never holds card-site credentials and never logs in to the card site.
- The person downloads each statement by hand; the caller's review waits for it.
- Two files for one month, or a file named for another month than it holds, fail the lookup
  naming the files, so a mismatch is never hidden.
- A change to Cal's PDF layout fails the parse loudly instead of shrinking the month.
