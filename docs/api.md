# API endpoints

This document details every route behind the entry points that
[Architecture](architecture.md#the-parts) summarizes: who may call it, what it takes and answers,
and its limits. Callers reach the `cal-agent` replicas over A2A, and people reach them through
the statements page; both pass through the `edge` service, which serves no route of its own and
passes each one on to a replica. The work no request waits on is in
[Workers' responsibilities and flows](workers.md).

## Agent HTTP API (`cal-agent` service)

FastAPI in `src/calagent/platform/`: `app.py` mounts the A2A SDK's routes and the health route,
and `statements_api.py` adds the statements page and its API. The Agent Card, the page, its
sign-in configuration and the probe are open; every other route needs the credentials its section
names.

### A2A

The skill's endpoint and the card that advertises it, served by the routes of the official A2A
Python SDK; [A2A contract](a2a-contract.md) holds the protocol, the methods and the errors.

- `POST /` — the JSON-RPC endpoint, with SSE streaming, for a registered caller acting for a
  signed-in person ([Transport](a2a-contract.md#transport),
  [Authentication](a2a-contract.md#authentication)).
- `GET /.well-known/agent-card.json` — the Agent Card, open to anyone and publicly cacheable for
  an hour ([Agent Card](a2a-contract.md#agent-card)).

### The statements page

The statements page's own API, `/api/statements`, takes the person's token alone, issued to this
agent's own client (`AUTH_CLIENT_ID`), and acts only on the folder of that person's Google account
id ([One folder per person](architecture/statements.md#one-folder-per-person)). Without an
acceptable token it answers 401 with `WWW-Authenticate: Bearer`, and each refusal is a problem
document whose `detail` names the cause. What the page does with these routes, and when an upload
is refused, is in [The statements page](architecture/statements.md#the-statements-page).

- `GET /statements.html` — the page itself, a static file; open.
- `GET /api/auth/config` — this agent's Google client id for the page, `clientId`; open, and
  `null` when the agent runs with authentication off.
- `GET /api/statements` — the person's statement files: `fileName`, `sizeBytes`, `modified`.
- `POST /api/statements` — takes the multipart part `file`; 201 with the stored file; 400 for a
  refused file, 413 over the 5 MB upload limit.
- `DELETE /api/statements/{file_name:path}` — 204; 400 when no listed statement has that name.

### Probes

- `GET /health` — `UP` while the replica serves; 503 `DOWN` once its lease sweep has stopped
  ([`LeaseSweep`](workers.md#leasesweep)). The Compose healthchecks and `deploy.sh` call it; open.
