"""Optional LLM transport. Only reference metadata crosses the network boundary."""

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import Field

from .analyst import Evidence
from .schemas import DTO

INPUT_LIMIT = 8000
OUTPUT_LIMIT = 1000
MAX_RESPONSE_BYTES = 64 * 1024
PROMPT = (
    "Rank the evidence for an analyst summary. Select up to 12 distinct pairs from "
    "the records. Prefer market matches and explicit demand, competition or risk "
    "links. Keep observations and evidence paired as supplied. Return one JSON "
    'object {"references":[{"evidence_id":"UUID","observation_id":"UUID"}]}. '
    "Return only these fields. Do not produce statements, numbers or advice."
)


def messages(evidence: tuple[Evidence, ...]) -> list[dict[str, str]]:
    payload = json.dumps(
        [row.provider_view() for row in evidence], separators=(",", ":")
    )
    return [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": payload},
    ]


def fits_input_limit(request: list[dict[str, str]]) -> bool:
    # Byte bound on the ASCII message content plus room for chat framing.
    return (
        sum(len(message["content"].encode()) for message in request) + 512
        <= INPUT_LIMIT
    )


class Usage(DTO):
    prompt_tokens: int = Field(strict=True, ge=1, le=1_000_000_000)
    completion_tokens: int = Field(strict=True, ge=0, le=1_000_000_000)


@dataclass(frozen=True)
class Reply:
    content: str | None
    usage: Usage


class Provider(Protocol):
    name: str
    model: str

    def complete(self, request: list[dict[str, str]]) -> Reply: ...


class ProviderError(Exception):
    """Remote outcome unavailable or indeterminate."""


@dataclass(frozen=True)
class ChatCompletions:
    url: httpx.URL
    model: str
    key: str = field(repr=False)
    timeout: float
    name = "chat-completions"

    def complete(self, request: list[dict[str, str]]) -> Reply:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._complete(request))
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
        ) as exc:
            raise ProviderError from exc
        finally:
            # Closing avoids waiting for an OS resolver thread after cancellation.
            loop.close()

    async def _complete(self, request: list[dict[str, str]]) -> Reply:
        payload = {
            "model": self.model,
            "messages": request,
            "response_format": {"type": "json_object"},
            "max_completion_tokens": OUTPUT_LIMIT,
            "n": 1,
        }
        async with (
            asyncio.timeout(self.timeout),
            httpx.AsyncClient(
                timeout=self.timeout, trust_env=False, follow_redirects=False
            ) as client,
        ):
            async with client.stream(
                "POST",
                self.url,
                headers={"Authorization": f"Bearer {self.key}"},
                json=payload,
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ProviderError
        envelope = json.loads(body)
        usage = envelope["usage"]
        measured = Usage(
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
        )
        try:
            choice = envelope["choices"][0]
            message = choice["message"]
            content = message["content"]
            if (
                choice["finish_reason"] == "stop"
                and not message.get("refusal")
                and not message.get("tool_calls")
                and isinstance(content, str)
            ):
                return Reply(content, measured)
        except (KeyError, TypeError, IndexError):
            pass
        return Reply(None, measured)


@dataclass(frozen=True)
class Budget:
    daily: int
    input_rate: int
    output_rate: int

    def cost(self, input_tokens: int, output_tokens: int) -> int:
        # Rates: micro-USD per million tokens. Round aggregate cost up to micro-USD.
        scaled = input_tokens * self.input_rate + output_tokens * self.output_rate
        return (scaled + 999_999) // 1_000_000

    @property
    def maximum(self) -> int:
        return self.cost(INPUT_LIMIT, OUTPUT_LIMIT)


@dataclass(frozen=True)
class External:
    provider: Provider
    budget: Budget


def external_from_env() -> External | None:
    mode = os.getenv("AI_PROVIDER", "local")
    if mode == "local":
        return None
    if (
        mode != "chat-completions"
        or os.getenv("AI_EXTERNAL_POLICY") != "pilot-reference-metadata-v1"
    ):
        raise ValueError("External analyst policy is missing or unsupported")
    try:
        url = httpx.URL(os.environ["AI_PROVIDER_URL"])
    except httpx.InvalidURL:
        raise ValueError("Invalid provider URL") from None
    if (
        url.scheme != "https"
        or not url.host
        or url.userinfo
        or url.query
        or url.fragment
        or not url.path.endswith("/chat/completions")
    ):
        raise ValueError("Invalid provider URL")
    model, key = os.environ["AI_MODEL"], os.environ["AI_API_KEY"]
    if not (1 <= len(model) <= 128 and model.strip() == model and key.strip()):
        raise ValueError("Invalid provider credentials or model")
    timeout = float(os.getenv("AI_TIMEOUT_SECONDS", "15"))
    if not 0 < timeout <= 20:
        raise ValueError("Provider timeout must fit within the worker lease")
    budget = Budget(
        daily=int(os.environ["AI_DAILY_BUDGET_MICRO_USD"]),
        input_rate=int(os.environ["AI_INPUT_MICRO_USD_PER_MTOK"]),
        output_rate=int(os.environ["AI_OUTPUT_MICRO_USD_PER_MTOK"]),
    )
    if not (
        0 < budget.daily <= 10**12
        and 0 <= budget.input_rate <= 10**9
        and 0 <= budget.output_rate <= 10**9
        and budget.maximum <= budget.daily
    ):
        raise ValueError("Invalid provider budget or rates")
    return External(ChatCompletions(url, model, key, timeout), budget)
