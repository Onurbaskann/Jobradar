from fastapi import HTTPException

from app.main import health, ready


class _ReadySession:
    def exec(self, _query):
        return 1


class _BrokenSession:
    def exec(self, _query):
        raise RuntimeError("parola gibi iç ayrıntılar dışarı çıkmamalı")


def test_health_is_a_db_independent_liveness_check() -> None:
    assert health() == {"status": "ok"}


def test_ready_checks_database() -> None:
    assert ready(_ReadySession()) == {"status": "ready"}  # type: ignore[arg-type]


def test_ready_returns_sanitized_503() -> None:
    try:
        ready(_BrokenSession())  # type: ignore[arg-type]
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail == "database unavailable"
    else:
        raise AssertionError("bozuk veritabanı bağlantısı hazır sayılmamalı")
