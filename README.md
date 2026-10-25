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

1. [Releases](../../releases/latest) sayfasından `KrersnIPTV-Setup-v….exe` dosyasını indirin.
2. Çift tıklayıp kurun. Yönetici izni gerekmez; masaüstüne ve Başlat menüsüne kısayol eklenir.
3. **Krersn IPTV** kısayolundan açın.

Yeni sürümü aynı şekilde kurmanız yeterli; ayarlar, favoriler ve izleme geçmişi korunur.
Kaldırmak için: Windows Ayarlar → Uygulamalar → **Krersn IPTV** → Kaldır.

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

## Kaynak kod

Kaynak kod [`kaynak/`](kaynak/) klasöründedir. Sadece kullanmak istiyorsanız buna ihtiyacınız yok; yukarıdaki kurulum dosyası yeterli.

```powershell
cd kaynak
pip install -r requirements.txt pyinstaller
# libmpv-2.dll dosyasını kaynak klasörüne koyun:
# https://github.com/shinchiro/mpv-winbuild-cmake/releases  (mpv-dev-x86_64-*.7z)
python iptv.py                                        # kaynaktan çalıştır
powershell -ExecutionPolicy Bypass -File derle.ps1    # EXE + kurulum -> dist\KrersnStudio\, kurulum\
# Kurulum dosyası için bir kez: winget install JRSoftware.InnoSetup
```

Ayarlar ve giriş bilgileri kullanıcının kendi bilgisayarında `%USERPROFILE%\.iptv_panel\` klasöründe tutulur; hiçbir yere gönderilmez.

## Lisans

GPL-3.0 — ayrıntılar için [`LICENSE`](LICENSE). Kurulum dosyası, GPL lisanslı [mpv/libmpv](https://mpv.io) içerir.

---

**English:** Lightweight Xtream Codes IPTV player for Windows (Python + libmpv). It ships **no content**; use it with your own legal IPTV subscription. Download `KrersnIPTV-Setup-v….exe` from Releases and install it (no admin rights needed). Source code is in [`kaynak/`](kaynak/).

© Krersn Studio — [krersnstudio.com](https://krersnstudio.com)
