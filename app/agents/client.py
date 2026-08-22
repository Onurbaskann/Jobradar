"""Ajanların ortak giriş noktası.

Burada toplanan üç şey her ajanda tekrar edilmesin diye:

* **Yapılandırılmış çıktı** — hiçbir ajan serbest metin ayrıştırmıyor; şema
  sağlayıcı tarafında zorlanıyor.
* **Sağlayıcı seçimi** — model adı Anthropic mi yerel Ollama mı olduğunu
  belirler (bkz. `providers.py`).
* **Token muhasebesi** — her çağrının kullanımı DB'ye yazılıyor ki harcama
  görünür olsun; yerel çağrılar ücretsiz ama yine kaydediliyor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from sqlmodel import Session

from app.agents.providers import (
    ProviderError,
    ProviderRefusal,
    call_anthropic,
    call_ollama,
    describe,
    is_local,
)
from app.config import get_settings
from app.db import get_engine
from app.models import UsageLog

log = logging.getLogger(__name__)


class AgentError(RuntimeError):
    """Ajan kullanılabilir bir sonuç üretemedi."""


class AgentRefusal(AgentError):
    """Model güvenlik gerekçesiyle yanıt vermeyi reddetti."""


@dataclass(slots=True)
class AgentResult[TModel: BaseModel]:
    data: TModel
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int


@lru_cache
def get_anthropic_client():
    import anthropic

    settings = get_settings()
    if not settings.anthropic_api_key:
        # Boş bırakılırsa SDK ortamdan (ANTHROPIC_API_KEY veya `ant auth login`
        # profili) çözer; burada hata fırlatmıyoruz.
        return anthropic.Anthropic()
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def call_structured[T: BaseModel](
    *,
    agent: str,
    model: str,
    system: str,
    user_content: str | list[dict[str, Any]],
    output_model: type[T],
    max_tokens: int = 16000,
    effort: str = "medium",
    tools: list[dict[str, Any]] | None = None,
    company_id: int | None = None,
    job_id: int | None = None,
) -> AgentResult[T]:
    """Şemaya uyan tek bir yanıt üretir ve kullanımını kaydeder."""
    try:
        if is_local(model):
            if not isinstance(user_content, str):
                raise ProviderError("yerel sağlayıcı yalnızca düz metin girdi alır")
            response = call_ollama(
                model=model,
                system=system,
                user_content=user_content,
                output_model=output_model,
                tools=tools,
            )
        else:
            response = call_anthropic(
                model=model,
                system=system,
                user_content=user_content,
                output_model=output_model,
                max_tokens=max_tokens,
                effort=effort,
                tools=tools,
            )
    except ProviderRefusal as exc:
        raise AgentRefusal(f"{agent}: {exc}") from exc
    except ProviderError as exc:
        raise AgentError(f"{agent}: {exc}") from exc

    _record_usage(agent, model, response, company_id=company_id, job_id=job_id)
    return AgentResult(
        data=response.data,  # type: ignore[arg-type]
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_read_tokens=response.cache_read_tokens,
    )


def _record_usage(
    agent: str, model: str, response, *, company_id: int | None, job_id: int | None
) -> None:
    """Kullanımı en iyi çabayla kaydeder — muhasebe hatası işi durdurmamalı."""
    try:
        with Session(get_engine()) as session:
            session.add(
                UsageLog(
                    agent=agent,
                    model=describe(model),
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cache_creation_input_tokens=response.cache_creation_tokens,
                    cache_read_input_tokens=response.cache_read_tokens,
                    company_id=company_id,
                    job_id=job_id,
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 — DB yoksa (test, CLI --help) sessizce geç
        log.debug("kullanım kaydedilemedi", exc_info=True)
