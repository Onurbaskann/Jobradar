"""Adaptör kaydı ve URL'den adaptör tanıma."""

from __future__ import annotations

from typing import Any

from app.adapters.ashby import AshbyAdapter
from app.adapters.base import Adapter
from app.adapters.greenhouse import GreenhouseAdapter
from app.adapters.jsonld import JsonLdAdapter
from app.adapters.lever import LeverAdapter
from app.adapters.llm_extract import LlmExtractAdapter
from app.adapters.personio import PersonioAdapter
from app.adapters.recruitee import RecruiteeAdapter
from app.adapters.sitemap import SitemapAdapter
from app.adapters.smartrecruiters import SmartRecruitersAdapter
from app.adapters.workable import WorkableAdapter
from app.models import AdapterType

# Probe sırası: en yaygından en seyreğe. İlk eşleşen kazanır.
L1_ADAPTERS: tuple[Adapter, ...] = (
    GreenhouseAdapter(),
    LeverAdapter(),
    AshbyAdapter(),
    WorkableAdapter(),
    RecruiteeAdapter(),
    SmartRecruitersAdapter(),
    PersonioAdapter(),
)

# L2/L3 — ATS bulunamayan şirketler için deterministik yedek yollar.
# Sıra maliyet sırasıdır: JSON-LD tek sayfa, sitemap onlarca sayfa okur.
L2L3_ADAPTERS: tuple[Adapter, ...] = (JsonLdAdapter(), SitemapAdapter())

# L4 — son çare. Yalnızca kaynak imzası değiştiğinde çalışır (bkz. crawl.py).
L4_ADAPTERS: tuple[Adapter, ...] = (LlmExtractAdapter(),)

_BY_TYPE: dict[AdapterType, Adapter] = {
    adapter.type: adapter for adapter in (*L1_ADAPTERS, *L2L3_ADAPTERS, *L4_ADAPTERS)
}


def register(adapter: Adapter) -> None:
    """L2/L3/L4 adaptörleri kendilerini import edilirken buraya ekler."""
    _BY_TYPE[adapter.type] = adapter


def get_adapter(adapter_type: AdapterType) -> Adapter:
    try:
        return _BY_TYPE[adapter_type]
    except KeyError as exc:
        raise LookupError(f"Kayıtlı adaptör yok: {adapter_type}") from exc


def has_adapter(adapter_type: AdapterType) -> bool:
    return adapter_type in _BY_TYPE


def detect_from_url(url: str) -> tuple[AdapterType, dict[str, Any]] | None:
    """Bir kariyer sayfası URL'si bilinen bir ATS'e işaret ediyor mu?

    En ucuz tespit yolu: hiç ağ isteği yok, sadece URL deseni.
    """
    for adapter in L1_ADAPTERS:
        config = adapter.config_from_url(url)
        if config:
            return adapter.type, config
    return None
