from sqlalchemy import String

from app.matching.queue import QueueSummary, _update_run_progress, enqueue_prioritized_leads
from app.models import (
    DiscoveryRun,
    JobLead,
    MatchQueueItem,
    MatchQueueStatus,
    Profile,
)


class Result:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value

    def all(self):
        return self.value


def test_queue_status_uses_portable_string_column() -> None:
    assert isinstance(MatchQueueItem.__table__.c.status.type, String)


def lead(lead_id: int) -> JobLead:
    return JobLead(
        id=lead_id,
        fingerprint=f"lead-{lead_id}",
        title="Backend Developer",
        company_name="Acme",
        description_md="Ayrıntılı ilan açıklaması " * 5,
    )


def test_enqueue_uses_first_candidates_and_skips_existing_or_active() -> None:
    class Session:
        def __init__(self):
            self.results = iter(
                [
                    Result(Profile(id=5, name="Onur", cv_text="Backend CV")),
                    Result([1]),
                    Result([2]),
                ]
            )
            self.added = []

        def exec(self, _query):
            return next(self.results)

        def add(self, item):
            self.added.append(item)

        def commit(self):
            pass

    session = Session()
    summary = enqueue_prioritized_leads(  # type: ignore[arg-type]
        session,
        run_id=7,
        leads=[lead(1), lead(2), lead(3), lead(4)],
        limit=3,
        reevaluate_existing=False,
    )

    assert summary == QueueSummary(considered=3, queued=1, skipped=2)
    assert [(item.lead_id, item.position) for item in session.added] == [(3, 3)]


def test_run_progress_reflects_queue_state() -> None:
    run = DiscoveryRun(id=7, profile_id=1, source_results={"jobspy": {"status": "completed"}})
    items = [
        MatchQueueItem(
            run_id=7, lead_id=1, profile_id=1, position=1, status=MatchQueueStatus.COMPLETED
        ),
        MatchQueueItem(
            run_id=7, lead_id=2, profile_id=1, position=2, status=MatchQueueStatus.PROCESSING
        ),
        MatchQueueItem(
            run_id=7, lead_id=3, profile_id=1, position=3, status=MatchQueueStatus.PENDING
        ),
    ]

    class Session:
        def get(self, _model, _ident):
            return run

        def exec(self, _query):
            return Result(items)

        def add(self, _item):
            pass

    _update_run_progress(Session(), 7)  # type: ignore[arg-type]

    assert run.source_results["jobspy"] == {"status": "completed"}
    assert run.source_results["automatic_matching"] == {
        "status": "processing",
        "queued": 3,
        "pending": 1,
        "processing": 1,
        "completed": 1,
        "skipped": 0,
        "failed": 0,
    }
