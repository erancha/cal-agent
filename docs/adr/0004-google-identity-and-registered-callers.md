# 0004. People are Google accounts; callers are registered with a secret each

- Status: Accepted
- Date: 2026-10-27

## Context

Every request is for one person's statements, and most arrive through a caller acting for that
person. The contract names two credentials: the caller's own, and the person's identity. The
household already signs in to the home finance agent with Google, so a Google ID token for the
person exists on the caller's side. The statements page needs a sign-in of its own, with no
caller in between. Only programs the agent's operator trusts should be served.

## Decision

- A caller is registered by `register-caller.sh` in the gitignored `allowed-callers.yaml`: a
  name, a secret the script mints and prints once, and the Google OAuth client id of the caller's
  own sign-in. The agent reads the file at startup and refuses to start without a caller.
- Every A2A call carries the caller's secret in `X-Caller-Secret`, compared in constant time; a
  call matching no caller is answered 401 before JSON-RPC.
- The caller forwards the person's Google ID token as a bearer token. The agent verifies its
  signature against Google's published keys, its issuer, expiry and audience, which must be the
  admitted caller's registered client id. The token's `sub` is the person's id everywhere.
- A failed person check pauses the task asking for sign-in, rather than refusing the call.
- The statements page signs in with the agent's own Google OAuth client, `AUTH_CLIENT_ID`, and
  its API accepts only tokens issued to that client.

## Consequences

- The agent stores no passwords and issues no tokens of its own.
- A caller sees only its own tasks; one caller's tokens never open another's tasks.
- Registering or revoking a caller takes a restart of a running agent.
- Trusting a token issued to a partner's client suits services under one roof; an agent run by a
  separate company would more likely issue tokens of its own.
