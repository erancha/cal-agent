"""Builds each JSON-RPC call's context: the admitted caller and the person the call is for.

The SDK scopes tasks by the context user's name, so the user is the caller, not the person: a
continue from another Google account then finds the task and is answered with sign-in-required
instead of task-not-found. The person's token is verified here but never refused here; the
executor answers a bad token inside the task, so the same task continues after a new sign-in.

State keys set on every context:
- caller: the admitted Caller, or None with authentication off
- person: the VerifiedPerson, or None when the token was missing or not valid
- auth_failure: why there is no person, readable after "could not verify who you are"
"""

from a2a.auth.user import User
from a2a.server.context import ServerCallContext
from a2a.server.routes import DefaultServerCallContextBuilder
from starlette.requests import Request

from calagent.domain.errors import InvalidTokenError
from calagent.platform.a2a.callers import CALLER_STATE_KEY
from calagent.ports.tokens import TokenVerifier, VerifiedPerson

ANONYMOUS = "anonymous"
PERSON_KEY = "person"
AUTH_FAILURE_KEY = "auth_failure"
_BEARER = "Bearer "


def bearer_token(authorization: str | None) -> str:
    """The token of an Authorization header value; InvalidTokenError when there is none."""
    if authorization is None:
        raise InvalidTokenError("no sign-in token came with the request")
    if not authorization.startswith(_BEARER):
        raise InvalidTokenError("the Authorization header is not a bearer token")
    return authorization.removeprefix(_BEARER)


class CallerUser(User):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._name


class CalCallContextBuilder(DefaultServerCallContextBuilder):
    """With no verifier, authentication is off and every call is for the person anonymous."""

    def __init__(self, verifier: TokenVerifier | None) -> None:
        self._verifier = verifier

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        if self._verifier is None:
            context.user = CallerUser(ANONYMOUS)
            context.state[CALLER_STATE_KEY] = None
            context.state[PERSON_KEY] = VerifiedPerson(ANONYMOUS, None)
            context.state[AUTH_FAILURE_KEY] = None
            return context
        caller = request.scope["state"][CALLER_STATE_KEY]
        context.user = CallerUser(caller.name)
        context.state[CALLER_STATE_KEY] = caller
        context.state[PERSON_KEY] = None
        context.state[AUTH_FAILURE_KEY] = None
        try:
            token = bearer_token(request.headers.get("authorization"))
            context.state[PERSON_KEY] = self._verifier.verify(token, caller.client_id)
        except InvalidTokenError as failure:
            context.state[AUTH_FAILURE_KEY] = failure.cause
        return context
