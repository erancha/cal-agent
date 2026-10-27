"""Verifies Google ID tokens locally: signature, issuer, expiry and audience.

Core building blocks:
- GoogleTokenVerifier: the TokenVerifier port over PyJWT; accepts only RS256 tokens issued by one
  issuer, for the audience the caller names, signed by a key the key source knows
- JwksKeys: Google's published keys, fetched from the JWKS URL and cached by PyJWT
- StaticKey: one public key from a PEM file, for tests that must not reach Google

Google issues ID tokens under either "https://accounts.google.com" or the bare
"accounts.google.com"; the verifier accepts the bare form only when the configured issuer is
Google's.
"""

from pathlib import Path
from typing import Protocol

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWK, PyJWKClient

from calagent.domain.errors import InvalidTokenError
from calagent.ports.tokens import VerifiedPerson

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ALGORITHM = "RS256"


class KeySource(Protocol):
    def key_for(self, token: str) -> PyJWK | RSAPublicKey:
        """The public key that signed the token, chosen by its key id; raises PyJWTError when
        the source has no such key."""
        ...


class JwksKeys:
    def __init__(self, url: str) -> None:
        self._client = PyJWKClient(url, cache_keys=True)

    def key_for(self, token: str) -> PyJWK:
        return self._client.get_signing_key_from_jwt(token)


class StaticKey:
    def __init__(self, pem: bytes) -> None:
        key = serialization.load_pem_public_key(pem)
        if not isinstance(key, RSAPublicKey):
            raise TypeError("the public key file must hold an RSA public key")
        self._key = key

    @classmethod
    def from_file(cls, path: Path) -> StaticKey:
        return cls(path.read_bytes())

    def key_for(self, token: str) -> RSAPublicKey:
        return self._key


class GoogleTokenVerifier:
    def __init__(self, keys: KeySource, issuer: str) -> None:
        self._issuers = [issuer, "accounts.google.com"] if issuer == GOOGLE_ISSUER else [issuer]
        self._keys = keys

    def verify(self, token: str, audience: str) -> VerifiedPerson:
        try:
            claims = jwt.decode(
                token,
                self._keys.key_for(token),
                algorithms=[ALGORITHM],
                audience=audience,
                issuer=self._issuers,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise InvalidTokenError("the sign-in has expired") from error
        except jwt.InvalidAudienceError as error:
            raise InvalidTokenError("the token was issued for another application") from error
        except jwt.InvalidIssuerError as error:
            raise InvalidTokenError(f"the token was not issued by {self._issuers[0]}") from error
        except jwt.PyJWKClientConnectionError as error:
            raise InvalidTokenError(f"could not fetch Google's signing keys: {error}") from error
        except jwt.PyJWTError as error:
            raise InvalidTokenError(f"the token is not valid: {error}") from error
        # Google sends the email claim only for the scopes the sign-in requests, so its absence
        # is a legal token.
        return VerifiedPerson(sub=claims["sub"], email=claims.get("email"))
