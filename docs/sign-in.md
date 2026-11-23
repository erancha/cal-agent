# Sign-in

cal-agent knows people by their Google account and nothing else: the statements page signs a
person in with the agent's own Google OAuth client, and every A2A call forwards the person's Google
ID token issued to the registered caller's client. This page explains how sign-in works and how to
set up the Google side, behind [Architecture](architecture.md#request-flow); how the agent checks
both credentials is in [Request flow](architecture/request-flow.md#who-is-calling).

## How it works

```mermaid
sequenceDiagram
    actor P as Person
    participant G as Google
    participant S as Statements page
    participant C as Registered caller
    participant A as cal-agent
    P->>S: Sign in with Google
    S->>G: Sign-in button, this agent's client
    G-->>S: ID token, audience = AUTH_CLIENT_ID
    S->>A: Statements API, Authorization: Bearer token
    A->>A: Verify signature, issuer, expiry, audience
    P->>C: Signs in to the caller's own client
    C->>A: A2A call: X-Caller-Secret + the person's token
    A->>A: Secret matches a registered caller;<br/>token audience = that caller's client id
```

- **The statements page** signs a person in with the Sign in with Google button of this agent's
  own client. The button hands the ID token to the page, which sends it as a bearer token with
  every call to the statements API; the agent accepts only tokens whose audience is
  `AUTH_CLIENT_ID`. A person sees only the folder of their own Google account id.
- **An A2A call** carries two credentials: the caller's shared secret, matched against the
  entries of the gitignored `allowed-callers.yaml`, and the person's token, issued to that caller's
  own client and accepted only when its audience is the client id registered with the caller.
- **The agent verifies every token locally**, against Google's published keys, the issuer and the
  expiry. No session is kept server side; a refused A2A call pauses the task until the person
  signs in again ([request-flow.md](architecture/request-flow.md#who-is-calling)).

## Setting up Google

Give cal-agent its own Google Cloud project with one OAuth client, apart from any caller's. Each
project has its own consent screen, test users and owner, so nothing in one console touches the
other, and the agent accepts a caller's tokens only because that caller registered its client id
here.

1. **Create the project.** In the [Google Cloud console](https://console.cloud.google.com/), open
   the project picker at the top of the page, choose **New project**, name it `cal-agent` and
   create it. Make sure the picker shows that project: everything below is per project.
2. **Configure the consent screen.** Search the top bar for **Google Auth Platform** and open it
   (older consoles reach the same place as **APIs & Services → OAuth consent screen**). A new
   project shows "Google Auth Platform not configured yet" with a **Get started** button. The
   wizard asks for an app name (`cal-agent`) and your email as the support email, then the
   audience, where you choose **External**, then a contact email, then your agreement to Google's
   policy. **Create** finishes it. The app is in **Testing**, which is where it stays: no
   verification, no publishing.
3. **Add the test users.** Open **Audience** and, under **Test users**, add the household's
   Google accounts. While an app is in testing, Google signs in nobody else, with an "access
   blocked" page. **Data Access** stays empty: the agent needs no scope beyond the defaults.
4. **Create the client.** Open **Clients → Create client**, choose **Web application**, give it a
   name, and under **Authorized JavaScript origins** add `http://localhost:8030`. Leave
   **Authorized redirect URIs** empty: the sign-in button hands the token to the page directly.
   **Create** shows the client id, a long string ending in `.apps.googleusercontent.com`, next to
   a client secret and a JSON download. Only the client id is needed; it stays listed on the
   Clients page. Ignore the secret and the download: the agent verifies tokens, it never redeems
   codes, so nothing in this repo has a place for the secret.
5. **Give it to the agent.** Copy the client id into `AUTH_CLIENT_ID` in `scripts/lib/params.sh`,
   which `./scripts/init-env.sh` creates.
6. **Start the agent.** Run `./scripts/deploy.sh`, which starts it with the client id.

Google accepts only `localhost` or a public hostname as an authorized origin, never a private
address such as `10.0.0.23`, so the statements page signs a person in only where it is reached
under one of those.

A stack deployed with `./scripts/deploy.sh --ec2` is reached at its CloudFront address, which the
script prints. Add `https://<id>.cloudfront.net` as a further authorized JavaScript origin of the
same client; it still needs no redirect URI.

## Who may sign in

The list of test users on the OAuth app is the access list for the statements page: while an app
is in testing mode, Google signs in nobody else and shows an "access blocked" page. There is no
allow-list in the agent's code, so adding or removing a person is done in the console, under
**Audience → Test users**. An A2A call is admitted for a registered caller only, and for the
people that caller's own Google app signs in.

The statements page explains signing in with Google under its sign-in button: the
toggle "Why sign in with Google?" opens a panel saying that Google approves the sign-in and
gives cal-agent only who the person is, that the person can disconnect cal-agent in their Google
account's settings, and that cal-agent stores no passwords, with a link to Google's own help
page.
