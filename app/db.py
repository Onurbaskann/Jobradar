from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Engine'i ilk kullanımda kurar.

    Tembel olması önemli: adaptör ve metin modülleri veritabanı sürücüsü
    kurulu olmadan da import edilebilmeli (testler ve `--help` bunu gerektirir).
    """
    return create_engine(get_settings().database_url, pool_pre_ping=True, echo=False)


def init_db() -> None:
    """Bekleyen Alembic migration'larını veritabanına uygular."""
    command.upgrade(Config("alembic.ini"), "head")


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
