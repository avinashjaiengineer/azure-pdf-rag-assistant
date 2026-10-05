import re
from typing import TYPE_CHECKING, Protocol

import httpx

from src.config.settings import Settings
from src.models.schemas import RetrievedChunk

if TYPE_CHECKING:
    from openai import OpenAI

NOT_FOUND_MESSAGE = "I could not find this information in the uploaded documents."

SYSTEM_PROMPT = f"""You are an enterprise document assistant.

Answer the user's question using only the provided context.

If the answer cannot be found in the context, say exactly:
"{NOT_FOUND_MESSAGE}"

Do not invent information.

Cite sources inline using the bracketed source labels from the context,
for example [terraform.pdf, page 3]."""


def format_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{r.chunk.filename}, page {r.chunk.page_number}]\n{r.chunk.content}" for r in chunks
    )


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    return f"Context:\n{format_context(chunks)}\n\nQuestion:\n{question}"


class Generator(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class OllamaGenerator:
    """Local chat model via Ollama's /api/chat endpoint."""

    def __init__(self, base_url: str, model: str, temperature: float, timeout: float):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model
        self._temperature = temperature

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.post(
            "/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "think": False,  # qwen3 reasoning traces aren't useful in answers
                "options": {"temperature": self._temperature},
            },
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        # Older Ollama versions ignore "think"; strip any leaked reasoning block.
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


class AzureOpenAIGenerator:
    """Chat completions from an Azure OpenAI deployment."""

    def __init__(
        self,
        client: "OpenAI",
        deployment: str,
        temperature: float,
        reasoning_effort: str | None,
        max_output_tokens: int,
    ):
        self._client = client
        self._deployment = deployment
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        params: dict = {"max_completion_tokens": self._max_output_tokens}
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        else:
            params["temperature"] = self._temperature
        response = self._client.chat.completions.create(
            model=self._deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **params,
        )
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise RuntimeError("Azure OpenAI content filter blocked the response")
        return (choice.message.content or "").strip()


def get_generator(settings: Settings) -> Generator:
    if settings.llm_provider == "ollama":
        return OllamaGenerator(
            settings.ollama_base_url,
            settings.ollama_chat_model,
            settings.temperature,
            settings.ollama_timeout_seconds,
        )
    if settings.llm_provider == "azure":
        from src.azure_clients.openai_client import get_openai_client

        return AzureOpenAIGenerator(
            get_openai_client(settings.azure_openai_endpoint, settings.azure_openai_timeout_seconds),
            settings.azure_openai_chat_deployment,
            settings.temperature,
            settings.azure_openai_reasoning_effort,
            settings.azure_openai_max_output_tokens,
        )
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
