# jobradar

Türkiye'deki şirketlerin iş ilanlarını bulan, CV'ne göre skorlayan ve onayınla başvuru gönderen araç.

## Nasıl çalışır

İlan keşfi 4 katmanlı ve **kademeli** — pahalı olan en sona bırakılır:

| Katman | Kaynak | Maliyet |
|---|---|---|
| L1 | ATS public API'leri (Greenhouse, Lever, Ashby, Workable, Recruitee, Personio, SmartRecruiters) | Sıfır, deterministik |
| L2 | Kariyer sayfasındaki `schema.org/JobPosting` JSON-LD | Sıfır, deterministik |
| L3 | Sitemap / RSS | Sıfır, deterministik |
| L4 | LLM çıkarım ajanı — sadece sayfa hash'i değiştiğinde | Ucuz model, seyrek |

Her şirket bir kez adaptöre bağlanır, sonra hep aynı ucuz yoldan taranır.

## Kurulum

```bash
cp .env.example .env        # POSTGRES_PASSWORD ve kullanacağın API anahtarlarını doldur
docker compose up -d db
docker compose run --rm app jobradar init-db
```

Mevcut bir kurulumu yeni sürüme yükselttikten sonra da `jobradar init-db`
komutunu bir kez çalıştır. Komut mevcut veriyi silmez; eksik geriye uyumlu
şema alanlarını ekler.

Tüm uygulamayı başlatmak için:

```bash
docker compose up -d --build app
docker compose exec app jobradar init-db
```

Arayüz `http://localhost:8000` adresindedir. Burada arama profili oluşturabilir,
JobSpy, takip edilen şirketler ve Türkiye portal aramasını birlikte taratabilir;
bulunan ilanları yeni / kısa liste / elenen durumlarında yönetebilirsin. JobSpy
bağımlılığı Docker'ın Python 3.12 imajında kurulur.

Kariyer.net, Secretcv ve Yenibiriş sonuçları portalları doğrudan kazımadan,
Brave Search API'nin resmi web arama ucu üzerinden bulunur. Bu isteğe bağlı
kaynak için [Brave Search API panelinden](https://api-dashboard.search.brave.com/)
bir anahtar oluşturup `.env` dosyasına ekle:

```bash
BRAVE_SEARCH_API_KEY=...
```

Anahtar tanımlı değilse yalnızca `turkiye_web` kaynağı hata verir; takip edilen
şirketler ve JobSpy taraması çalışmaya devam eder.

## Kullanım

```bash
# 1. Takip edilecek şirketleri yükle
docker compose run --rm app jobradar seed seeds/companies.yaml

# 2. Hangi şirketin hangi ATS'i kullandığını bul (LLM kullanmaz, sadece ağ denemesi)
docker compose run --rm app jobradar probe

# 3. Tahminle bulunanları onayla (aşağıdaki nota bak — bu adımı atlama)
docker compose run --rm app jobradar review

# 4. Hâlâ çözülemeyenler için LLM tespit ajanı (ücretli, şirket başına bir kez)
docker compose run --rm app jobradar detect

# 5. Tara
docker compose run --rm app jobradar crawl

# 6. Sonuçlara bak
docker compose run --rm app jobradar companies
docker compose run --rm app jobradar jobs --limit 30
docker compose run --rm app jobradar usage      # ajan token harcaması
```

`probe` ve `crawl` hiçbir LLM çağrısı yapmaz. Ücretli olan tek adım `detect`,
ve o da şirket başına bir kez çalışır. Tarama sırasında LLM yalnızca L4
adaptörüne düşmüş şirketlerde ve **yalnızca sayfanın ham imzası değiştiğinde**
devreye girer.

### Neden bir onay adımı var

`probe` iki farklı güçte kanıt üretir:

- **Yetkili** — şirketin kendi alan adı (veya kariyer alt alan adı) ATS panosuna
  link veriyor. Doğrudan aktifleşir.
- **Tahmin** — şirket adından türetilen slug bir panoda karşılık buldu, ama o
  panonun bu şirkete ait olduğuna dair kanıt yok. Bunlar `needs_review`
  durumunda bekler ve taranmaz.

Tahminler neden karantinaya alınıyor: canlı ölçümde 5 slug isabetinin 2'si yanlış
şirketti — `greenhouse/peak` bir Teksas fizik tedavi zinciri, `greenhouse/insider`
ise Business Insider. Onaysız aktifleştirilseler CV'n Teksas klinik ilanlarına
karşı skorlanırdı.

Eski istatistik paneli: http://localhost:8000/stats
Canlılık kontrolü `/health`, veritabanını da sınayan hazır olma kontrolü `/ready`
adresindedir.

## Yerel model (Ollama) desteği

Model adı sağlayıcıyı belirler — ayrı bir ayar yok:

```bash
MODEL_EXTRACT=ollama:qwen3:8b     # yerelde, ücretsiz
MODEL_DETECT=ollama:qwen3:8b      # Brave sonuçlarını yerelde yorumlar
```

**qwen3:8b ile yapılan ölçüm** (doğru cevabı bilinen iki test):

| Test | Beklenen | Sonuç |
|---|---|---|
| iyzico ilan sayfası | 12 ilan | **12/12 doğru**, kaçan yok, uydurma yok |
| Craftgate (ilan yok) | 0 ilan | **0 ilan**, doğru şekilde "liste sayfası değil" dedi |

Kalite tam isabet. Sınır hızda: bu makinede model **GPU değil CPU** kullanıyor
(Intel Arc, Ollama'nın standart Windows kurulumunda desteklenmiyor), yaklaşık
**4 token/saniye** üretiyor. İlan çıkarımı sayfa başına birkaç dakika sürüyor.

Bu, arka planda çalışan bir tarayıcı için sorun değil — çıkarım zaten yalnızca
sayfa gerçekten değiştiğinde yapılıyor.

Kariyer sayfası/ATS tespitinde web aramasını Brave yapar; sonuçları Qwen yerelde
yorumlar. Modelin önerisi doğrudan kabul edilmez, ilgili ATS adaptörü gerçek ilan
döndürmeden şirket kaynağı aktifleşmez.

## Türkiye'de ölçülen gerçek durum

Onlarca Türk şirketinin kariyer sayfası denendi. Bulgular, bu projenin neden
kademeli tasarlandığını açıklıyor:

| Ne bulundu | Örnek | Sonuç |
|---|---|---|
| Bilinen ATS kullanıyor | Trendyol (Lever), iyzico (Lever) | ✅ Bedava ve güvenilir |
| Sayfa var, ilanlar JavaScript ile yükleniyor | obilet (`[jobs]` yer tutucusu) | ❌ HTML'de ilan yok |
| Bot koruması engelliyor | Papara, Getir, Hepsiburada (403) | ❌ Sayfaya erişilemiyor |
| İlan yok, başvuru e-postayla | Craftgate (`talent@craftgate.io`) | ⚠️ Çıkarılacak ilan yok |
| Sayfa geçici olarak başka içerikte | Param (TMSF duyurusu) | ⚠️ Şimdilik ilan yok |

**Önemli sonuç:** JavaScript ile dolan sayfalarda yapay zekâ da işe yaramaz —
ortada okunacak metin yoktur. Bu sayfalar için ayrı bir yetenek (başsız
tarayıcı) gerekir; bu henüz kapsam dışı ve ayrı bir karar.

## Durum

| Faz | Kapsam | Durum |
|---|---|---|
| 0 | İskelet, veri modeli, Docker | ✅ |
| 1 | 7 ATS adaptörü, kanıtlı tespit, onay akışı | ✅ gerçek ilanlarla doğrulandı |
| 2 | JSON-LD, sitemap, robots.txt, değişiklik tespiti | ✅ gerçek sitelerde ölçüldü |
| 3 | Brave + yerel Qwen tespit ve çıkarım ajanları | ✅ Trendyol üzerinde canlı doğrulandı |
| 4 | CV profili ve eşleştirme | ⏳ |
| 5–6 | Onay paneli ve gönderim | ⏳ |
| 7 | JobSpy keşfi, arama profilleri ve React ilan kutusu | ✅ ilk dikey dilim hazır |
| 8 | Türkiye'ye özel portal arama adaptörleri ve deploy | ⚠️ adaptör canlı doğrulandı, deploy bekliyor |

Faz 3'ün mantığı (budama, şema eşleme, doğrulama, maliyet kapısı) testlerle
korunuyor. Varsayılan akış Brave Search ve yerel Ollama/Qwen kullanır;
`ANTHROPIC_API_KEY` gerekmez. Anthropic sağlayıcısı yalnız isteğe bağlıdır ve
`pip install -e ".[cloud]"` ile ayrıca kurulabilir.

## Geliştirme

Yerel geliştirme ortamı Python 3.12 kullanır. JobSpy'ın sabitlediği NumPy sürümü
nedeniyle Python 3.13 ve üzeri şu anda desteklenmez.

```bash
py -3.12 -m venv .venv
pip install -e ".[dev]"
pytest              # adaptör testleri ağ gerektirmez, kaydedilmiş yanıtlara karşı çalışır
ruff check .
```

Ön yüzü geliştirirken:

```bash
cd web
pnpm install
pnpm dev
pnpm typecheck
pnpm build
```

FastAPI çalışırken `pnpm generate:api`, ön yüz tiplerini canlı OpenAPI
sözleşmesinden yeniden üretir.

Eşleştirme adımı (Faz 4) yerel gömme modeli kullanır ve torch çeker; çekirdek
tarayıcı onsuz çalışsın diye ayrı tutuldu:

```bash
pip install -e ".[embeddings]"
```

## Tarama etiği

- `robots.txt`'ye uyulur, alan adı başına en az 2 saniye beklenir
- `User-Agent` kendini tanıtır ve iletişim adresi içerir (`.env` → `CRAWLER_USER_AGENT`)
- Yalnızca herkese açık ilan verisi ve ATS'lerin kendi public uçları kullanılır
- LinkedIn/Kariyer.net scraping'i, oturum taklidi ve insan onayı olmadan gönderim **yapılmaz**
