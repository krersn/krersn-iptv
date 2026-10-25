# Krersn IPTV — By Krersn Studio

Windows için hızlı, sade bir **Xtream Codes** IPTV oynatıcısı. Python + libmpv ile yazıldı.

> ⚠️ Bu uygulama **hiçbir kanal, film veya içerik barındırmaz/sağlamaz**. Yalnızca bir oynatıcıdır.
> Kendi yasal IPTV aboneliğinizin sunucu adresi, kullanıcı adı ve parolasıyla kullanılır.

## Özellikler

- Canlı TV, film ve dizi kategorileri; binlerce içerikte bile akıcı afişli ızgara
- libmpv tabanlı oynatıcı: donanım hızlandırma, ses/altyazı parçası seçimi, gecikme ayarı
- Film ve dizilerde **kaldığı yerden devam** (1 dk'dan uzun izlenen içerikler)
- İnternet koptuğunda otomatik yeniden bağlanma; internet gelince kendiliğinden devam
- Sağlayıcı bağlantı sınırı doluysa (401/403/409/509) uyarı verip aralıklı yeniden dener
- Yayın açılmazsa biçim (TS/HLS) ya da uzantı alternatiflerini sırayla dener
- Bağlantı zayıfsa kaliteyi otomatik düşürme
- Favoriler, önbellek, klavye kısayolları
- Sorun kaydı: `%USERPROFILE%\.iptv_panel\iptv_gunluk.txt` (kullanıcı adı/parola gizlenir)

## İndirme

1. [Releases](../../releases/latest) sayfasından `KrersnIPTV-Windows-x64-….zip` dosyasını indirin.
2. Zip'i bir klasöre çıkarın (klasörün tamamı gerekir, exe tek başına çalışmaz).
3. `By Krersn Studio.exe` dosyasını açın.

İlk açılışta Windows SmartScreen "tanınmayan uygulama" uyarısı verebilir:
**Ek bilgi → Yine de çalıştır**. (Uygulama kod imzalı değildir.)

Gereksinim: Windows 10/11, 64-bit.

## Kısayollar

| Tuş | İşlev |
|---|---|
| Boşluk / K | Oynat – duraklat |
| ← → | 10 sn geri / ileri |
| Shift + ← → | 1 dk geri / ileri |
| J / L | 5 sn geri / ileri |
| ↑ ↓ | Ses |
| M | Sessiz |
| S | Altyazı aç/kapat |
| A | Ses parçası değiştir |
| Z / X | Altyazı gecikmesi − / + |
| Ctrl + ← → | Ses gecikmesi − / + |
| V | Görüntü ayarları |
| F / F11 | Tam ekran |
| Esc | Tam ekrandan çık |
| F1 | Kısayol listesi |

## Kaynaktan çalıştırma / derleme

```powershell
pip install -r requirements.txt pyinstaller
# libmpv-2.dll dosyasını proje köküne koyun:
# https://github.com/shinchiro/mpv-winbuild-cmake/releases  (mpv-dev-x86_64-*.7z)
python iptv.py                                        # kaynaktan çalıştır
powershell -ExecutionPolicy Bypass -File derle.ps1    # EXE derle -> dist\KrersnStudio\
```

Ayarlar ve giriş bilgileri kullanıcının kendi bilgisayarında `%USERPROFILE%\.iptv_panel\` klasöründe tutulur; hiçbir yere gönderilmez.

Yeni sürüm etiketi (`v*`) gönderildiğinde GitHub Actions EXE'yi Windows'ta derleyip Releases'a ekler.

## Lisans

GPL-3.0 — ayrıntılar için `LICENSE`. Paketlenen EXE, GPL lisanslı [mpv/libmpv](https://mpv.io) içerir.

---

**English:** Lightweight Xtream Codes IPTV player for Windows (Python + libmpv). It ships **no content**; use it with your own legal IPTV subscription. Download the zip from Releases, extract, run `By Krersn Studio.exe`.

© Krersn Studio — [krersnstudio.com](https://krersnstudio.com)
