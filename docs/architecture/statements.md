# Statements

Where a person's statements live, how the Cal statement PDF is read, and the page that loads them.
The agent reads only statements a person loaded themselves; it never logs in to the card site.

## One folder per person

`STATEMENTS_DIR` is a root with one folder per person, named by their Google account id and
created by their first upload. A folder's statements are indexed by the billing month their
content declares, not by their file names:

- Every lookup rescans the folder, so a file loaded while a task waits is found on `continue`. A
  file is parsed again only when its size or modification time changes, so each statement is
  parsed once however often its month is asked for.
- Two files for one billing month fail the lookup, naming both: silently preferring one would hide
  a mismatch (`has 2 statements for 2026-10, a.pdf and b.pdf; keep one`).
- A file whose name holds a month, such as `2026-10.pdf`, but whose content declares another fails,
  naming the file and both months (`could not use 2026-10.pdf: it is named for 2026-10 but holds
  2026-09`).
- A PDF that fails to parse fails the lookup naming the file, followed by the parser's reason
  (`could not read 2026-10.pdf: it has no pages`). Files that are not PDFs are ignored.

Each of these texts is a predicate that reads after the agent's name, since a caller shows a
failure as `<agent> <text>`.

## The Cal statement

A Cal monthly statement is a Hebrew, right-to-left PDF. Its title, `דף חיוב חודשי ל-02/10/26`,
gives the charge date, and the charge date gives the billing month (`2026-10`) and every row's
`chargeDate`. One table lists the charges, with these columns from the right: purchase date
(`DD/MM/YYYY`), merchant, the issuer's sector label (`מזון ומשקא`, `מסעדות`, `בתי כלבו`...),
details, whether the card was presented, the transaction amount, the charged amount, and a
Shufersal-benefit mark. Every column is right-aligned. A longer month continues the table on the
next page under a header of its own, and the table ends in a total line,
`סה"כ לתאריך 02/10/26 ₪ 13,986.22`.

The details cell carries, in any combination, an installment (`תשלום 3 מ - 3`, payment 3 of 3), a
standing order (`הוראת קבע`), a digital wallet's card token, a fee marker, or the country of a
merchant abroad, written as a word ending in a period (`אירלנד.`). The transaction amount differs
from the charged amount only on installments, where it is the purchase price and the charged amount
this month's payment.

A cell longer than its column wraps: the next line holds only the remainder, under the same column,
with no date and no amounts. Merchants, details and sector labels all wrap this way.

Text extraction returns Hebrew in visual order: each Hebrew word's letters are reversed, and the
words of a cell run left to right. Latin words (`Temu.com`) come out in logical order.

## Reading the PDF

The parser reads the words of each page with pdfplumber, with their positions, and works from
those positions rather than from the extracted lines, since the text is visual-order Hebrew in
right-aligned columns:

- **Lines.** Words whose tops lie within 3 pt of a line's first word sit on that line, so a cell
  drawn a point or two off its row stays on the row; table lines are about 10 pt apart, so a
  wrapped cell's next line stays a line of its own.
- **Columns.** The table's two header lines are found by their words, and the right edge of each
  column's rightmost header word fixes that column's right edge. A word belongs to the column whose
  edge it ends at; a word reaching across two columns fails the parse. The page's side panel runs
  down the far left, beside the table, so its words fall in the benefit column.
- **Reading order.** Each cell is read back into logical order: its words taken right to left,
  each word holding Hebrew letters reversed, a number inside a Hebrew word kept as written, and a
  run of Latin words kept in its own left-to-right order, so `Google Pay` stays `Google Pay`.
- **Rows.** A line with a date in the date column starts a row and must carry a charged amount. A
  line with no date and no amounts continues the previous row: each of its words extends the cell
  of the column it sits under, joined with a space. A line with amounts but no date, or a
  continuation before any row, fails the parse naming the line.
- **Fields.** Per row: the purchase date, the merchant cell exactly, the sector label kept beside
  the row as the categorizer's hint, the charged amount, an installment's number and total, a
  standing-order mark, and the abroad mark when the details open with a word ending in a period.
  The transaction amount, the card-presented mark and the benefit mark are read and dropped, and
  so are the side panel's words. An amount in the benefit column fails the parse naming it, since
  it is a charge's amount drawn out of its column, never a mark.

A month comes back whole or not at all. Rows are read until the total line, across pages, and the
charged amounts must add up to the printed total, so a row that is lost or misread fails the parse
with both sums instead of quietly shrinking the month. The statement prints no voucher numbers, so
a row's id is the charge date and the row's position, `20261002-01`: stable for one file and
unique across months.

The test statement, `tests/statements/2026-10.pdf` (19 rows), is a real statement with the
holder's private details replaced by `scripts/anonymize-statement.py`. The Cal PDF draws some words
one glyph at a time and others whole, under one embedded font that holds several glyphs of
different widths for one character, so the script finds each private word in the page's text
joined in drawing order, redraws each character of its stand-in with the glyph closest in width to
the one it replaces, and adjusts the character spacing so the word keeps its original width. Text
extraction therefore sees the same columns as in the real file. The mapping of private words to
stand-ins never enters the repo, and the run fails when any private word is still in the output.

## The statements page

`/statements.html` is a single static page where a person signs in with Google, loads statement
PDFs into their own folder and deletes them. It does nothing else: reading, categorizing and
reviewing a month stay with the A2A skill and its callers. The page reads this agent's Google
client id from `GET /api/auth/config`, keeps the ID token in memory only and sends it as the bearer
token of every API call; a 401 brings the sign-in button back.

| Request | Answer |
|---|---|
| `GET /api/statements` | The person's statement files: `fileName`, `sizeBytes`, `modified`. |
| `POST /api/statements`, multipart part `file` | 201 with the stored file; 400 for a refused file, 413 over the 5 MB upload limit, each a problem document whose `detail` names the cause. |
| `DELETE /api/statements/{fileName}` | 204; 400 when no listed statement has that name. |
| any of the above without an acceptable token | 401 with `WWW-Authenticate: Bearer`. |

An upload is refused when it is not a PDF, does not parse as a Cal statement, or is for a month
another file already covers; a statement already loaded is not replaced, so the person removes the
old file first. An upload is refused too while another file in the folder cannot be read, naming
that file, since the month it covers cannot be checked. Every check runs on a hidden temporary
file in the person's folder, which is then linked under the name of the billing month it declares,
whatever it was called. So a lookup never sees a partial or refused file, an uploaded name can
never place a file outside the folder, and two uploads for one month never overwrite each other.
An upload over the limit is cut off while it arrives. A delete does not read the file, so a broken
or duplicate file that blocks the folder can still be removed.

A task waiting for a missing statement names this page in its input-required data part, so a caller
can link the person straight to it; signing in there with the same Google account lands them in the
same folder the task reads.
