"""The port that turns a bearer token into the verified person it was issued to."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VerifiedPerson:
    sub: str
    email: str | None


class TokenVerifier(Protocol):
    def verify(self, token: str, audience: str) -> VerifiedPerson:
        """The person the token was issued to for this audience; raises InvalidTokenError with a
        readable cause when the token is not valid."""
        ...
