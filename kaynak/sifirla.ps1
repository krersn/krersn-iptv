<#
  By Krersn Studio - onbellek temizleme / sifirlama
  Kullanim:  powershell -ExecutionPolicy Bypass -File sifirla.ps1

  Varsayilan: sadece listeler ve afisler silinir.
  Giris bilgileri ve favoriler icin ayrica onay sorulur.
#>
$ErrorActionPreference = "Stop"

function Yaz($m, $r = "Gray") { Write-Host $m -ForegroundColor $r }

# Uygulamanin veri klasoru: once ev klasoru, sonra AppData, sonra Temp
$adaylar = @(
    (Join-Path $env:USERPROFILE ".iptv_panel"),
    (Join-Path $env:APPDATA "KrersnIPTV"),
    (Join-Path $env:LOCALAPPDATA "KrersnIPTV"),
    (Join-Path $env:TEMP "KrersnIPTV")
)
$klasorler = $adaylar | Where-Object { Test-Path $_ }

if ($klasorler.Count -eq 0) {
    Yaz "Veri klasoru bulunamadi - silinecek bir sey yok." "Yellow"
    Yaz ("Bakilan yerler: " + ($adaylar -join ", "))
    exit 0
}

Yaz "1) Calisan uygulama kapatiliyor..." "Cyan"
$bulundu = $false
foreach ($ad in @("By Krersn Studio", "KrersnStudio", "IPTVPanel")) {
    foreach ($s in (Get-Process -Name $ad -ErrorAction SilentlyContinue)) {
        $bulundu = $true
        Yaz ("   kapatiliyor: {0} (PID {1})" -f $s.ProcessName, $s.Id) "Yellow"
        try { Stop-Process -Id $s.Id -Force -ErrorAction Stop } catch { }
    }
}
if (-not $bulundu) { Yaz "   calisan uygulama yok." }
Start-Sleep -Milliseconds 600

$toplam = 0
foreach ($kok in $klasorler) {
    Yaz ("2) Temizleniyor: {0}" -f $kok) "Cyan"
    foreach ($alt in @("cache", "posters")) {
        $yol = Join-Path $kok $alt
        if (-not (Test-Path $yol)) { continue }
        $sayi = (Get-ChildItem $yol -File -ErrorAction SilentlyContinue).Count
        try {
            Remove-Item (Join-Path $yol "*") -Recurse -Force -ErrorAction Stop
            $toplam += $sayi
            Yaz ("   {0}: {1} dosya silindi" -f $alt, $sayi)
        } catch {
            Yaz ("   {0}: silinemedi - {1}" -f $alt, $_.Exception.Message) "Red"
        }
    }
}
Yaz ("   Toplam {0} dosya silindi." -f $toplam) "Green"

Write-Host ""
$cevap = Read-Host "Giris bilgileri ve favoriler de silinsin mi? (e/H)"
if ($cevap -eq "e" -or $cevap -eq "E") {
    foreach ($kok in $klasorler) {
        foreach ($dosya in @("config.json", "favorites.json", "settings.json")) {
            $yol = Join-Path $kok $dosya
            if (Test-Path $yol) {
                try {
                    Remove-Item $yol -Force -ErrorAction Stop
                    Yaz ("   silindi: {0}" -f $yol) "Yellow"
                } catch {
                    Yaz ("   silinemedi: {0}" -f $yol) "Red"
                }
            }
        }
    }
    Yaz "   Uygulama bir sonraki acilista giris soracak." "Yellow"
} else {
    Yaz "   Giris bilgileri ve favoriler korundu."
}

Write-Host ""
Yaz "Bitti. Uygulamayi acip listelerin yeniden yuklenmesini bekleyin." "Green"
