from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.config import get_settings

EMBED_DIM = get_settings().embedding_dim


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- enums


class AdapterType(StrEnum):
    """Bir şirketin ilanlarını hangi katmandan çektiğimiz."""

    # L1 — ATS public API
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKABLE = "workable"
    RECRUITEE = "recruitee"
    PERSONIO = "personio"
    SMARTRECRUITERS = "smartrecruiters"
    # L2 / L3 — deterministik HTML kaynakları
    JSONLD = "jsonld"
    SITEMAP = "sitemap"
    # L4 — LLM çıkarımı (son çare)
    LLM = "llm"
    # henüz tespit edilmedi
    UNKNOWN = "unknown"


L1_ADAPTERS = frozenset(
    {
        AdapterType.GREENHOUSE,
        AdapterType.LEVER,
        AdapterType.ASHBY,
        AdapterType.WORKABLE,
        AdapterType.RECRUITEE,
        AdapterType.PERSONIO,
        AdapterType.SMARTRECRUITERS,
    }
)


class CompanyStatus(StrEnum):
    PENDING = "pending"  # adaptör tespiti bekliyor
    NEEDS_REVIEW = "needs_review"  # adaptör tahminle bulundu, insan onayı bekliyor
    ACTIVE = "active"
    FAILED = "failed"  # tespit veya tarama sürekli başarısız
    REJECTED = "rejected"  # kullanıcı istemiyor


class RemoteType(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class ApplyChannel(StrEnum):
    EMAIL = "email"  # ilanda başvuru e-postası var → biz gönderebiliriz
    ATS_FORM = "ats_form"  # form doldurulacak → paket hazırlayıp link veririz
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class MatchStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    DISMISSED = "dismissed"
    APPROVED = "approved"
    SENT = "sent"


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    REPLIED = "replied"
    REJECTED = "rejected"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DiscoveryRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobLeadStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    DISMISSED = "dismissed"


class MatchQueueStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ResumeProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------- tables


class Company(SQLModel, table=True):
    __tablename__ = "company"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    domain: str = Field(index=True, unique=True)
    careers_url: str | None = None

    adapter_type: AdapterType = Field(default=AdapterType.UNKNOWN, index=True)
    # Adaptöre özel ayarlar: {"token": "trendyol"} / {"site": "getir"} / {"url": "..."}
    adapter_config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))

    status: CompanyStatus = Field(default=CompanyStatus.PENDING, index=True)
    source: str = "seed"  # seed | discovery | manual

    # Adaptörün nasıl bulunduğu. Tahminle bulunanlar onaylanana kadar taranmaz —
    # slug çakışmaları yanlış şirketin ilanlarını sisteme sokabiliyor.
    detection_method: str | None = None  # careers_url | site_link | slug | llm
    detection_confidence: str | None = None  # authoritative | guess
    detection_evidence: str | None = None  # kanıt URL'si veya denenen slug

    # Çekilen ilan kümesinin hash'i — yazma işini atlamak için
    content_hash: str | None = None
    # Kaynağın ham imzası. Adaptör çalıştırılmadan ÖNCE kontrol edilir; pahalı
    # adaptörlerde (LLM çıkarımı) modelin hiç çağrılmamasını sağlayan kanca budur.
    source_fingerprint: str | None = None
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    # Daha önce ilanı olan bir kaynaktan tek seferlik boş cevap gelmesi bütün
    # ilanları yanlışlıkla kapatmasın. İkinci ardışık boş sonuç doğrulama sayılır.
    consecutive_empty_results: int = 0
    last_error: str | None = None

    created_at: datetime = Field(default_factory=utcnow)


class JobPosting(SQLModel, table=True):
    __tablename__ = "job_posting"
    __table_args__ = (UniqueConstraint("company_id", "external_id", name="uq_job_company_ext"),)

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id", index=True)
    # Kaynaktaki kimlik; yoksa URL/başlık hash'i kullanılır
    external_id: str = Field(index=True)

    title: str
    location: str | None = None
    remote_type: RemoteType = RemoteType.UNKNOWN
    seniority: str | None = None
    department: str | None = None
    employment_type: str | None = None
    description_md: str = ""

    apply_channel: ApplyChannel = ApplyChannel.UNKNOWN
    apply_email: str | None = None
    apply_url: str | None = None

    posted_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utcnow, index=True)
    last_seen_at: datetime = Field(default_factory=utcnow)
    closed_at: datetime | None = None  # taramada artık görünmüyorsa doldurulur

    source_adapter: AdapterType = AdapterType.UNKNOWN
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))

    embedding: list[float] | None = Field(default=None, sa_column=Column(Vector(EMBED_DIM)))


class Profile(SQLModel, table=True):
    __tablename__ = "profile"

    id: int | None = Field(default=None, primary_key=True)
    name: str = "default"
    # Geçiş tamamlanana kadar veritabanı uyumluluğu için tutulur. Yeni kod CV
    # verisini yalnız Resume ve alt tablolarından okur/yazar.
    cv_file_path: str | None = None
    cv_original_filename: str | None = None
    cv_text: str = ""
    cv_summary: str = ""
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    # {"locations": [...], "remote_ok": true, "seniority": [...], "blocklist": [...]}
    preferences: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))
    embedding: list[float] | None = Field(default=None, sa_column=Column(Vector(EMBED_DIM)))
    updated_at: datetime = Field(default_factory=utcnow)


class Resume(SQLModel, table=True):
    """Adayın yüklediği CV'nin sürümlenmiş, metin olarak işlenmiş hali."""

    __tablename__ = "resume"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_resume_profile_version"),
        UniqueConstraint("profile_id", "sha256", name="uq_resume_profile_hash"),
    )

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profile.id", index=True)
    version: int
    original_filename: str
    file_path: str
    sha256: str | None = Field(default=None, index=True)
    mime_type: str
    extracted_text: str = ""
    language: str | None = None
    summary: str = ""
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    status: ResumeProcessingStatus = Field(
        default=ResumeProcessingStatus.PENDING,
        sa_column=Column(String, nullable=False, index=True),
    )
    parser_version: str = ""
    extraction_model: str | None = None
    processing_error: str | None = None
    uploaded_at: datetime = Field(default_factory=utcnow, index=True)
    processed_at: datetime | None = None


class ResumeExperience(SQLModel, table=True):
    __tablename__ = "resume_experience"

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resume.id", index=True, ondelete="CASCADE")
    employer: str
    title: str
    location: str | None = None
    start_year: int | None = None
    start_month: int | None = None
    end_year: int | None = None
    end_month: int | None = None
    is_current: bool = False
    description: str = ""
    display_order: int = 0


class ResumeEducation(SQLModel, table=True):
    __tablename__ = "resume_education"

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resume.id", index=True, ondelete="CASCADE")
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    location: str | None = None
    start_year: int | None = None
    start_month: int | None = None
    end_year: int | None = None
    end_month: int | None = None
    description: str = ""
    display_order: int = 0


class ResumeProject(SQLModel, table=True):
    __tablename__ = "resume_project"

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resume.id", index=True, ondelete="CASCADE")
    name: str
    role: str | None = None
    url: str | None = None
    start_year: int | None = None
    start_month: int | None = None
    end_year: int | None = None
    end_month: int | None = None
    description: str = ""
    display_order: int = 0


class ResumeSkill(SQLModel, table=True):
    __tablename__ = "resume_skill"
    __table_args__ = (
        UniqueConstraint("resume_id", "normalized_name", name="uq_resume_skill_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resume.id", index=True, ondelete="CASCADE")
    name: str
    normalized_name: str
    category: str | None = None
    evidence: str = ""


class ResumeCertification(SQLModel, table=True):
    __tablename__ = "resume_certification"

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resume.id", index=True, ondelete="CASCADE")
    name: str
    issuer: str | None = None
    issue_year: int | None = None
    issue_month: int | None = None
    expiry_year: int | None = None
    expiry_month: int | None = None
    credential_id: str | None = None
    credential_url: str | None = None
    display_order: int = 0


class ResumeLanguage(SQLModel, table=True):
    __tablename__ = "resume_language"
    __table_args__ = (
        UniqueConstraint("resume_id", "normalized_name", name="uq_resume_language_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resume.id", index=True, ondelete="CASCADE")
    name: str
    normalized_name: str
    level: str | None = None


class ResumeAssessment(SQLModel, table=True):
    __tablename__ = "resume_assessment"
    __table_args__ = (
        UniqueConstraint("resume_id", "rubric_version", name="uq_resume_assessment_rubric"),
    )

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resume.id", index=True, ondelete="CASCADE")
    rubric_version: str = "1"
    overall_score: int
    parsing_score: int
    contact_score: int
    section_score: int
    chronology_score: int
    evidence_score: int
    consistency_score: int
    findings: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    assessed_at: datetime = Field(default_factory=utcnow)


class Match(SQLModel, table=True):
    __tablename__ = "match"
    __table_args__ = (UniqueConstraint("job_id", "profile_id", name="uq_match_job_profile"),)

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job_posting.id", index=True)
    profile_id: int = Field(foreign_key="profile.id", index=True)

    prefilter_passed: bool = False
    prefilter_reason: str | None = None  # neden elendiği (şeffaflık için)
    embedding_score: float | None = None
    llm_score: int | None = Field(default=None, index=True)
    rationale: str | None = None
    gaps: list[str] = Field(default_factory=list, sa_column=Column(JSONB))

    status: MatchStatus = Field(default=MatchStatus.NEW, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Application(SQLModel, table=True):
    __tablename__ = "application"

    id: int | None = Field(default=None, primary_key=True)
    lead_match_id: int | None = Field(
        default=None,
        foreign_key="lead_match.id",
        index=True,
        unique=True,
        ondelete="SET NULL",
    )
    job_title: str = ""
    company_name: str = ""

    tailored_cv_path: str | None = None
    cover_letter: str = ""
    recipient_email: str = ""
    email_subject: str = ""
    email_body: str = ""

    channel: ApplyChannel = ApplyChannel.UNKNOWN
    status: ApplicationStatus = Field(default=ApplicationStatus.DRAFT, index=True)
    gmail_draft_id: str | None = None
    gmail_thread_id: str | None = None
    sent_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class DiscoveryCandidate(SQLModel, table=True):
    """Keşif ajanının bulduğu, henüz onaylanmamış şirket adayları."""

    __tablename__ = "discovery_candidate"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    domain: str = Field(index=True, unique=True)
    source: str  # kap | teknopark | list:<url> | ...
    confidence: float = 0.0
    note: str | None = None
    status: CandidateStatus = Field(default=CandidateStatus.PENDING, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class SearchProfile(SQLModel, table=True):
    """Tekrarlanabilir ilan arama ölçütleri."""

    __tablename__ = "search_profile"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    query: str
    location: str = "Türkiye"
    remote_only: bool = False
    hours_old: int = 168
    results_wanted: int = 30
    sources: list[str] = Field(
        default_factory=lambda: ["tracked", "jobspy", "turkiye_web"],
        sa_column=Column(JSONB),
    )
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DiscoveryRun(SQLModel, table=True):
    """Bir arama profilinin tek keşif çalışması."""

    __tablename__ = "discovery_run"

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="search_profile.id", index=True)
    status: DiscoveryRunStatus = Field(default=DiscoveryRunStatus.PENDING, index=True)
    found_count: int = 0
    new_count: int = 0
    source_results: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobLead(SQLModel, table=True):
    """Bir veya daha fazla keşif kaynağından normalize edilmiş ilan adayı."""

    __tablename__ = "job_lead"

    id: int | None = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True, unique=True)
    title: str
    company_name: str = Field(index=True)
    location: str | None = None
    remote_type: RemoteType = RemoteType.UNKNOWN
    description_md: str = ""
    apply_url: str | None = None
    posted_at: datetime | None = None
    sources: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    status: JobLeadStatus = Field(default=JobLeadStatus.NEW, index=True)
    last_run_id: int | None = Field(default=None, foreign_key="discovery_run.id", index=True)
    first_seen_at: datetime = Field(default_factory=utcnow, index=True)
    last_seen_at: datetime = Field(default_factory=utcnow)


class LeadMatch(SQLModel, table=True):
    """Keşfedilen bir ilanın belirli CV profiliyle değerlendirmesi."""

    __tablename__ = "lead_match"
    __table_args__ = (UniqueConstraint("lead_id", "resume_id", name="uq_lead_match_resume"),)

    id: int | None = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="job_lead.id", index=True)
    profile_id: int = Field(foreign_key="profile.id", index=True)
    resume_id: int | None = Field(default=None, foreign_key="resume.id", index=True)
    score: int
    rationale: str
    gaps: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    model: str
    updated_at: datetime = Field(default_factory=utcnow)


class MatchQueueItem(SQLModel, table=True):
    """Yerel LLM tarafından sırayla işlenecek kalıcı değerlendirme işi."""

    __tablename__ = "match_queue_item"
    __table_args__ = (
        UniqueConstraint("run_id", "lead_id", "resume_id", name="uq_match_queue_run_lead"),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="discovery_run.id", index=True)
    lead_id: int = Field(foreign_key="job_lead.id", index=True)
    profile_id: int = Field(foreign_key="profile.id", index=True)
    resume_id: int | None = Field(default=None, foreign_key="resume.id", index=True)
    position: int
    status: MatchQueueStatus = Field(
        default=MatchQueueStatus.PENDING,
        sa_column=Column(String, nullable=False, index=True),
    )
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class UsageLog(SQLModel, table=True):
    """Her ajan çağrısının token/maliyet kaydı — panelde günlük harcama için."""

    __tablename__ = "usage_log"

    id: int | None = Field(default=None, primary_key=True)
    agent: str = Field(index=True)  # detect_ats | extract_jobs | score_match | tailor
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    batch: bool = False
    company_id: int | None = None
    job_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
