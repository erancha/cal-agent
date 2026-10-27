"""The public agent card: the monthly-transactions skill and the credentials every call carries.

With authentication required, the card asks for two credentials together: the signed-in person's
Google ID token (an OpenID Connect scheme, sent as the bearer token) and the caller's shared
secret (an API key scheme in the X-Caller-Secret header). Without it, the card declares none.
"""

from importlib.metadata import version

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    APIKeySecurityScheme,
    OpenIdConnectSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)

from calagent.domain.taxonomy import TAXONOMY
from calagent.platform.config import Settings

SKILL_ID = "monthly-transactions"
PERSON_SCHEME = "google"
CALLER_SCHEME = "caller"
CALLER_SECRET_HEADER = "X-Caller-Secret"
GOOGLE_OPENID_CONFIGURATION = "https://accounts.google.com/.well-known/openid-configuration"
# The skill accepts and returns what the agent as a whole does, so both levels share these.
INPUT_MODES = ["application/json", "text/plain"]
OUTPUT_MODES = ["application/json"]


def build_agent_card(settings: Settings) -> AgentCard:
    card = AgentCard(
        name="Cal (Israel Credit Cards) card agent",
        description=(
            "Serves the transactions charged to a Cal (Israel Credit Cards) card in a given "
            "billing month, categorized into a fixed taxonomy."
        ),
        version=version("calagent"),
        supported_interfaces=[
            AgentInterface(
                url=settings.advertised_url, protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=INPUT_MODES,
        default_output_modes=OUTPUT_MODES,
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name="Monthly card transactions",
                description=(
                    "Returns the card transactions charged in a given billing month, each "
                    f"categorized into one of: {', '.join(TAXONOMY)}. Send a data part "
                    '{"month": "YYYY-MM"}. When no statement covers the month the task asks for '
                    'input; reply {"action": "continue"} after uploading it.'
                ),
                tags=["finance", "credit-card", "transactions"],
                examples=['{"month": "2026-10"}'],
                input_modes=INPUT_MODES,
                output_modes=OUTPUT_MODES,
            )
        ],
    )
    if settings.a2a_auth_required:
        card.security_schemes[PERSON_SCHEME].CopyFrom(
            SecurityScheme(
                open_id_connect_security_scheme=OpenIdConnectSecurityScheme(
                    open_id_connect_url=GOOGLE_OPENID_CONFIGURATION,
                    description="The signed-in person's Google ID token, as the bearer token",
                )
            )
        )
        card.security_schemes[CALLER_SCHEME].CopyFrom(
            SecurityScheme(
                api_key_security_scheme=APIKeySecurityScheme(
                    location="header",
                    name=CALLER_SECRET_HEADER,
                    description="Shared secret registered with the agent operator",
                )
            )
        )
        card.security_requirements.append(
            SecurityRequirement(schemes={PERSON_SCHEME: StringList(), CALLER_SCHEME: StringList()})
        )
    return card
