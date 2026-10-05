from functools import lru_cache

from azure.identity import get_bearer_token_provider
from openai import OpenAI

from src.azure_clients.credential import get_credential

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


@lru_cache
def get_openai_client(endpoint: str, timeout: float) -> OpenAI:
    """Azure OpenAI v1 endpoint authenticated with Entra ID (no API keys).

    DefaultAzureCredential picks up `az login` locally and managed identity once deployed.
    """
    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT is not set")
    token_provider = get_bearer_token_provider(get_credential(), COGNITIVE_SERVICES_SCOPE)
    return OpenAI(
        base_url=f"{endpoint.rstrip('/')}/openai/v1/",
        api_key=token_provider,
        timeout=timeout,
    )
