"""A key pair generated at import, and tokens signed with it, so no test reaches Google."""

import time
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from calagent.adapters.google_tokens import GOOGLE_ISSUER

CALLER_CLIENT_ID = "caller-123.apps.googleusercontent.com"
OTHER_CALLER_CLIENT_ID = "other-789.apps.googleusercontent.com"
PAGE_CLIENT_ID = "page-456.apps.googleusercontent.com"
KID = "key-1"

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


def sign(key: rsa.RSAPrivateKey = PRIVATE_KEY, **claims: Any) -> str:
    """A token for person 1000 issued to the caller's client, valid an hour, with any claim
    overridden."""
    now = int(time.time())
    payload = {
        "iss": GOOGLE_ISSUER,
        "aud": CALLER_CLIENT_ID,
        "sub": "1000",
        "iat": now,
        "exp": now + 3600,
        "email": "dana@example.com",
    }
    payload.update(claims)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": KID})
