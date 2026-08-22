"""Tarama döngüsündeki maliyet kapısı.

Projenin maliyet iddiası tek bir davranışa dayanıyor: pahalı adaptörler
(LLM çıkarımı) yalnızca kaynağın ham imzası değiştiğinde çalışır. Bu dosya
tam olarak onu doğrular — kapı bozulursa her tarama modele para öder.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters.base import Adapter, RawJob
from app.models import AdapterType, Company, CompanyStatus
from app.net import HttpClient
from app.pipeline.crawl import crawl_company


class _StubSession:
    """crawl_company'nin "değişmedi" yolunda ihtiyaç duyduğu asgari oturum."""

    def __init__(self) -> None:
        self.commits = 0

    def add(self, _obj: Any) -> None:  # noqa: D102
        pass

    def commit(self) -> None:  # noqa: D102
        self.commits += 1


class _CountingAdapter(Adapter):
    """fetch çağrısını sayan, sabit imza döndüren sahte adaptör."""

    type = AdapterType.LLM

    def __init__(self, fingerprint: str | None) -> None:
        self.fingerprint = fingerprint
        self.fetch_calls = 0

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        self.fetch_calls += 1
        return [RawJob(external_id="1", title="Backend", description_md="x")]

    async def source_fingerprint(self, http: HttpClient, config: dict[str, Any]) -> str | None:
        return self.fingerprint


def _company(fingerprint: str | None) -> Company:
    return Company(
        id=1,
        name="Acme",
        domain="acme.com",
        adapter_type=AdapterType.LLM,
        adapter_config={"url": "https://acme.com/kariyer"},
        status=CompanyStatus.ACTIVE,
        source_fingerprint=fingerprint,
    )


@pytest.fixture
def http() -> HttpClient:
    return HttpClient(domain_delay=0.0, max_retries=0, respect_robots=False)


@pytest.fixture
def patched_adapter(monkeypatch: pytest.MonkeyPatch):
    def _install(adapter: _CountingAdapter) -> _CountingAdapter:
        import app.pipeline.crawl as crawl_mod

        monkeypatch.setattr(crawl_mod, "get_adapter", lambda _t: adapter)
        monkeypatch.setattr(crawl_mod, "has_adapter", lambda _t: True)
        return adapter

    return _install


async def test_unchanged_fingerprint_skips_fetch(http: HttpClient, patched_adapter) -> None:
    adapter = patched_adapter(_CountingAdapter("aynı-imza"))
    company = _company("aynı-imza")

    outcome = await crawl_company(http, _StubSession(), company)
    await http.aclose()

    assert outcome.status == "unchanged"
    assert adapter.fetch_calls == 0, (
        "imza değişmediği hâlde fetch çalıştı — bu, her taramada LLM maliyeti demek"
    )


async def test_changed_fingerprint_runs_fetch(http: HttpClient, patched_adapter) -> None:
    adapter = patched_adapter(_CountingAdapter("yeni-imza"))
    company = _company("eski-imza")

    class _Session(_StubSession):
        def exec(self, _query: Any):
            class _Empty:
                def first(self) -> None:
                    return None

                def all(self) -> list:
                    return []

            return _Empty()

    outcome = await crawl_company(http, _Session(), company)
    await http.aclose()

    assert adapter.fetch_calls == 1
    assert outcome.status == "updated"
    assert company.source_fingerprint == "yeni-imza", "yeni imza kaydedilmeli"


async def test_adapter_without_fingerprint_support_always_fetches(
    http: HttpClient, patched_adapter
) -> None:
    """Ücretsiz ATS adaptörleri ön kontrol yapmaz; fazladan istek anlamsız olurdu."""
    adapter = patched_adapter(_CountingAdapter(None))
    company = _company("eski-imza")

    class _Session(_StubSession):
        def exec(self, _query: Any):
            class _Empty:
                def first(self) -> None:
                    return None

                def all(self) -> list:
                    return []

            return _Empty()

    await crawl_company(http, _Session(), company)
    await http.aclose()

    assert adapter.fetch_calls == 1


async def test_first_empty_result_does_not_close_existing_jobs(
    http: HttpClient, patched_adapter
) -> None:
    adapter = patched_adapter(_CountingAdapter(None))
    adapter.fetch = lambda _http, _config: _async_result([])  # type: ignore[method-assign]
    company = _company(None)
    company.content_hash = "önceki-dolu-küme"

    session = _StubSession()
    outcome = await crawl_company(http, session, company)  # type: ignore[arg-type]
    await http.aclose()

    assert outcome.status == "skipped"
    assert company.consecutive_empty_results == 1
    assert company.content_hash == "önceki-dolu-küme"


async def test_second_empty_result_confirms_empty_job_set(
    http: HttpClient, patched_adapter
) -> None:
    adapter = patched_adapter(_CountingAdapter(None))
    adapter.fetch = lambda _http, _config: _async_result([])  # type: ignore[method-assign]
    company = _company(None)
    company.content_hash = "önceki-dolu-küme"
    company.consecutive_empty_results = 1

    class _Session(_StubSession):
        def exec(self, _query: Any):
            class _Empty:
                def first(self) -> None:
                    return None

                def all(self) -> list:
                    return []

            return _Empty()

    outcome = await crawl_company(http, _Session(), company)
    await http.aclose()

    assert outcome.status == "updated"
    assert outcome.fetched == 0
    assert company.consecutive_empty_results == 0
    assert company.content_hash != "önceki-dolu-küme"


async def _async_result(value):
    return value
