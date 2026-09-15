from __future__ import annotations

import base64
import mimetypes
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import Error as GoogleApiError

from app.config import Settings

GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
STATE_TTL = timedelta(minutes=10)
_pending_states: dict[str, datetime] = {}


class GmailError(RuntimeError):
    """Gmail yapılandırması, yetkilendirmesi veya API çağrısı başarısız."""


@dataclass(frozen=True)
class GmailConnection:
    configured: bool
    connected: bool


@dataclass(frozen=True)
class GmailDraft:
    draft_id: str
    thread_id: str | None


class GmailDraftGateway:
    def __init__(self, settings: Settings):
        self._settings = settings

    def connection(self) -> GmailConnection:
        configured = Path(self._settings.gmail_credentials_path).is_file()
        if not configured:
            return GmailConnection(configured=False, connected=False)
        credentials = self._load_credentials()
        connected = credentials is not None and (
            credentials.valid or bool(credentials.refresh_token)
        )
        return GmailConnection(configured=True, connected=connected)

    def authorization_url(self) -> str:
        self._require_client_credentials()
        flow = self._flow()
        state = secrets.token_urlsafe(32)
        _pending_states[state] = datetime.now(UTC)
        self._prune_states()
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return url

    def complete_authorization(self, authorization_response: str, state: str) -> None:
        issued_at = _pending_states.pop(state, None)
        if issued_at is None or datetime.now(UTC) - issued_at > STATE_TTL:
            raise GmailError("Gmail bağlantı isteği geçersiz veya süresi dolmuş")
        flow = self._flow(state=state)
        try:
            flow.fetch_token(authorization_response=authorization_response)
        except Exception as exc:
            raise GmailError("Gmail yetkilendirmesi tamamlanamadı") from exc
        self._save_credentials(flow.credentials)

    def upsert_draft(
        self,
        *,
        recipient_email: str,
        subject: str,
        body: str,
        cover_letter: str,
        attachment_path: Path,
        draft_id: str | None,
    ) -> GmailDraft:
        credentials = self._authorized_credentials()
        raw = _build_raw_message(
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            cover_letter=cover_letter,
            attachment_path=attachment_path,
        )
        try:
            service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
            request = (
                service.users().drafts().update(
                    userId="me", draftId=draft_id, body={"message": {"raw": raw}}
                )
                if draft_id
                else service.users().drafts().create(
                    userId="me", body={"message": {"raw": raw}}
                )
            )
            result: dict[str, Any] = request.execute()
        except (GoogleApiError, OSError, TimeoutError) as exc:
            raise GmailError("Gmail taslağı oluşturulamadı") from exc
        result_id = result.get("id")
        if not isinstance(result_id, str) or not result_id:
            raise GmailError("Gmail geçerli bir taslak kimliği döndürmedi")
        message = result.get("message") or {}
        thread_id = message.get("threadId") if isinstance(message, dict) else None
        return GmailDraft(draft_id=result_id, thread_id=thread_id)

    def _authorized_credentials(self) -> Credentials:
        credentials = self._load_credentials()
        if credentials is None:
            raise GmailError("Önce Gmail hesabını bağlamalısın")
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                self._save_credentials(credentials)
            except Exception as exc:
                raise GmailError("Gmail bağlantısı yenilenemedi; hesabı yeniden bağla") from exc
        if not credentials.valid:
            raise GmailError("Gmail bağlantısı geçersiz; hesabı yeniden bağla")
        return credentials

    def _load_credentials(self) -> Credentials | None:
        token_path = Path(self._settings.gmail_token_path)
        if not token_path.is_file():
            return None
        try:
            return Credentials.from_authorized_user_file(token_path, [GMAIL_COMPOSE_SCOPE])
        except (OSError, ValueError, TypeError):
            return None

    def _save_credentials(self, credentials: Credentials) -> None:
        token_path = Path(self._settings.gmail_token_path)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        try:
            token_path.chmod(0o600)
        except OSError:
            pass

    def _flow(self, *, state: str | None = None) -> Flow:
        try:
            flow = Flow.from_client_secrets_file(
                self._settings.gmail_credentials_path,
                scopes=[GMAIL_COMPOSE_SCOPE],
                state=state,
            )
        except (OSError, ValueError) as exc:
            raise GmailError("Gmail OAuth kimlik dosyası okunamadı") from exc
        flow.redirect_uri = self._settings.gmail_redirect_uri
        return flow

    def _require_client_credentials(self) -> None:
        if not Path(self._settings.gmail_credentials_path).is_file():
            raise GmailError("Gmail OAuth kimlik dosyası bulunamadı")

    @staticmethod
    def _prune_states() -> None:
        now = datetime.now(UTC)
        expired = [
            state
            for state, issued_at in _pending_states.items()
            if now - issued_at > STATE_TTL
        ]
        for state in expired:
            _pending_states.pop(state, None)


def _build_raw_message(
    *,
    recipient_email: str,
    subject: str,
    body: str,
    cover_letter: str,
    attachment_path: Path,
) -> str:
    if not attachment_path.is_file():
        raise GmailError("CV dosyası bulunamadı; CV'yi yeniden yükle")

    message = EmailMessage()
    try:
        message["To"] = recipient_email
        message["Subject"] = subject
    except ValueError as exc:
        raise GmailError("E-posta başlıkları geçersiz") from exc
    message.set_content(f"{body.strip()}\n\n{cover_letter.strip()}")

    mime_type, _ = mimetypes.guess_type(attachment_path.name)
    maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
    try:
        attachment = attachment_path.read_bytes()
    except OSError as exc:
        raise GmailError("CV dosyası okunamadı") from exc
    message.add_attachment(
        attachment,
        maintype=maintype,
        subtype=subtype,
        filename=attachment_path.name,
    )
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
