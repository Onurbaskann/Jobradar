"""LLM sağlayıcıları: Anthropic API veya yerel Ollama.

Sağlayıcı model adından anlaşılır — ayrı bir ayar yok:

    MODEL_EXTRACT=claude-haiku-4-5      → Anthropic
    MODEL_EXTRACT=ollama:qwen3:8b       → yerelde Ollama

Böylece her ajan bağımsız seçilebilir. Tipik kullanım: yüksek hacimli ve
mekanik işler (ilan çıkarımı, ön eleme) yerelde bedava, yazı kalitesi önemli
olan tek iş (CV uyarlama) bulutta.

İki sağlayıcı da **şemaya uyan** çıktı üretir; hiçbir ajan serbest metin
ayrıştırmaz.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

log = logging.getLogger(__name__)

OLLAMA_PREFIX = "ollama:"

#: Yerel modelin bağlam penceresi. Ollama varsayılanı 4096'dır ve budanmış bir
#: kariyer sayfası bunu rahatça aşar — açıkça vermezsek sayfanın sonu sessizce
#: kırpılır ve ilanlar kaybolur.
OLLAMA_NUM_CTX = 32768

#: `effort` / adaptive thinking yalnızca yeni nesil Anthropic modellerinde var.
_EFFORT_CAPABLE_PREFIXES = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
)


class ProviderError(RuntimeError):
    """Sağlayıcı kullanılabilir bir yanıt üretemedi."""


class ProviderRefusal(ProviderError):
    """Model yanıt vermeyi reddetti."""


@dataclass(slots=True)
class ProviderResponse:
    data: BaseModel
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


def is_local(model: str) -> bool:
    return model.startswith(OLLAMA_PREFIX)


def supports_effort(model: str) -> bool:
    return model.startswith(_EFFORT_CAPABLE_PREFIXES)


def describe(model: str) -> str:
    """Log ve maliyet tablosunda okunur isim."""
    return f"yerel/{model.removeprefix(OLLAMA_PREFIX)}" if is_local(model) else model


# --------------------------------------------------------------------- Anthropic


def call_anthropic[T: BaseModel](
    *,
    model: str,
    system: str,
    user_content: str | list[dict[str, Any]],
    output_model: type[T],
    max_tokens: int,
    effort: str,
    tools: list[dict[str, Any]] | None,
) -> ProviderResponse:
    import anthropic

    from app.agents.client import get_anthropic_client

    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        # Sistem promptu sabit ön ek: önbellek buradan okunur.
        # Değişken içerik ön ekten SONRA gelmeli, yoksa önbellek sessizce ölür.
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_content}],
        "output_format": output_model,
    }
    if supports_effort(model):
        params["output_config"] = {"effort": effort}
    if tools:
        params["tools"] = tools

    try:
        response = get_anthropic_client().messages.parse(**params)
    except anthropic.APIStatusError as exc:
        raise ProviderError(f"Anthropic {exc.status_code}: {exc.message}") from exc

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        raise ProviderRefusal(f"model reddetti (kategori: {category})")

    if response.parsed_output is None:
        raise ProviderError(f"yanıt şemaya uymadı (stop_reason={response.stop_reason})")

    usage = response.usage
    return ProviderResponse(
        data=response.parsed_output,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )


# ------------------------------------------------------------------------ Ollama


def call_ollama[T: BaseModel](
    *,
    model: str,
    system: str,
    user_content: str,
    output_model: type[T],
    tools: list[dict[str, Any]] | None,
) -> ProviderResponse:
    if tools:
        # Sunucu taraflı web arama/çekme yalnızca Anthropic tarafında var.
        # Sessizce araçsız çalışmak, ajanın yapamayacağı bir işi yapıyormuş
        # gibi görünmesine yol açardı.
        raise ProviderError("yerel model sunucu taraflı araçları (web arama/çekme) desteklemiyor")

    settings = get_settings()
    body = {
        "model": model.removeprefix(OLLAMA_PREFIX),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "format": output_model.model_json_schema(),
        "stream": False,
        "think": False,
        "options": {"num_ctx": OLLAMA_NUM_CTX, "temperature": 0},
    }

    try:
        response = httpx.post(
            f"{settings.ollama_url.rstrip('/')}/api/chat",
            json=body,
            timeout=settings.ollama_timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"Ollama'ya ulaşılamadı ({settings.ollama_url}): {exc}") from exc

    payload = response.json()
    content = (payload.get("message") or {}).get("content") or ""

    try:
        parsed = output_model.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ProviderError(f"yerel model şemaya uymayan çıktı verdi: {str(exc)[:200]}") from exc

    return ProviderResponse(
        data=parsed,
        input_tokens=int(payload.get("prompt_eval_count") or 0),
        output_tokens=int(payload.get("eval_count") or 0),
    )
