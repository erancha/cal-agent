# Testing

Four layers, each proving something the others cannot. Unit tests pin the rules of parsing,
categorizing, sign-in and the task, with the agent's app called in process through the A2A SDK's
client. Integration tests run the Redis adapters on a real Redis, and two agent processes sharing
it as replicas. `validate.sh` starts the agent as an operator would and proves it from the client
side, check by check. The official A2A conformance suite checks the protocol itself. None needs a
model API key, and none reaches Google: the tests sign their own tokens with a key they generate.

**Contents:** [Running](#running) · [Unit](#unit) · [Integration](#integration) ·
[Client-side validation](#client-side-validation) · [Conformance](#conformance) · [CI](#ci)

## Running

| Command | Runs | Needs |
|---|---|---|
| `./scripts/test.sh unit` | Lint (ruff), types (mypy), layer contracts (lint-imports), unit tests, the operator scripts' tests | Python 3.14 |
| `./scripts/test.sh` (or `it`, `all`) | The above with the integration tests | Python 3.14, Docker for Redis |
| `./scripts/validate.sh` | The agent proved from the client side | Python 3.14, openssl |
| `./scripts/validate.sh --tck` | The above, then the A2A conformance suite | as above, plus network to fetch the suite |

Every script builds `.venv` itself on first use, with the runtime dependencies at the exact pins the
image installs.

## Unit

Tests mirror the package's layout under `tests/`. What the unit layer pins, by area:

- **The PDF statement.** On the anonymized test statement, all 19 rows are read with their fields,
  the wrapped merchant, details and sector, the installment, the standing order and the purchase
  abroad among them, and add up to the printed total; a misread total fails with both sums, and a
  PDF without pages fails readably. Hebrew is read back from visual order, Latin words keep theirs,
  columns come from the header, and a word across two columns or an unexpected header fails. When
  `CAL_REAL_STATEMENTS_DIR` names a folder of real statements outside the repo, one more test parses
  each of them against its printed total; otherwise it is skipped.
- **The test statement itself.** It holds the stand-ins and none of the private values, still reads
  as 19 rows and the total, and the anonymizer's leftover check finds a private word wherever it
  falls.
- **Statement folders and the page.** Lookup by the month a file declares, whatever its name; two
  files for one month, a name disagreeing with the content, and an unreadable file each fail
  naming the file; a file is parsed again only when it changes; each person sees only their own
  folder; an upload lands only in the person's folder under its month's name, refused uploads
  write nothing and name an unreadable neighbour; the API's 401, 400 and 413 answers, an oversized
  body cut off while it arrives, and a path-like delete that deletes nothing.
- **Categorizing.** Each merchant is asked once, in batches, and remembered; scores become
  confidence levels at the two thresholds; any answer outside the taxonomy or the score range is
  `uncategorized` and `low` and is not remembered; a wrong answer count fails; a changed sector or
  taxonomy asks again; repeated merchants keep their own answers in order. The prompt carries every
  category's guide. Against fake provider clients, each adapter forces the answer's schema, and a
  truncated, refused, malformed or failed reply is a readable classifier failure.
- **Sign-in.** Expired, foreign-audience, foreign-issuer, tampered, unsigned, key-id-less and
  claim-less tokens are refused naming a cause a person can act on; a page token and a forwarded
  caller token are each checked against their own client id; the callers file refuses an empty
  list, a blank field and a shared secret or name.
- **The task.** The app runs in process on the SDK's in-memory store and is called through the
  SDK's client: a covered month streams its 19 rows on one artifact and completes; an empty
  statement sends one empty chunk and 26 rows two chunks; both pauses carry their data parts;
  `continue` completes once the file lands and pauses again without it; a malformed month, a
  `continue` on a completed task and a month on a paused one are `InvalidParams`, the first leaving
  no task; a `continue` while another call holds the lease is refused; a `continue` by the same
  person after signing in completes and one by another account pauses for sign-in; a token issued to
  another registered caller's client pauses for sign-in, and that caller cannot find, let alone
  continue, the first caller's task; a wrong secret is 401 before JSON-RPC; a parse failure fails
  the task with its cause; cancel; the lease is held, renewed and released under an owner per call.
  Every request, batch and pause validates against the contract's pinned JSON Schemas.
- **Startup.** Each wrong required setting fails naming the variable, without printing the model
  key, and so do a lease period or batch size below one and confidence thresholds out of order; the
  conformance executor forces auth off and refuses a shared Redis or a callers file; `.env.example`
  documents every setting, and only the edge publishes a port. The sweep retries a pass that cannot
  reach Redis and stops on any other error, and `/health` then answers `DOWN`.
- **Operator scripts.** `scripts/tests/*.sh` check the hand-over lines, `.env` loading, caller
  registration, the callers-file guard, the statements root `start.sh` creates and
  `docker-helper.sh`'s refusals.

## Integration

These start Redis in Docker through Testcontainers.

- **The Redis adapters**, each on its own: the task store (a first save read back at version 1, a
  stale save and another caller's save refused, a cancel overwriting only a live task, the time to
  live, listing by state, the working scan across callers), the event stream (a subscriber gets the
  events after its version up to the end, a late event within a second, a destroyed stream fails
  an unfinished subscriber), the lease (one owner at a time, only the owner renews or releases),
  the merchant memory per person, and the sweep failing a task unleased on two passes while
  leaving a leased or changed one.
- **Two replicas**: two agent processes sharing one Redis and one statements folder, called over
  HTTP, the first on fixed port 18030 since the card advertises the URL the client calls. A month
  that pauses on the first completes when `continue` is sent to the second; a `SubscribeToTask`
  sent to the second while the first runs the task streams the first's events; a replica killed
  mid-task leaves a failed task and the month fetchable again; two continues sent at once run the
  task once.

## Client-side validation

`validate.sh` starts the agent on port 8031 with `LLM_MODEL=keyword`, a throwaway signing key
standing in for Google, the test statement in person `1000`'s folder and a caller registered by
`register-caller.sh`, and drives it with `scripts/validate/check_agent.py`, a client on the A2A
SDK playing that caller. It prints one `PASS` line per check, 19 in all, and stops at the first
failure:

1. The card advertises `monthly-transactions`,
2. streaming,
3. the person's token as an OpenID Connect scheme,
4. and the caller's secret as an API key in `X-Caller-Secret`.
5. `2026-10` completes,
6. streaming 19 transactions,
7. each carrying a category.
8. `2026-09` asks for input,
9. with the reason `statement-missing`,
10. naming the person.
11. `continue` without the file asks again.
12. Cancel of the waiting task succeeds,
13. and cancel of the completed task is refused.
14. A call without the person's token ends in auth-required with `sign-in-required`,
15. and so does a call with a token issued to another client.
16. A wrong secret is 401.
17. The auth config names the page's client.
18. The statements API refuses a call without a token,
19. and lists the person's own statement with one.

It then boots the agent on port 8033 once per real model provider with a placeholder key, which
proves each provider's client library ships in the pinned dependencies. It refuses to start while
one of its ports already answers, so it never validates an agent left over from an interrupted
run.

## Conformance

`./scripts/validate.sh --tck` also runs the official
[A2A conformance suite (TCK)](https://github.com/a2aproject/a2a-tck) against a second agent on port
8032, over JSON-RPC, at the MUST level: the requirements mandatory for conformance. The suite sends
scripted messages and expects scripted answers no card agent would give, and sends no credentials,
so this agent runs with `A2A_EXECUTOR=tck`, auth off and a scenario executor in place of the
card's. The suite therefore proves the protocol; the tests and `validate.sh` prove the card work.
The script fetches the suite into `.tck/` and leaves its reports in `.tck/reports/`.

## CI

`.github/workflows/ci.yml` runs on every push and pull request: `scripts/test.sh all`, which
includes the operator scripts' tests, then `validate.sh`. CI calls the same scripts developers run,
so the two cannot drift. The conformance suite runs locally through `validate.sh --tck`.
