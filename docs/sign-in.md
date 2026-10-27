# Sign-in

cal-agent knows people by their Google account and nothing else: the statements page signs a
person in with the agent's own Google OAuth client, and every A2A call forwards the person's Google
ID token issued to the registered caller's client. How the agent checks both is in
[request-flow.md](architecture/request-flow.md#who-is-calling); this page sets up the Google side.

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
5. **Give it to the agent.** Copy the client id into `AUTH_CLIENT_ID` in `.env`.

Google accepts only `localhost` or a public hostname as an authorized origin, never a private
address such as `10.0.0.23`, so the statements page signs a person in only where it is reached
under one of those.
