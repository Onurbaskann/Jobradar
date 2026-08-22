"""seeds/companies.yaml → Company kayıtları."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, select

from app.models import AdapterType, Company, CompanyStatus


@dataclass(slots=True)
class SeedReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] | None = None


def load_seed_file(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    companies = data.get("companies")
    if not isinstance(companies, list):
        raise ValueError("seed dosyasında 'companies' listesi bulunamadı")
    return companies


def apply_seed(session: Session, entries: list[dict[str, Any]]) -> SeedReport:
    report = SeedReport(errors=[])

    for entry in entries:
        name = (entry.get("name") or "").strip()
        domain = _normalize_domain(entry.get("domain"))
        if not name or not domain:
            report.errors.append(f"eksik name/domain: {entry!r}")  # type: ignore[union-attr]
            continue

        adapter_type = AdapterType(entry["adapter_type"]) if entry.get("adapter_type") else None
        adapter_config = entry.get("adapter_config") or {}

        existing = session.exec(select(Company).where(Company.domain == domain)).first()
        if existing is None:
            session.add(
                Company(
                    name=name,
                    domain=domain,
                    careers_url=entry.get("careers_url"),
                    adapter_type=adapter_type or AdapterType.UNKNOWN,
                    adapter_config=adapter_config,
                    # Adaptör verilmişse doğrudan taranabilir; verilmemişse probe bekler
                    status=(CompanyStatus.ACTIVE if adapter_type else CompanyStatus.PENDING),
                    source="seed",
                )
            )
            report.created += 1
            continue

        # Var olan kaydı ezmiyoruz; sadece seed'de açıkça verilen alanları güncelliyoruz
        changed = False
        if entry.get("careers_url") and existing.careers_url != entry["careers_url"]:
            existing.careers_url = entry["careers_url"]
            changed = True
        if adapter_type and existing.adapter_type != adapter_type:
            existing.adapter_type = adapter_type
            existing.adapter_config = adapter_config
            existing.status = CompanyStatus.ACTIVE
            changed = True
        if changed:
            session.add(existing)
            report.updated += 1
        else:
            report.skipped += 1

    session.commit()
    return report


def _normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    domain = value.strip().casefold()
    for prefix in ("https://", "http://"):
        domain = domain.removeprefix(prefix)
    domain = domain.removeprefix("www.").split("/")[0].split(":")[0]
    return domain or None
