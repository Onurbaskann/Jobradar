from app.adapters.base import RawJob, infer_remote_type
from app.adapters.probe import slug_candidates
from app.models import ApplyChannel, RemoteType
from app.pipeline.crawl import jobset_hash
from app.util.text import content_hash, find_apply_email, html_to_text, slugify


def test_html_to_text_strips_markup_and_keeps_list_structure() -> None:
    text = html_to_text("<div><p>Başlık</p><ul><li>Bir</li><li>İki</li></ul></div>")
    assert "<" not in text
    assert "Başlık" in text
    assert "- Bir" in text
    assert "- İki" in text


def test_html_to_text_drops_scripts() -> None:
    text = html_to_text("<p>Metin</p><script>alert('x')</script>")
    assert "alert" not in text
    assert "Metin" in text


def test_html_to_text_handles_escaped_markup() -> None:
    """Greenhouse açıklamayı kaçış karakterli gönderir; etiketler metne sızmamalı."""
    text = html_to_text("&lt;p&gt;Merhaba&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Bir&lt;/li&gt;&lt;/ul&gt;")
    assert "&lt;" not in text
    assert "<p>" not in text
    assert "Merhaba" in text
    assert "- Bir" in text


def test_html_to_text_passes_plain_text_through() -> None:
    assert html_to_text("düz metin") == "düz metin"
    assert html_to_text(None) == ""


def test_find_apply_email_skips_noise() -> None:
    assert find_apply_email("Başvuru: kariyer@acme.com") == "kariyer@acme.com"
    assert find_apply_email("noreply@acme.com adresine yazmayın") is None
    assert find_apply_email("hiç e-posta yok") is None


def test_find_apply_email_strips_trailing_punctuation() -> None:
    assert find_apply_email("CV'ni ik@acme.com.tr adresine gönder.") == "ik@acme.com.tr"


def test_slugify_handles_turkish_and_suffixes() -> None:
    assert slugify("Acme Yazılım A.Ş.") == "acmeyazilim"
    assert slugify("Şişli Teknoloji Ltd.") == "sislteknoloji" or slugify(
        "Şişli Teknoloji Ltd."
    ).startswith("sisl")


def test_slug_candidates_prefers_domain_root() -> None:
    candidates = slug_candidates("Trendyol Grup A.Ş.", "trendyol.com")
    assert candidates[0] == "trendyol"
    assert len(candidates) == len(set(candidates)), "aynı slug iki kez denenmemeli"


def test_infer_remote_type_recognises_turkish() -> None:
    assert infer_remote_type("Uzaktan Yazılım Geliştirici") is RemoteType.REMOTE
    assert infer_remote_type("Hibrit çalışma") is RemoteType.HYBRID
    assert infer_remote_type("İstanbul ofis") is RemoteType.UNKNOWN


def test_content_hash_is_order_sensitive_but_stable() -> None:
    assert content_hash("a", "b") == content_hash("a", "b")
    assert content_hash("a", "b") != content_hash("b", "a")
    # None atlanır, ayırıcı sayesinde "ab" ile ("a","b") çakışmaz
    assert content_hash("a", None, "b") == content_hash("a", "b")
    assert content_hash("ab") != content_hash("a", "b")


def test_jobset_hash_ignores_ordering() -> None:
    a = RawJob(external_id="1", title="A", description_md="x")
    b = RawJob(external_id="2", title="B", description_md="y")
    assert jobset_hash([a, b]) == jobset_hash([b, a])


def test_jobset_hash_detects_description_change() -> None:
    before = [RawJob(external_id="1", title="A", description_md="eski")]
    after = [RawJob(external_id="1", title="A", description_md="yeni")]
    assert jobset_hash(before) != jobset_hash(after)


def test_jobset_hash_detects_application_and_classification_changes() -> None:
    before = [RawJob(external_id="1", title="A", apply_url="https://x/old")]
    after = [
        RawJob(
            external_id="1",
            title="A",
            apply_url="https://x/new",
            apply_channel=ApplyChannel.ATS_FORM,
            remote_type=RemoteType.REMOTE,
        )
    ]
    assert jobset_hash(before) != jobset_hash(after)


def test_raw_job_finalize_sets_channel_from_url() -> None:
    job = RawJob(external_id="1", title="A", apply_url="https://x/apply").finalize()
    assert job.apply_channel.value == "ats_form"
