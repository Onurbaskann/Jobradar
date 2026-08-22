"""Sağlayıcı katmanı: model adına göre Anthropic mi yerel Ollama mı."""

from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.agents.client import AgentError, call_structured
from app.agents.providers import (
    OLLAMA_NUM_CTX,
    ProviderError,
    call_ollama,
    describe,
    is_local,
    supports_effort,
)


class Answer(BaseModel):
    ok: bool
    note: str = ""


def test_model_name_selects_provider() -> None:
    assert is_local("ollama:qwen3:8b")
    assert not is_local("claude-haiku-4-5")


def test_effort_only_for_new_generation_models() -> None:
    """Haiku 4.5'e effort göndermek hata döndürür; model bazında karar veriyoruz."""
    assert supports_effort("claude-opus-5")
    assert supports_effort("claude-sonnet-5")
    assert not supports_effort("claude-haiku-4-5")
    assert not supports_effort("ollama:qwen3:8b")


def test_describe_marks_local_models() -> None:
    assert describe("ollama:qwen3:8b") == "yerel/qwen3:8b"
    assert describe("claude-haiku-4-5") == "claude-haiku-4-5"


@respx.mock
def test_ollama_call_sends_schema_and_context_window() -> None:
    """num_ctx açıkça verilmezse Ollama 4096'ya düşer ve sayfanın sonu sessizce kırpılır."""
    route = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"content": '{"ok": true, "note": "tamam"}'},
                "prompt_eval_count": 1200,
                "eval_count": 40,
            },
        )
    )

    response = call_ollama(
        model="ollama:qwen3:8b",
        system="sistem",
        user_content="sayfa metni",
        output_model=Answer,
        tools=None,
    )

    assert response.data.ok is True
    assert response.input_tokens == 1200
    assert response.output_tokens == 40

    body = route.calls[0].request.content.decode()
    assert '"num_ctx":32768' in body.replace(" ", "") or f'"num_ctx": {OLLAMA_NUM_CTX}' in body
    assert '"model":"qwen3:8b"' in body.replace(" ", ""), "ollama: öneki çıkarılmalı"
    assert "properties" in body, "şema gönderilmeli — serbest metin ayrıştırmıyoruz"


@respx.mock
def test_ollama_rejects_schema_violating_output() -> None:
    """Yerel model bozuk JSON verirse sessizce yanlış veri kaydetmemeliyiz."""
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "{ bozuk"}})
    )

    with pytest.raises(ProviderError, match="şemaya uymayan"):
        call_ollama(
            model="ollama:qwen3:8b",
            system="s",
            user_content="u",
            output_model=Answer,
            tools=None,
        )


def test_ollama_refuses_server_side_tools() -> None:
    """Web arama/çekme yalnızca Anthropic'te var; sessizce araçsız çalışmak yanıltıcı olur."""
    with pytest.raises(ProviderError, match="araç"):
        call_ollama(
            model="ollama:qwen3:8b",
            system="s",
            user_content="u",
            output_model=Answer,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
        )


@respx.mock
def test_unreachable_ollama_gives_a_clear_error() -> None:
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        side_effect=httpx.ConnectError("bağlantı reddedildi")
    )

    with pytest.raises(AgentError, match="Ollama'ya ulaşılamadı"):
        call_structured(
            agent="extract_jobs",
            model="ollama:qwen3:8b",
            system="s",
            user_content="u",
            output_model=Answer,
        )


@respx.mock
def test_call_structured_routes_local_model_to_ollama() -> None:
    route = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": '{"ok": true}'}, "eval_count": 5}
        )
    )

    result = call_structured(
        agent="extract_jobs",
        model="ollama:qwen3:8b",
        system="s",
        user_content="u",
        output_model=Answer,
    )

    assert route.called
    assert result.data.ok is True
