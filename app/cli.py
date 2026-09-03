"""jobradar komut satırı arayüzü."""

from __future__ import annotations

import asyncio
import logging

import typer
from rich.table import Table
from sqlmodel import Session, col, select

from app.adapters.probe import ProbeConfidence, probe_company
from app.adapters.registry import get_adapter
from app.console import console
from app.db import get_engine, init_db
from app.models import AdapterType, Company, CompanyStatus, JobPosting
from app.net import HttpClient
from app.pipeline.crawl import crawl_all
from app.pipeline.seed import apply_seed, load_seed_file

app = typer.Typer(help="Türkiye odaklı iş ilanı radarı", no_args_is_help=True)


@app.callback()
def _configure(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command("init-db")
def init_db_command() -> None:
    """Uzantıları ve tabloları oluşturur."""
    init_db()
    console.print("[green]Veritabanı hazır.[/green]")


@app.command()
def seed(path: str = typer.Argument("seeds/companies.yaml")) -> None:
    """Seed dosyasındaki şirketleri veritabanına yükler."""
    entries = load_seed_file(path)
    with Session(get_engine()) as session:
        report = apply_seed(session, entries)

    console.print(
        f"[green]{report.created} yeni[/green], "
        f"[yellow]{report.updated} güncellendi[/yellow], "
        f"{report.skipped} değişmedi"
    )
    for error in report.errors or []:
        console.print(f"  [red]![/red] {error}")


@app.command()
def probe(
    company: str | None = typer.Option(None, "--company", help="Sadece bu şirket"),
    limit: int | None = typer.Option(None, "--limit"),
) -> None:
    """Adaptörü bilinmeyen şirketler için ATS tespiti dener (LLM kullanmaz)."""
    asyncio.run(_probe(company, limit))


async def _probe(company_name: str | None, limit: int | None) -> None:
    with Session(get_engine()) as session:
        query = select(Company).where(Company.adapter_type == AdapterType.UNKNOWN)
        if company_name:
            query = select(Company).where(Company.name == company_name)
        if limit:
            query = query.limit(limit)
        targets = [(c.id, c.name, c.domain, c.careers_url) for c in session.exec(query).all()]

    if not targets:
        console.print("Tespit bekleyen şirket yok.")
        return

    confirmed = guessed = 0
    async with HttpClient() as http:
        for company_id, name, domain, careers_url in targets:
            result = await probe_company(http, name=name, domain=domain, careers_url=careers_url)

            with Session(get_engine()) as session:
                record = session.get(Company, company_id)
                if record is None:
                    continue

                if result is None:
                    record.last_error = "L1 probe sonuçsuz"
                    console.print(f"  [yellow]?[/yellow] {name}: L1 ATS bulunamadı")
                else:
                    record.adapter_type = result.adapter_type
                    record.adapter_config = result.config
                    record.detection_method = result.method
                    record.detection_confidence = result.confidence
                    record.detection_evidence = result.evidence
                    record.last_error = None

                    if result.confidence is ProbeConfidence.AUTHORITATIVE:
                        record.status = CompanyStatus.ACTIVE
                        confirmed += 1
                        console.print(
                            f"  [green]✓[/green] {name}: {result.adapter_type} "
                            f"[dim]({result.method}: {result.evidence})[/dim]"
                        )
                    else:
                        # Slug tahmini yanlış şirketi işaret edebilir — taramadan önce onay iste
                        record.status = CompanyStatus.NEEDS_REVIEW
                        guessed += 1
                        console.print(
                            f"  [yellow]~[/yellow] {name}: {result.adapter_type} "
                            f"[dim](tahmin: {result.evidence}) → onay bekliyor[/dim]"
                        )

                session.add(record)
                session.commit()

    console.print(
        f"\n[green]{confirmed} doğrulandı[/green], "
        f"[yellow]{guessed} onay bekliyor[/yellow], "
        f"{len(targets) - confirmed - guessed} bulunamadı"
    )
    if guessed:
        console.print("Onay için: [bold]jobradar review[/bold]")


@app.command("set-careers")
def set_careers(
    company: str = typer.Argument(..., help="Şirket adı"),
    url: str = typer.Argument(..., help="Kariyer sayfasının adresi"),
) -> None:
    """Bir şirketin kariyer sayfasını elle bildir ve hangi katmanın işe yaradığını sına.

    Kariyer sayfasının adresini biliyorsan Brave + LLM tespit adımına ihtiyaç
    kalmaz. Sırayla denenir:
    ATS adresi mi → sayfada yapısal veri var mı → LLM çıkarımı iş görüyor mu.
    """
    asyncio.run(_set_careers(company, url))


async def _set_careers(company_name: str, url: str) -> None:
    from app.adapters.jsonld import JsonLdAdapter
    from app.adapters.llm_extract import LlmExtractAdapter
    from app.adapters.registry import detect_from_url

    with Session(get_engine()) as session:
        record = session.exec(select(Company).where(Company.name == company_name)).first()
        if record is None:
            console.print(f"[red]'{company_name}' bulunamadı.[/red] Önce seed'e ekle.")
            raise typer.Exit(1)
        company_id = record.id

    # 1. Adres zaten bilinen bir ATS'e mi işaret ediyor? (hiç istek yok)
    known = detect_from_url(url)
    if known:
        adapter_type, config = known
        console.print(f"  [green]✓[/green] Adres {adapter_type} panosuna işaret ediyor.")
        _save_careers(company_id, url, adapter_type, config, "careers_url")
        return

    # 2. Sayfada yapısal veri var mı? (bedava, LLM yok)
    # 3. Yoksa LLM çıkarımı bir şey bulabiliyor mu?
    attempts = (
        (JsonLdAdapter(), {"url": url}, AdapterType.JSONLD, "yapısal veri (JSON-LD)"),
        (
            LlmExtractAdapter(),
            {"url": url, "company_name": company_name, "company_id": company_id},
            AdapterType.LLM,
            "LLM çıkarımı",
        ),
    )

    async with HttpClient() as http:
        for adapter, config, adapter_type, label in attempts:
            console.print(f"  [dim]{label} deneniyor...[/dim]")
            try:
                jobs = await adapter.fetch(http, config)
            except Exception as exc:  # noqa: BLE001
                console.print(f"    [yellow]olmadı:[/yellow] {str(exc)[:90]}")
                continue

            if not jobs:
                console.print("    [yellow]çalıştı ama ilan bulunamadı[/yellow]")
                continue

            console.print(f"  [green]✓[/green] {label} ile {len(jobs)} ilan bulundu:")
            for job in jobs[:5]:
                console.print(f"      • {job.title[:60]} [dim]— {job.location or '?'}[/dim]")
            _save_careers(company_id, url, adapter_type, config, label)
            return

    console.print(
        "\n[yellow]Bu sayfadan ilan çıkarılamadı.[/yellow] "
        "Sayfa muhtemelen JavaScript ile doluyor — ilanlar HTML'de yok."
    )


def _save_careers(
    company_id: int | None, url: str, adapter_type: AdapterType, config: dict, method: str
) -> None:
    with Session(get_engine()) as session:
        record = session.get(Company, company_id)
        if record is None:
            return
        record.careers_url = url
        record.adapter_type = adapter_type
        record.adapter_config = config
        record.status = CompanyStatus.ACTIVE
        # Elle verilen adres yetkilidir: kaynağı sen doğruladın
        record.detection_method = "manual"
        record.detection_confidence = "authoritative"
        record.detection_evidence = f"{method}: {url}"[:500]
        record.content_hash = None
        record.source_fingerprint = None
        record.last_error = None
        session.add(record)
        session.commit()
    console.print("  [green]Kaydedildi — artık taramaya dahil.[/green]")


@app.command()
def detect(
    limit: int | None = typer.Option(None, "--limit", help="En fazla kaç şirket"),
    company: str | None = typer.Option(None, "--company"),
) -> None:
    """L1/L2/L3'te çözülemeyen şirketler için LLM tespit ajanını çalıştırır.

    Ücretlidir ve şirket başına bir kezdir. Ajanın önerisi doğrudan kabul
    edilmez; önce adaptörle gerçekten ilan döndüğü doğrulanır.
    """
    asyncio.run(_detect(company, limit))


async def _detect(company_name: str | None, limit: int | None) -> None:
    from app.agents.detect_ats import detect_ats_safe

    with Session(get_engine()) as session:
        query = select(Company).where(
            Company.adapter_type == AdapterType.UNKNOWN,
            Company.status == CompanyStatus.PENDING,
        )
        if company_name:
            query = select(Company).where(Company.name == company_name)
        if limit:
            query = query.limit(limit)
        targets = [(c.id, c.name, c.domain) for c in session.exec(query).all()]

    if not targets:
        console.print("Ajan tespiti bekleyen şirket yok.")
        return

    console.print(f"[dim]{len(targets)} şirket için LLM tespit ajanı çalışacak (ücretli).[/dim]")
    found = 0

    async with HttpClient() as http:
        for company_id, name, domain in targets:
            outcome = await detect_ats_safe(http, name=name, domain=domain, company_id=company_id)

            with Session(get_engine()) as session:
                record = session.get(Company, company_id)
                if record is None:
                    continue
                if outcome is None:
                    record.last_error = "LLM tespiti doğrulanamadı"
                    console.print(f"  [yellow]?[/yellow] {name}: doğrulanabilir kaynak bulunamadı")
                else:
                    record.adapter_type = outcome.adapter_type
                    record.adapter_config = outcome.config
                    record.careers_url = outcome.careers_url or record.careers_url
                    record.detection_method = "llm"
                    # Ajanın önerisi adaptörle doğrulandı — tahmin değil
                    record.detection_confidence = "authoritative"
                    record.detection_evidence = outcome.evidence
                    record.status = CompanyStatus.ACTIVE
                    record.last_error = None
                    found += 1
                    console.print(
                        f"  [green]✓[/green] {name}: {outcome.adapter_type} "
                        f"[dim]({outcome.evidence[:60]})[/dim]"
                    )
                session.add(record)
                session.commit()

    console.print(f"\n[green]{found}/{len(targets)}[/green] şirket ajanla çözüldü.")


@app.command()
def usage(days: int = typer.Option(30, "--days")) -> None:
    """Ajan token kullanımını ve tahmini maliyeti gösterir."""
    from datetime import timedelta

    from app.models import UsageLog, utcnow

    since = utcnow() - timedelta(days=days)
    with Session(get_engine()) as session:
        rows = session.exec(select(UsageLog).where(UsageLog.created_at >= since)).all()

    if not rows:
        console.print(f"Son {days} günde ajan çağrısı yok.")
        return

    by_agent: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        bucket = by_agent.setdefault(
            (row.agent, row.model), {"calls": 0, "in": 0, "out": 0, "cached": 0}
        )
        bucket["calls"] += 1
        bucket["in"] += row.input_tokens
        bucket["out"] += row.output_tokens
        bucket["cached"] += row.cache_read_input_tokens

    table = Table("Ajan", "Model", "Çağrı", "Girdi", "Çıktı", "Önbellekten")
    for (agent, model), stats in sorted(by_agent.items()):
        table.add_row(
            agent,
            model,
            str(stats["calls"]),
            f"{stats['in']:,}",
            f"{stats['out']:,}",
            f"{stats['cached']:,}",
        )
    console.print(table)
    console.print(
        "[dim]Önbellekten okunan token ~0.1x fiyatlanır. Sürekli 0 ise sistem "
        "promptunun sabit ön eki bozulmuş demektir.[/dim]"
    )


@app.command()
def review(
    limit: int = typer.Option(5, "--limit", help="Şirket başına gösterilecek örnek ilan"),
) -> None:
    """Tahminle bulunmuş adaptörleri örnek ilanlarla gösterir; onayla veya reddet.

    Slug tahmini yanlış şirketi işaret edebildiği için (ör. `greenhouse/insider`
    aslında Business Insider'dır) bu adım atlanmamalı.
    """
    asyncio.run(_review(limit))


async def _review(limit: int) -> None:
    with Session(get_engine()) as session:
        pending = [
            (c.id, c.name, c.domain, c.adapter_type, c.adapter_config, c.detection_evidence)
            for c in session.exec(
                select(Company).where(Company.status == CompanyStatus.NEEDS_REVIEW)
            ).all()
        ]

    if not pending:
        console.print("Onay bekleyen şirket yok.")
        return

    async with HttpClient() as http:
        for company_id, name, domain, adapter_type, config, evidence in pending:
            console.print(
                f"\n[bold]{name}[/bold] ({domain}) → {adapter_type} "
                f"[dim]tahmin edilen slug: {evidence}[/dim]"
            )
            try:
                jobs = await get_adapter(adapter_type).fetch(http, config)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]ilanlar çekilemedi: {exc}[/red]")
                continue

            for job in jobs[:limit]:
                console.print(f"    • {job.title[:60]} [dim]— {job.location or '?'}[/dim]")
            console.print(f"    [dim]toplam {len(jobs)} ilan[/dim]")

            answer = (
                typer.prompt("  Bu pano gerçekten bu şirkete mi ait? [e/h/atla]", default="atla")
                .strip()
                .lower()
            )

            with Session(get_engine()) as session:
                record = session.get(Company, company_id)
                if record is None:
                    continue
                if answer in {"e", "evet", "y", "yes"}:
                    record.status = CompanyStatus.ACTIVE
                    record.detection_confidence = "confirmed_by_user"
                    console.print("  [green]onaylandı[/green]")
                elif answer in {"h", "hayır", "hayir", "n", "no"}:
                    # Yanlış pano kalıcı olmasın; L2/L3/L4 katmanlarına düşsün
                    record.status = CompanyStatus.PENDING
                    record.adapter_type = AdapterType.UNKNOWN
                    record.adapter_config = {}
                    record.detection_method = None
                    record.detection_confidence = None
                    record.detection_evidence = None
                    console.print("  [yellow]reddedildi — sonraki katmana bırakıldı[/yellow]")
                else:
                    console.print("  [dim]atlandı[/dim]")
                session.add(record)
                session.commit()


@app.command()
def crawl(
    company: str | None = typer.Option(None, "--company"),
    limit: int | None = typer.Option(None, "--limit"),
) -> None:
    """Aktif şirketleri bir kez tarar."""
    outcomes = asyncio.run(crawl_all(company_name=company, limit=limit))

    table = Table("Şirket", "Durum", "İlan", "Yeni", "Güncel", "Kapandı", "Hata")
    for outcome in sorted(outcomes, key=lambda o: (o.status != "error", o.company)):
        colour = {"updated": "green", "unchanged": "dim", "error": "red"}.get(
            outcome.status, "yellow"
        )
        table.add_row(
            outcome.company,
            f"[{colour}]{outcome.status}[/{colour}]",
            str(outcome.fetched),
            str(outcome.created),
            str(outcome.updated),
            str(outcome.closed),
            (outcome.error or "")[:60],
        )
    console.print(table)


@app.command("companies")
def list_companies() -> None:
    """Kayıtlı şirketleri ve adaptör durumlarını listeler."""
    status_colour = {
        CompanyStatus.ACTIVE: "green",
        CompanyStatus.NEEDS_REVIEW: "yellow",
        CompanyStatus.FAILED: "red",
        CompanyStatus.REJECTED: "dim",
    }

    with Session(get_engine()) as session:
        companies = session.exec(select(Company).order_by(col(Company.name))).all()
        table = Table("Şirket", "Domain", "Adaptör", "Durum", "Tespit", "Son tarama", "Hata")
        for company in companies:
            colour = status_colour.get(company.status, "white")
            detection = (
                f"{company.detection_method}: {company.detection_evidence}"
                if company.detection_method
                else "-"
            )
            table.add_row(
                company.name,
                company.domain,
                company.adapter_type,
                f"[{colour}]{company.status}[/{colour}]",
                detection[:32],
                company.last_checked_at.strftime("%Y-%m-%d %H:%M")
                if company.last_checked_at
                else "-",
                (company.last_error or "")[:32],
            )
    console.print(table)


@app.command("jobs")
def list_jobs(
    limit: int = typer.Option(20, "--limit"),
    company: str | None = typer.Option(None, "--company"),
    include_closed: bool = typer.Option(False, "--include-closed"),
) -> None:
    """Veritabanındaki ilanları listeler."""
    with Session(get_engine()) as session:
        query = select(JobPosting, Company).join(Company)
        if not include_closed:
            query = query.where(col(JobPosting.closed_at).is_(None))
        if company:
            query = query.where(Company.name == company)
        query = query.order_by(col(JobPosting.first_seen_at).desc()).limit(limit)

        table = Table("Şirket", "Başlık", "Lokasyon", "Uzaktan", "Kanal", "Görüldü")
        for job, company_row in session.exec(query).all():
            table.add_row(
                company_row.name,
                job.title[:50],
                (job.location or "-")[:28],
                job.remote_type,
                job.apply_channel,
                job.first_seen_at.strftime("%Y-%m-%d"),
            )
    console.print(table)


if __name__ == "__main__":
    app()
