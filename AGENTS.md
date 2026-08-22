# Jobradar Engineering Rules

## Amaç

- Jobradar'ı küçük ve anlaşılır bir modüler monolit olarak geliştir.
- SOLID ve Clean Architecture ilkelerini değişiklik etkisini azaltmak, dış bağımlılıkları sınırlamak ve test edilebilirliği artırmak için kullan.
- Katman, interface, generic veya ortak klasör sayısını kalite ölçüsü olarak görme. En küçük yeterli tasarımı seç.

## Mimari sınırlar

- Yeni işleri özellik odaklı modüllerde tut: `discovery`, `jobs`, `matching`, `applications` gibi.
- HTTP/UI teslim katmanı iş kuralı içermez; kullanım senaryosunu servis veya açıkça adlandırılmış fonksiyon üzerinden çağırır.
- JobSpy, ATS, web araması, LLM, e-posta ve dosya üretimi gibi dış sistemleri adaptör sınırının arkasında tut.
- `Protocol`/interface yalnız birden fazla gerçek implementasyon, değiştirilebilir dış sistem veya gerekli test seam'i varsa ekle.
- Dependency injection container kurma; constructor/fonksiyon parametresiyle açık bağımlılık aktarımını tercih et.
- Genel `BaseService`, `BaseManager`, `GenericRepository` ve soyut Unit of Work oluşturma. Karmaşık sorgu veya aggregate sınırı oluşursa somut repository kullan.
- Mevcut modülleri sırf katman şemasına uydurmak için topluca taşıma. Yeni özellik çevresinde küçük, davranışı koruyan refactor yap.

## Ortak kod ve generic kullanımı

- Önce somut ve okunur çözümü yaz. İkinci gerçek tekrar ortaya çıktığında ortaklaştırmayı değerlendir.
- Yalnız aynı kavramı temsil eden ve aynı nedenle değişecek kodu paylaş.
- Generic bir yapı ancak en az iki gerçek tipte aynı algoritmayı uyguluyor, type safety sağlıyor ve çağrı yerlerini sadeleştiriyorsa kullan.
- `Any`, reflection, string tabanlı dispatch, çok sayıda callback veya davranış bayrağı gerektiren generic yerine somut kodu tercih et.
- Ortaklaştırma sonrasında kod daha zor okunuyorsa tekrar somutlaştır.

## Backend

- İş akışlarını küçük, niyet belirten servis/fonksiyonlarda tut; sadece satır sayısını azaltmak için bölme.
- API şeması, kalıcılık modeli ve domain davranışı gerçekten farklılaştığında ayrı modeller kullan; her tablo için törensel DTO katmanları üretme.
- Kaynaklardan gelen ilanları ortak ve tipli bir sözleşmeye normalize et. Kaynağa özel alanları iş akışına sızdırma.
- Hataları sınırda bağlamlı domain/application hatalarına dönüştür; geniş `except` yalnız bir kaynağın bütün taramayı düşürmemesi gibi bilinçli izolasyon noktalarında kullan.
- Ağ, zaman ve model çağrılarını testlerde taklit edilebilir sınırlar arkasında tut.

## Frontend

- React kodunu özellik odaklı düzenle; `App` yalnız composition glue olsun.
- Tasarım sistemi temellerini (`Button`, `Dialog`, `Table`, form kontrolleri, durum göstergeleri) ortaklaştır; iş alanına özgü component'leri ilgili feature içinde tut.
- Bir component'i yalnız görsel benzerlik nedeniyle `shared` klasörüne taşıma. En az iki gerçek kullanım ve kararlı bir API bekle.
- Büyük boolean-prop component'leri yerine küçük component composition ve açık variant'lar kullan.
- `utils.ts`, `helpers.ts`, `common.ts` gibi sınırsız toplama dosyaları oluşturma; dosyaları yaptıkları işe göre adlandır.
- FastAPI OpenAPI sözleşmesini frontend API tiplerinin kaynağı yap; Python ve TypeScript DTO'larını elle paralel geliştirmemeye çalış.
- Erişilebilirlik, responsive davranış, loading/empty/error durumları ve gerçek kullanıcı etkileşimleri teslim kapsamındadır.

## Değişiklik akışı

- Özelliği küçük bir dikey dilim olarak tamamla: sözleşme/veri -> kullanım senaryosu -> dış adaptör -> API -> UI -> test.
- İlgisiz refactorları aynı değişikliğe katma.
- Yeni production bağımlılığını gerekçelendir; standart kütüphane veya mevcut bağımlılık yeterliyse yenisini ekleme.
- Mimari karar verirken `$jobradar-architecture` skill'ini kullan.

## Doğrulama

- Python değişikliklerinde en az ilgili testleri ve `ruff check .` çalıştır; mümkünse tam `pytest` çalıştır.
- Frontend değişikliklerinde typecheck/lint/test/build komutlarını ve anlamlı kullanıcı akışını gerçek tarayıcıda doğrula.
- Testi geçmek için ürün davranışını zayıflatma. Ortam kaynaklı test hatasını ürün hatasından ayır ve açıkça raporla.
- Teslimde yapılan değişikliği, seçilen en küçük mimariyi ve doğrulama sonuçlarını kısa biçimde belirt.
