from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Engine'i ilk kullanımda kurar.

    Tembel olması önemli: adaptör ve metin modülleri veritabanı sürücüsü
    kurulu olmadan da import edilebilmeli (testler ve `--help` bunu gerektirir).
    """
    return create_engine(get_settings().database_url, pool_pre_ping=True, echo=False)


def init_db() -> None:
    """Uzantıları ve tabloları oluşturur. Şema oturana kadar Alembic yerine bu kullanılır."""
    import app.models  # noqa: F401  — tabloların metadata'ya kaydolması için

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    SQLModel.metadata.create_all(engine)
    # create_all mevcut tabloya sütun eklemez. Alembic'e geçiş tamamlanana kadar
    # bu geriye uyumlu değişiklik mevcut kurulumları güvenle yükseltir.
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE company ADD COLUMN IF NOT EXISTS "
                "consecutive_empty_results INTEGER NOT NULL DEFAULT 0"
            )
        )


@contextmanager
def session_scope() -> Iterator[Session]:
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(get_engine()) as session:
        yield session
