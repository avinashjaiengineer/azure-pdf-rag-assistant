from functools import lru_cache

from azure.identity import DefaultAzureCredential


@lru_cache
def get_credential() -> DefaultAzureCredential:
    """One credential shared by every Azure client.

    DefaultAzureCredential remembers which source worked (az CLI locally, managed identity
    in Azure), so sharing it avoids re-probing the whole chain once per client.
    """
    return DefaultAzureCredential()
