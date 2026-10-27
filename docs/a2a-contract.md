# A2A contract: how cal-agent implements it

The `monthly-transactions` skill has one contract for every card agent, owned by its caller, and
the caller publishes it. The demo's caller, the home finance agent, keeps it at
[docs/a2a-contract.md in its repo](https://github.com/erancha/home-finance-agent/blob/main/docs/a2a-contract.md);
it defines the transport, the agent card, the request, the stream, the row schema, the taxonomy,
the pauses and the two credentials, and publishes the request, row and pause shapes as JSON
Schemas. This page describes only what is cal-agent's own: the endpoint and its headers, the
card's values, the exact texts and artifact naming it puts on the wire, how it fills each row, how
it checks the credentials, and the errors it answers with.

**Contents:** [Transport](#transport) · [Agent Card](#agent-card) · [Request](#request) ·
[Task lifecycle](#task-lifecycle) · [Pauses and resume](#pauses-and-resume) ·
[Cancel](#cancel) · [Rows](#rows) · [Authentication](#authentication) · [Errors](#errors)

## Transport

- One endpoint: `POST /` at the agent's base URL (`http://localhost:8030` by default), served by
  the routes of the official A2A Python SDK (`a2a-sdk`).
- Every JSON-RPC request carries `Content-Type: application/json` and `A2A-Version: 1.0`. Without
  the version header the SDK treats the request as an older protocol version and answers
  `VersionNotSupported` (-32009).
- `SendStreamingMessage` and `SubscribeToTask` answer with `text/event-stream`: one SSE frame per
  event, each `data:` line holding a JSON-RPC response with the same `id` as the request. Every
  other method answers with one JSON document.
- A request refused before its task exists (a malformed month, a `continue` that cannot run)
  answers with a plain JSON-RPC error document, not a stream. An error raised while the task
  works (a statement that does not parse, a model provider error) arrives on the stream as a frame
  of type `event: error` holding a JSON-RPC error, after which the stream ends.
- Every JSON-RPC error travels with HTTP 200. The only non-200 answer on `POST /` is the 401 of the
  caller-secret check.
- The skill is served by `SendStreamingMessage` only. The blocking `SendMessage` is refused with
  `UnsupportedOperation` (-32004), message `this agent only streams; use SendStreamingMessage`:
  a `continue` takes the task's lease before the task resumes and hands it to the run on the
  stream (see [scaling.md](architecture/scaling.md#the-lease)).

## Agent Card

`GET /.well-known/agent-card.json`, unauthenticated, `Cache-Control: max-age=3600, public`.

| Field | Value |
|---|---|
| `name` | `Cal (Israel Credit Cards) card agent` |
| `version` | The package version, from `pyproject.toml` |
| `supportedInterfaces` | one entry: `protocolBinding: "JSONRPC"`, `url` = `AGENT_URL` (default `http://localhost:<SERVER_PORT>`), `protocolVersion: "1.0"` |
| `capabilities` | `streaming: true`, `pushNotifications: false` |
| `defaultInputModes` / `defaultOutputModes` | `application/json`, `text/plain` / `application/json` |
| `securitySchemes` | `google`: OpenID Connect scheme, `openIdConnectUrl` `https://accounts.google.com/.well-known/openid-configuration`, the signed-in person's Google ID token sent as the bearer token; `caller`: API key scheme, `location: "header"`, `name: "X-Caller-Secret"`, the caller's registered secret. Present only when `A2A_AUTH_REQUIRED=true` |
| `securityRequirements` | one requirement naming both `google` and `caller`: every call carries both; present only when `A2A_AUTH_REQUIRED=true` |

One skill:

| Field | Value |
|---|---|
| `id` | `monthly-transactions` |
| `name` | `Monthly card transactions` |
| `description` | Names the full taxonomy, rendered from the agent's taxonomy value, and the request and resume shapes |
| `inputModes` / `outputModes` | `application/json`, `text/plain` / `application/json` |
| `tags` | `finance`, `credit-card`, `transactions` |
| `examples` | `{"month": "2026-10"}` |

A client calls the `url` in `supportedInterfaces`, not the address it fetched the card from, so
`AGENT_URL` must be the address clients reach.

## Request

`SendStreamingMessage` with a user message naming a billing month:

```http
POST / HTTP/1.1
Content-Type: application/json
A2A-Version: 1.0
Authorization: Bearer <the signed-in person's Google ID token>
X-Caller-Secret: <the caller's registered secret>

{"jsonrpc": "2.0", "id": 1, "method": "SendStreamingMessage",
 "params": {"message": {"messageId": "<client-chosen id>", "role": "ROLE_USER",
                        "parts": [{"data": {"month": "2026-10"}}]}}}
```

- A message carries one data part, `{"month": "YYYY-MM"}` or `{"action": "continue"}`; a data part
  of any other shape, or a second data part, is refused.
- A message with no data part may name the month in a text part instead
  (`"transactions for 2026-10"`).
- A month in any other shape (`2026-9`, `09/2026`, `2026-13`) is refused with `InvalidParams`
  (-32602), message `'2026-9' is not a billing month; expected YYYY-MM`, never read as a nearby
  month. A message with no usable part is refused the same way. No task is created for a refused
  request.

## Task lifecycle

A covered month produces these events, in order, on one stream:

1. `task`: the new task in `TASK_STATE_SUBMITTED`, holding the caller's message.
2. `statusUpdate` `TASK_STATE_WORKING` with an agent message holding the text part
   `Parsing statement for 2026-10`.
3. One or more `artifactUpdate` events, each carrying one data part (see [Rows](#rows)) with up to
   25 transactions. All chunks of a task share one `artifactId` (`transactions-<taskId>`) and the
   name `transactions`; `append` is false on the first chunk and true after it, and `lastChunk` is
   true on the final one. A statement with no rows still produces one chunk with an empty
   `transactions` list.
4. `statusUpdate` `TASK_STATE_COMPLETED`. The server then ends the stream.

One frame of the stream, abridged:

```text
data: {"result": {"statusUpdate": {"taskId": "fe07…", "contextId": "ecc6…",
       "status": {"state": "TASK_STATE_WORKING", "message": {"role": "ROLE_AGENT",
       "parts": [{"text": "Parsing statement for 2026-10"}], …}}}}, "id": 1, "jsonrpc": "2.0"}
```

Status updates carry no `final` flag. `TASK_STATE_COMPLETED`, `TASK_STATE_CANCELED` and
`TASK_STATE_FAILED` are terminal; `TASK_STATE_INPUT_REQUIRED` and `TASK_STATE_AUTH_REQUIRED` are
interrupted states, so the task stays alive, but the agent ends the stream right after either
event.

When reading or categorizing fails, the stream ends with an `event: error` frame,
`InternalError` (-32603), whose message is the cause written to follow the agent's name, and the
task is left in `TASK_STATE_FAILED`. For example `could not read 2026-10.pdf: its charges add up
to 13986.22 but it prints a total of 5.00`, `has 2 statements for 2026-10, 2026-10.pdf and
statement.pdf; keep one`, or `got 3 answers from the model for 4 merchants`.

A replica that stops while a task works leaves the task `TASK_STATE_WORKING` with no lease; within
three lease periods (three minutes by default) a replica's sweep marks it `TASK_STATE_FAILED` with
the status text
`stopped while reading 2026-10; start the review again` (see
[scaling.md](architecture/scaling.md#the-sweep)).

`SubscribeToTask` with the task id streams a working task from whichever replica receives it: the
stream opens with the task as stored and follows the events of the replica running it, until the
task completes, fails or pauses.

## Pauses and resume

Each pause's status message holds a text part for the person and one data part that names the
reason, the month and the person the task is for, so the task itself remembers everything a
resume needs.

**Missing statement.** When no statement file of the person covers the month, the task goes from
`TASK_STATE_WORKING` to `TASK_STATE_INPUT_REQUIRED`:

```json
{"role": "ROLE_AGENT", "parts": [
  {"text": "No statement covers 2026-09."},
  {"data": {"reason": "statement-missing", "month": "2026-09", "page": "/statements.html",
            "user": "1000"}}
]}
```

`page` is always `/statements.html`, the statements page on the agent's own base URL; `user` is
the Google account id (`sub`) of the person, from the token the caller forwarded.

**Sign-in required.** When the request carries no acceptable token for the person (none, expired,
badly signed, or issued to a client other than the caller's registered one), the task goes to
`TASK_STATE_AUTH_REQUIRED` right after it is submitted, before any work:

```json
{"role": "ROLE_AGENT", "parts": [
  {"text": "could not verify who you are (the sign-in has expired); sign in again and continue"},
  {"data": {"reason": "sign-in-required", "month": "2026-09", "user": ""}}
]}
```

The text follows the agent's name, and the parenthesis names the cause, one of:

- `no sign-in token came with the request`
- `the Authorization header is not a bearer token`
- `the sign-in has expired`
- `the token was issued for another application`
- `the token was not issued by https://accounts.google.com`
- `the token is not valid: <detail>`
- `could not fetch Google's signing keys: <detail>`

`user` is the person the task was already bound to, or `""` when no person has been verified yet;
a task whose pause names `""` serves the first verified person who continues it. A `continue`
whose token names another Google account than the pause's `user` gets the same answer, with the
cause `a different Google account signed in than the one this review was started for`; the task
serves only its own person.

After either pause the agent ends the stream, so a waiting task holds no connection.

To resume, the client sends a new message on the same `taskId` and `contextId`, with the
person's current token and the caller's secret as on every call:

```json
{"jsonrpc": "2.0", "id": 2, "method": "SendStreamingMessage",
 "params": {"message": {"messageId": "<new id>", "role": "ROLE_USER",
                        "taskId": "<waiting task id>", "contextId": "<its context id>",
                        "parts": [{"data": {"action": "continue"}}]}}}
```

- The task must be in `TASK_STATE_INPUT_REQUIRED` or `TASK_STATE_AUTH_REQUIRED`; a message on a
  task in any other state is refused with `InvalidParams` (-32602), message `task <id> is
  TASK_STATE_COMPLETED; only a task waiting for input or sign-in can continue` (or the state it is
  in). A message on a paused task that is not a `continue`, and a `continue` without a `taskId`,
  are refused the same way.
- Of two `continue` messages for one task, only the first runs it; the other is refused with
  `UnsupportedOperation` (-32004), message `task <id> is already running`.
- The agent reads the month and the person back from the task's own pause message (the current
  status message first, then the history newest first), so the client does not repeat the month.
- The agent checks the token, then rescans the person's folder. The stream shows
  `TASK_STATE_WORKING` and then either the artifact chunks and `TASK_STATE_COMPLETED`, or
  `TASK_STATE_INPUT_REQUIRED` again with the same message; a token problem shows
  `TASK_STATE_AUTH_REQUIRED` instead.

## Cancel

`CancelTask` with `{"id": "<taskId>"}`:

- A task paused in `TASK_STATE_INPUT_REQUIRED` or `TASK_STATE_AUTH_REQUIRED` moves to
  `TASK_STATE_CANCELED`; the result is the task.
- A terminal task (`TASK_STATE_COMPLETED`, `TASK_STATE_CANCELED`, `TASK_STATE_FAILED`) is refused
  with `TaskNotCancelable` (-32002), message `Task cannot be canceled`.

## Rows

Each artifact chunk carries one data part in the contract's row schema,
`{"month": "2026-10", "currency": "ILS", "transactions": [...]}`. Numbers are JSON numbers
(`796.0`), never strings. How cal-agent fills the fields:

| Field | Source |
|---|---|
| `currency` | Always `ILS`. |
| `id` | The charge date and the row's position on the statement (`20261002-01`), stable across runs of the same file and unique across months. |
| `transactionDate` | The row's purchase date. |
| `chargeDate` | The charge date in the statement's title, the same for every row. |
| `merchant` | The display name chosen by the categorizer. |
| `rawMerchant` | The merchant cell exactly as printed, a cell that wraps onto a second line joined with a space. |
| `amount` | The charged amount; for an installment, this month's payment, not the purchase price. |
| `originalAmount`, `originalCurrency` | Always `null`: the statement prints no purchase amount in another currency, and `abroad` marks a merchant abroad. |
| `standingOrder` | True when the row's details read `הוראת קבע`. |
| `abroad` | True when the first word of the row's details ends in a period, the country of a merchant abroad, as `אירלנד.`. |
| `installment` | `{"number": 3, "total": 3}` from the details' `תשלום 3 מ - 3`; `null` otherwise. |
| `category`, `confidence` | The categorizer's answer; every other field comes from the statement without a model call. |

The model's score stays inside the agent: from `CATEGORIZER_HIGH_CONFIDENCE` up it is reported as
`high`, from `CATEGORIZER_MEDIUM_CONFIDENCE` up as `medium`, below that as `low`. A `low` row keeps
the agent's best guess as its category, so the caller can confirm or correct it. A model answer
outside the taxonomy or the score range is `"category": "uncategorized"` with `low` confidence.

The tests validate every request, batch and pause the agent sends against pinned copies of the
contract's JSON Schemas in `tests/contract/`.

## Authentication

Every A2A call carries the contract's two credentials, and the card says so (see
[Agent Card](#agent-card)):

- `X-Caller-Secret: <secret>` proves which registered caller sends the request. Callers are
  registered by the agent's operator in `allowed-callers.yaml` (`scripts/register-caller.sh`), each
  with a name, the secret it presents and the Google OAuth client id whose tokens it forwards. The
  secret is compared in constant time against every entry; a missing or unknown secret gets HTTP
  401 with `WWW-Authenticate: X-Caller-Secret` and an empty body, before any JSON-RPC handling.
- `Authorization: Bearer <Google ID token>` says which person the call is for: the token the
  person received when signing in to the caller's own page with Google, forwarded as received. The
  agent verifies it itself: RS256 signature against Google's published keys, issuer
  `https://accounts.google.com` (or `accounts.google.com`), expiry, and audience equal to the
  caller's registered client id. The token's `sub` is the person's id: their statements live in
  the folder of that name. A token that fails any check does not refuse the request; the task
  pauses in `TASK_STATE_AUTH_REQUIRED` (see [Pauses and resume](#pauses-and-resume)) so the caller
  can have the person sign in again and continue the same task.

A task belongs to the caller that started it, and the task's pause names its person. Another
caller asking for the task gets `TaskNotFound`; another person continuing it through the same
caller gets `TASK_STATE_AUTH_REQUIRED`.

The statements page's own API, `/api/statements`, takes the person's token alone, issued to this
agent's own client (`AUTH_CLIENT_ID`); without an acceptable one it answers 401 with a problem
document. `GET /.well-known/agent-card.json`, `GET /health`, `/statements.html` and
`GET /api/auth/config` are open.

With `A2A_AUTH_REQUIRED=false` neither credential is read, the card declares no security scheme,
and every request is for the one person `anonymous`.

A note on trust: cal-agent honors a Google token that was issued to a partner's client. That is
what two services trusting the same identity provider do under one roof; an agent operated by a
separate company would more likely issue tokens of its own after verifying the person (OAuth 2.0
token exchange) and advertise an OAuth 2.0 scheme instead.

## Errors

| Code | SDK error | When |
|---|---|---|
| -32700 | `JSONParseError` | The body is not valid JSON. |
| -32600 | `InvalidRequestError` | Valid JSON that is not a well-formed JSON-RPC request. |
| -32601 | `MethodNotFoundError` | An unknown method name. |
| -32602 | `InvalidParamsError` | A malformed month, an unusable message, or a message on a task that is not paused. |
| -32603 | `InternalError` | The agent failed while working on the task, or an unexpected server error. |
| -32001 | `TaskNotFoundError` | No task of this caller has the given id. |
| -32002 | `TaskNotCancelableError` | `CancelTask` on a terminal task. |
| -32004 | `UnsupportedOperationError` | The blocking `SendMessage`, or a `continue` for a task another request is already running. |
| -32009 | `VersionNotSupportedError` | The `A2A-Version: 1.0` header is missing or names another version. |

An error body is a JSON-RPC error object with `code` and `message`; all but the first and third
carry a `data` list holding a `google.rpc.ErrorInfo` whose `reason` names the error (for example
`INVALID_PARAMS`).
