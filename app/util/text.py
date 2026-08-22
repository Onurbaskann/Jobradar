"""HTML → düz metin ve küçük normalizasyon yardımcıları.

ATS API'leri ilan açıklamalarını HTML olarak döner. Ham HTML'i ne veritabanına
ne de LLM'e gönderiyoruz; her ikisi de token ve gürültü demek.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

from selectolax.parser import HTMLParser

_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "template")
_WS = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")


def html_to_text(raw: str | None) -> str:
    """HTML parçasını okunabilir düz metne çevirir. Zaten düz metinse dokunmaz."""
    if not raw:
        return ""

    # Greenhouse gibi bazı ATS'ler açıklamayı kaçış karakterli gönderir
    # ("&lt;p&gt;..."). Bir kez çözmezsek etiketler metne karışır.
    if "<" not in raw and "&lt;" in raw:
        raw = html.unescape(raw)

    if "<" not in raw:
        return normalize_ws(html.unescape(raw))

    tree = HTMLParser(raw)
    for tag in _DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()

    # Liste öğelerini madde işaretine çevir ki açıklamanın yapısı kaybolmasın
    for node in tree.css("li"):
        text = node.text(deep=True, separator=" ").strip()
        if text:
            node.replace_with(f"\n- {text}\n")

    body = tree.body or tree.root
    if body is None:
        return normalize_ws(html.unescape(raw))

    return normalize_ws(html.unescape(body.text(deep=True, separator="\n")))


def normalize_ws(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKS.sub("\n\n", text).strip()


def content_hash(*parts: object) -> str:
    """Değişiklik tespiti için kararlı hash. Sıra korunur, None'lar atlanır."""
    digest = hashlib.sha256()
    for part in parts:
        if part is None:
            continue
        digest.update(str(part).encode("utf-8", errors="replace"))
        digest.update(b"\x1e")
    return digest.hexdigest()


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Görsel olarak e-postaya benzeyen ama başvuru adresi olmayan kalıplar
_EMAIL_BLOCKLIST = re.compile(
    r"(noreply|no-reply|donotreply|example\.|sentry\.io|@2x|\.png|\.jpg)", re.I
)


def find_apply_email(text: str) -> str | None:
    """İlan metninde başvuru e-postası ara. Bulamazsa None."""
    for candidate in _EMAIL.findall(text or ""):
        if not _EMAIL_BLOCKLIST.search(candidate):
            return candidate.rstrip(".,;:)")
    return None


def slugify(value: str) -> str:
    """Şirket adından ATS slug tahmini üretir: 'Acme Yazılım A.Ş.' → 'acmeyazilim'."""
    value = unicodedata.normalize("NFKD", value.lower())
    replacements = {"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"}
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"\b(a\.?s|ltd|sti|inc|corp|gmbh|bv|llc|co)\b\.?", "", value)
    return re.sub(r"[^a-z0-9]", "", value)
