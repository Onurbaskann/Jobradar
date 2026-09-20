import base64
from email import policy
from email.parser import BytesParser

import pytest

from app.applications import gmail
from app.applications.gmail import GmailDraftGateway, GmailError, _build_raw_message
from app.config import Settings


def test_default_redirect_uri_matches_gmail_callback_route() -> None:
    settings = Settings(_env_file=None)

    assert settings.gmail_redirect_uri == (
        "http://localhost:8000/api/applications/gmail/callback"
    )


def test_builds_gmail_message_with_cv_attachment(tmp_path) -> None:
    cv_path = tmp_path / "cv.pdf"
    cv_path.write_bytes(b"example-pdf")

    raw = _build_raw_message(
        recipient_email="ik@example.com",
        subject="Backend Developer başvurusu",
        body="Merhaba, özgeçmişimi iletiyorum.",
        cover_letter="Ekibinize katkı sunmak istiyorum.",
        attachment_path=cv_path,
    )
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))

    assert message["To"] == "ik@example.com"
    assert message["Subject"] == "Backend Developer başvurusu"
    assert "özgeçmişimi" in message.get_body(preferencelist=("plain",)).get_content()
    assert "Ekibinize katkı" in message.get_body(preferencelist=("plain",)).get_content()
    assert [part.get_filename() for part in message.iter_attachments()] == ["cv.pdf"]


def test_rejects_missing_cv_attachment(tmp_path) -> None:
    with pytest.raises(GmailError, match="CV dosyası bulunamadı"):
        _build_raw_message(
            recipient_email="ik@example.com",
            subject="Başvuru",
            body="Merhaba",
            cover_letter="Ön yazı",
            attachment_path=tmp_path / "missing.pdf",
        )


def test_reports_unconfigured_gmail(tmp_path) -> None:
    settings = Settings(
        gmail_credentials_path=str(tmp_path / "missing-client.json"),
        gmail_token_path=str(tmp_path / "missing-token.json"),
    )
    gateway = GmailDraftGateway(settings)

    assert gateway.connection().configured is False
    assert gateway.connection().connected is False
    with pytest.raises(GmailError, match="kimlik dosyası bulunamadı"):
        gateway.authorization_url()


@pytest.mark.parametrize(
    ("existing_id", "expected_method"),
    [(None, "create"), ("existing-draft", "update")],
)
def test_creates_or_updates_remote_draft(
    monkeypatch,
    tmp_path,
    existing_id,
    expected_method,
) -> None:
    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("CV", encoding="utf-8")
    calls = []

    class Request:
        def execute(self):
            return {"id": "gmail-draft", "message": {"threadId": "gmail-thread"}}

    class Drafts:
        def create(self, **kwargs):
            calls.append(("create", kwargs))
            return Request()

        def update(self, **kwargs):
            calls.append(("update", kwargs))
            return Request()

    class Service:
        def users(self):
            return self

        def drafts(self):
            return Drafts()

    settings = Settings(
        gmail_credentials_path=str(tmp_path / "client.json"),
        gmail_token_path=str(tmp_path / "token.json"),
    )
    gateway = GmailDraftGateway(settings)
    monkeypatch.setattr(gateway, "_authorized_credentials", lambda: object())
    monkeypatch.setattr(gmail, "build", lambda *_args, **_kwargs: Service())

    result = gateway.upsert_draft(
        recipient_email="ik@example.com",
        subject="Başvuru",
        body="Merhaba",
        cover_letter="Ön yazı",
        attachment_path=cv_path,
        draft_id=existing_id,
    )

    assert calls[0][0] == expected_method
    assert calls[0][1]["userId"] == "me"
    assert result.draft_id == "gmail-draft"
    assert result.thread_id == "gmail-thread"
