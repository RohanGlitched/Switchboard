"""Model provider resolution for Switchboard.

Switchboard is provider-portable on purpose. The hackathon requires the Strands
Agents SDK; the *model* behind it is a deployment detail. We ship Amazon Bedrock
as the default so a judge with a standard AWS account can clone and run, and we
fall back cleanly when credentials are absent.

Resolution order for SWITCHBOARD_PROVIDER=auto (the default):
    1. bedrock   - if boto3 can resolve credentials, or a Bedrock API key is set
    2. anthropic - if ANTHROPIC_API_KEY is set
    3. none      - no model could be resolved

Resolution never raises. A missing credential must not stop the server from
starting: the console still loads, the header says plainly which provider is in
play, and /api/run returns a 503 naming the environment variables to set. A
blank page teaches you nothing; a running page that tells you what is missing
teaches you everything.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("switchboard.config")

# Cheap tier by default. Triage/classification/drafting do not need a frontier
# model, and a background agent that runs all day needs to be affordable to run.
BEDROCK_FAST = os.getenv("SWITCHBOARD_BEDROCK_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
ANTHROPIC_FAST = os.getenv("SWITCHBOARD_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

DEFAULT_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


@dataclass(frozen=True)
class ProviderInfo:
    """What actually ended up powering the agents, for display in the UI."""

    name: str
    model_id: str
    detail: str

    @property
    def is_live(self) -> bool:
        return self.name != "none"


def _bedrock_credentials_available() -> bool:
    """Bedrock accepts two different kinds of auth and we support both.

    A Bedrock API key (AWS_BEARER_TOKEN_BEDROCK) does *not* populate the normal
    boto3 credential chain, so checking Session.get_credentials() alone reports
    "no credentials" on a machine that can in fact call Bedrock perfectly well.
    Check the bearer token first.
    """
    if os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        return True
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return False
    try:
        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            return False
        # Resolving is lazy; force it so we fail here rather than mid-demo.
        frozen = creds.get_frozen_credentials()
        return bool(frozen.access_key)
    except (BotoCoreError, ClientError, Exception):  # noqa: BLE001 - never block startup
        return False


def resolve_provider() -> ProviderInfo:
    """Pick a provider without ever raising. Startup must not fail."""
    requested = os.getenv("SWITCHBOARD_PROVIDER", "auto").strip().lower()

    if requested in ("bedrock", "auto") and _bedrock_credentials_available():
        return ProviderInfo("bedrock", BEDROCK_FAST, f"Amazon Bedrock ({DEFAULT_REGION})")

    if requested == "bedrock":
        logger.warning("SWITCHBOARD_PROVIDER=bedrock but no AWS credentials resolved; falling back.")

    if requested in ("anthropic", "auto") and os.getenv("ANTHROPIC_API_KEY"):
        return ProviderInfo("anthropic", ANTHROPIC_FAST, "Anthropic API")

    return ProviderInfo(
        "none",
        "unconfigured",
        "No model credentials found - set AWS_BEARER_TOKEN_BEDROCK, "
        "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, or ANTHROPIC_API_KEY",
    )


def build_model(provider: ProviderInfo):
    """Return a Strands model instance, or None if nothing could be resolved."""
    if provider.name == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(
            model_id=provider.model_id,
            region_name=DEFAULT_REGION,
            temperature=0.2,
            # Low temperature: this agent makes operational decisions about food
            # safety and minors. Creativity is not the goal; consistency is.
        )

    if provider.name == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(
            client_args={"api_key": os.getenv("ANTHROPIC_API_KEY")},
            model_id=provider.model_id,
            max_tokens=1024,
            params={"temperature": 0.2},
        )

    return None


PROVIDER = resolve_provider()
