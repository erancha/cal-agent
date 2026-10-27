"""Token verification against the test key pair, so no test reaches Google."""

import time
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import PyJWKClient

from calagent.adapters.google_tokens import (
    GOOGLE_ISSUER,
    GoogleTokenVerifier,
    JwksKeys,
    StaticKey,
)
from calagent.domain.errors import InvalidTokenError
from calagent.ports.tokens import VerifiedPerson
from tests.auth_keys import (
    CALLER_CLIENT_ID,
    KID,
    OTHER_KEY,
    PAGE_CLIENT_ID,
    PRIVATE_KEY,
    PUBLIC_PEM,
    sign,
)


def verifier(issuer: str = GOOGLE_ISSUER) -> GoogleTokenVerifier:
    return GoogleTokenVerifier(StaticKey(PUBLIC_PEM), issuer)


def verify(token: str, issuer: str = GOOGLE_ISSUER) -> VerifiedPerson:
    return verifier(issuer).verify(token, CALLER_CLIENT_ID)


def resign(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})


def claims_of(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


def test_a_valid_token_names_the_person() -> None:
    assert verify(sign()) == VerifiedPerson("1000", "dana@example.com")


def test_email_is_optional() -> None:
    payload = claims_of(sign())
    del payload["email"]
    assert verify(resign(payload)) == VerifiedPerson("1000", None)


def test_google_bare_issuer_form_is_accepted_for_google_only() -> None:
    assert verify(sign(iss="accounts.google.com")).sub == "1000"
    with pytest.raises(InvalidTokenError, match="not issued by test-issuer"):
        verify(sign(iss="accounts.google.com"), issuer="test-issuer")


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"exp": int(time.time()) - 1}, "expired"),
        ({"aud": "other-client"}, "another application"),
        ({"iss": "https://evil.example"}, "not issued by"),
    ],
)
def test_wrong_claims_are_refused_with_a_reason(claims: dict[str, Any], reason: str) -> None:
    with pytest.raises(InvalidTokenError, match=reason):
        verify(sign(**claims))


def test_the_page_clients_token_is_refused_for_the_callers_audience() -> None:
    with pytest.raises(InvalidTokenError, match="another application"):
        verify(sign(aud=PAGE_CLIENT_ID))
    assert verifier().verify(sign(aud=PAGE_CLIENT_ID), PAGE_CLIENT_ID).sub == "1000"


def test_a_token_signed_by_another_key_is_refused() -> None:
    with pytest.raises(InvalidTokenError, match="not valid"):
        verify(sign(key=OTHER_KEY))


def test_unsigned_symmetric_and_malformed_tokens_are_refused() -> None:
    payload = claims_of(sign())
    for token in (
        jwt.encode(payload, None, algorithm="none"),
        jwt.encode(payload, "s" * 32, algorithm="HS256"),
        "not.a.token",
    ):
        with pytest.raises(InvalidTokenError, match="not valid"):
            verify(token)


def test_a_token_missing_a_required_claim_is_refused() -> None:
    payload = claims_of(sign())
    del payload["sub"]
    with pytest.raises(InvalidTokenError, match="not valid"):
        verify(resign(payload))


def test_a_token_without_a_key_id_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True)
    published = {"keys": [{**jwk, "kid": KID, "alg": "RS256", "use": "sig"}]}
    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda self: published)
    token = jwt.encode(claims_of(sign()), PRIVATE_KEY, algorithm="RS256")
    checker = GoogleTokenVerifier(JwksKeys("https://keys.example/certs"), GOOGLE_ISSUER)
    with pytest.raises(
        InvalidTokenError, match='not valid: Unable to find a signing key that matches: "None"'
    ):
        checker.verify(token, CALLER_CLIENT_ID)


def test_unreachable_signing_keys_are_reported_as_such(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(self: PyJWKClient) -> dict[str, Any]:
        raise jwt.PyJWKClientConnectionError("offline")

    monkeypatch.setattr(PyJWKClient, "fetch_data", unreachable)
    checker = GoogleTokenVerifier(JwksKeys("https://keys.example/certs"), GOOGLE_ISSUER)
    with pytest.raises(InvalidTokenError, match="could not fetch Google's signing keys: offline"):
        checker.verify(sign(), CALLER_CLIENT_ID)


def test_static_key_reads_a_pem_file_and_refuses_a_non_rsa_key(tmp_path: Path) -> None:
    pem = tmp_path / "public.pem"
    pem.write_bytes(PUBLIC_PEM)
    checker = GoogleTokenVerifier(StaticKey.from_file(pem), GOOGLE_ISSUER)
    assert checker.verify(sign(), CALLER_CLIENT_ID).sub == "1000"
    ec_pem = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    with pytest.raises(TypeError, match="RSA"):
        StaticKey(ec_pem)


def test_jwks_keys_select_the_signing_key_by_its_id(monkeypatch: pytest.MonkeyPatch) -> None:
    jwk = jwt.PyJWK.from_dict(
        {
            **jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True),
            "kid": KID,
            "alg": "RS256",
            "use": "sig",
        }
    )
    other = jwt.PyJWK.from_dict(
        {
            **jwt.algorithms.RSAAlgorithm.to_jwk(OTHER_KEY.public_key(), as_dict=True),
            "kid": "key-2",
            "alg": "RS256",
            "use": "sig",
        }
    )
    fetched: list[str] = []

    def fetch_data(self: PyJWKClient) -> dict[str, Any]:
        fetched.append(self.uri)
        return {"keys": [other._jwk_data, jwk._jwk_data]}

    monkeypatch.setattr(PyJWKClient, "fetch_data", fetch_data)
    checker = GoogleTokenVerifier(JwksKeys("https://keys.example/certs"), GOOGLE_ISSUER)

    assert checker.verify(sign(), CALLER_CLIENT_ID).sub == "1000"
    assert checker.verify(sign(), CALLER_CLIENT_ID).sub == "1000"
    assert fetched == ["https://keys.example/certs"]
    unknown_kid = jwt.encode(
        claims_of(sign()), OTHER_KEY, algorithm="RS256", headers={"kid": "key-3"}
    )
    with pytest.raises(InvalidTokenError, match="not valid"):
        checker.verify(unknown_kid, CALLER_CLIENT_ID)
