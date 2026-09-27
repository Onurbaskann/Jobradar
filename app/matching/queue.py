from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.agents.client import AgentError
from app.agents.workload import interactive_model_call_pending
from app.db import get_engine
from app.matching.service import MatchInputError, score_lead
from app.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    JobLead,
    LeadMatch,
    MatchQueueItem,
    MatchQueueStatus,
    Profile,
    utcnow,
)

log = logging.getLogger(__name__)
ACTIVE_QUEUE_STATUSES = (MatchQueueStatus.PENDING, MatchQueueStatus.PROCESSING)


@dataclass(frozen=True)
class QueueSummary:
    considered: int = 0
    queued: int = 0
    skipped: int = 0


def enqueue_prioritized_leads(
    session: Session,
    *,
    run_id: int,
    leads: list[JobLead],
    limit: int,
    reevaluate_existing: bool,
) -> QueueSummary:
    profile = session.exec(select(Profile).order_by(Profile.id)).first()
    if profile is None or profile.id is None or not profile.cv_text.strip() or limit <= 0:
        return QueueSummary()

    candidates = leads[:limit]
    lead_ids = [lead.id for lead in candidates if lead.id is not None]
    matched_ids: set[int] = set()
    if lead_ids and not reevaluate_existing:
        matched_ids = set(
            session.exec(
                select(LeadMatch.lead_id).where(
                    LeadMatch.profile_id == profile.id,
                    col(LeadMatch.lead_id).in_(lead_ids),
                )
            ).all()
        )
    active_ids = set(
        session.exec(
            select(MatchQueueItem.lead_id).where(
                MatchQueueItem.profile_id == profile.id,
                col(MatchQueueItem.status).in_(ACTIVE_QUEUE_STATUSES),
            )
        ).all()
    )

    queued = skipped = 0
    for position, lead in enumerate(candidates, start=1):
        if lead.id is None or lead.id in active_ids or lead.id in matched_ids:
            skipped += 1
            continue
        session.add(
            MatchQueueItem(
                run_id=run_id,
                lead_id=lead.id,
                profile_id=profile.id,
                position=position,
            )
        )
        queued += 1
    session.commit()
    return QueueSummary(considered=len(candidates), queued=queued, skipped=skipped)


def list_active_queue(session: Session) -> list[MatchQueueItem]:
    return list(
        session.exec(
            select(MatchQueueItem)
            .where(col(MatchQueueItem.status).in_(ACTIVE_QUEUE_STATUSES))
            .order_by(col(MatchQueueItem.created_at), col(MatchQueueItem.position))
        ).all()
    )


def recover_interrupted_work() -> None:
    with Session(get_engine()) as session:
        for item in session.exec(
            select(MatchQueueItem).where(
                MatchQueueItem.status == MatchQueueStatus.PROCESSING
            )
        ).all():
            item.status = MatchQueueStatus.PENDING
            item.started_at = None
            session.add(item)
        for run in session.exec(
            select(DiscoveryRun).where(DiscoveryRun.status == DiscoveryRunStatus.RUNNING)
        ).all():
            run.status = DiscoveryRunStatus.FAILED
            run.error = "Uygulama yeniden başlatıldığı için tarama yarıda kaldı"
            run.completed_at = utcnow()
            session.add(run)
        session.commit()


def process_next_queued_match() -> bool:
    with Session(get_engine()) as session:
        item = session.exec(
            select(MatchQueueItem)
            .join(DiscoveryRun, DiscoveryRun.id == MatchQueueItem.run_id)
            .where(MatchQueueItem.status == MatchQueueStatus.PENDING)
            .where(DiscoveryRun.status == DiscoveryRunStatus.COMPLETED)
            .order_by(col(MatchQueueItem.created_at), col(MatchQueueItem.position))
        ).first()
        if item is None or item.id is None:
            return False
        item.status = MatchQueueStatus.PROCESSING
        item.started_at = utcnow()
        item.error = None
        session.add(item)
        session.commit()
        item_id = item.id
        run_id = item.run_id

        try:
            score_lead(session, item.lead_id)
            status = MatchQueueStatus.COMPLETED
            error = None
        except (MatchInputError, LookupError) as exc:
            status = MatchQueueStatus.SKIPPED
            error = str(exc)[:240]
        except AgentError as exc:
            status = MatchQueueStatus.FAILED
            error = str(exc)[:240]
            log.warning("Kuyruktaki ilan değerlendirilemedi (lead_id=%s): %s", item.lead_id, exc)
        except Exception as exc:  # noqa: BLE001 — tek iş worker'ı durdurmamalı
            session.rollback()
            status = MatchQueueStatus.FAILED
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            log.exception("Eşleştirme kuyruğu işi başarısız (item_id=%s)", item_id)

        current = session.get(MatchQueueItem, item_id)
        if current is not None:
            current.status = status
            current.error = error
            current.completed_at = utcnow()
            session.add(current)
        _update_run_progress(session, run_id)
        session.commit()
        return True


def _update_run_progress(session: Session, run_id: int) -> None:
    run = session.get(DiscoveryRun, run_id)
    if run is None:
        return
    items = list(
        session.exec(select(MatchQueueItem).where(MatchQueueItem.run_id == run_id)).all()
    )
    counts = {status: 0 for status in MatchQueueStatus}
    for item in items:
        counts[item.status] += 1
    active = counts[MatchQueueStatus.PENDING] + counts[MatchQueueStatus.PROCESSING]
    result = dict(run.source_results)
    final_status = "partial" if counts[MatchQueueStatus.FAILED] else "completed"
    result["automatic_matching"] = {
        "status": "processing" if active else final_status,
        "queued": len(items),
        "pending": counts[MatchQueueStatus.PENDING],
        "processing": counts[MatchQueueStatus.PROCESSING],
        "completed": counts[MatchQueueStatus.COMPLETED],
        "skipped": counts[MatchQueueStatus.SKIPPED],
        "failed": counts[MatchQueueStatus.FAILED],
    }
    run.source_results = result
    session.add(run)


async def run_matching_worker() -> None:
    while True:
        if interactive_model_call_pending():
            await asyncio.sleep(0.25)
            continue
        processed = await asyncio.to_thread(process_next_queued_match)
        await asyncio.sleep(0.25 if processed else 1.5)
