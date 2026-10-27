from pathlib import Path
from typing import Any

from tests.platform.support import AGENT_URL, http_client, make_app


async def card_of(tmp_path: Path, **settings: Any) -> dict[str, Any]:
    async with http_client(make_app(tmp_path, **settings), token=None, secret=None) as http:
        response = await http.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "max-age=3600, public"
    card: dict[str, Any] = response.json()
    return card


async def test_the_card_offers_the_skill_at_the_advertised_url(tmp_path: Path) -> None:
    card = await card_of(tmp_path)

    assert card["name"] == "Cal (Israel Credit Cards) card agent"
    assert card["skills"][0]["id"] == "monthly-transactions"
    assert "groceries, dining, transport" in card["skills"][0]["description"]
    assert card["supportedInterfaces"][0] == {
        "url": AGENT_URL,
        "protocolBinding": "JSONRPC",
        "protocolVersion": "1.0",
    }
    assert card["capabilities"]["streaming"] is True


async def test_the_card_requires_the_persons_token_and_the_callers_secret(tmp_path: Path) -> None:
    card = await card_of(tmp_path)

    schemes = card["securitySchemes"]
    assert schemes["google"]["openIdConnectSecurityScheme"]["openIdConnectUrl"] == (
        "https://accounts.google.com/.well-known/openid-configuration"
    )
    caller = schemes["caller"]["apiKeySecurityScheme"]
    assert (caller["location"], caller["name"]) == ("header", "X-Caller-Secret")
    [requirement] = card["securityRequirements"]
    assert set(requirement["schemes"]) == {"google", "caller"}


async def test_with_auth_off_the_card_declares_no_scheme(tmp_path: Path) -> None:
    card = await card_of(tmp_path, a2a_auth_required=False)

    assert "securitySchemes" not in card
    assert "securityRequirements" not in card
