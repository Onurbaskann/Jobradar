from alembic.config import Config

from app import db


def test_init_db_upgrades_to_head(monkeypatch) -> None:
    call: dict[str, object] = {}

    def fake_upgrade(config: Config, revision: str) -> None:
        call["config"] = config
        call["revision"] = revision

    monkeypatch.setattr(db.command, "upgrade", fake_upgrade)

    db.init_db()

    config = call["config"]
    assert isinstance(config, Config)
    assert isinstance(config.config_file_name, str)
    assert config.config_file_name == "alembic.ini"
    assert call["revision"] == "head"
