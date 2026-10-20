<#
  By Krersn Studio - guvenli derleme betigi
  Kullanim:  powershell -ExecutionPolicy Bypass -File derle.ps1

  Neden bu betik: PyInstaller dist klasorunu silerek isine baslar. Uygulama
  (veya arka planda kalmis bir ornegi) calisiyorsa dosyalar kilitli olur ve
  derleme "WinError 5 Erisim engellendi" ile coker. Bu betik once kilidi
  cozer, cozemezse baska bir klasore derleyerek isi yine de tamamlar.
#>

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Proje   = $PSScriptRoot
$DistYol = Join-Path $Proje "dist"
$Hedef   = Join-Path $DistYol "KrersnStudio"

function Yaz($metin, $renk = "Gray") { Write-Host $metin -ForegroundColor $renk }

function Kilitleyen-Surecler($klasor) {
    # 1) Calistigi dosya bu klasorun altinda olan surecler
    $bulunan = @()
    foreach ($s in Get-Process) {
        $yol = $null
        try { $yol = $s.Path } catch { }
        if ($yol -and $yol.StartsWith($klasor, [System.StringComparison]::OrdinalIgnoreCase)) {
            $bulunan += $s
            continue
        }
        # 2) Bu klasordeki bir DLL/PYD dosyasini yuklemis surecler
        try {
            foreach ($m in $s.Modules) {
                if ($m.FileName -and $m.FileName.StartsWith($klasor, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $bulunan += $s
                    break
                }
            }
        } catch { }
    }
    return $bulunan | Sort-Object Id -Unique
}

Yaz "1) Calisan uygulama araniyor..." "Cyan"
$adaylar = @()
foreach ($ad in @("By Krersn Studio", "KrersnStudio", "IPTVPanel")) {
    $adaylar += Get-Process -Name $ad -ErrorAction SilentlyContinue
}
if (Test-Path $DistYol) {
    $adaylar += Kilitleyen-Surecler $DistYol
}
$adaylar = $adaylar | Sort-Object Id -Unique

if ($adaylar.Count -gt 0) {
    foreach ($s in $adaylar) {
        Yaz ("   kapatiliyor: {0} (PID {1})" -f $s.ProcessName, $s.Id) "Yellow"
        try { Stop-Process -Id $s.Id -Force -ErrorAction Stop } catch {
            Yaz ("   kapatilamadi: {0}" -f $_.Exception.Message) "Red"
        }
    }
    Start-Sleep -Milliseconds 1200
} else {
    Yaz "   calisan uygulama yok."
}

Yaz "2) Eski derleme siliniyor..." "Cyan"
$silindi = $true
foreach ($klasor in @("dist", "build")) {
    if (-not (Test-Path $klasor)) { continue }
    $ok = $false
    for ($deneme = 1; $deneme -le 5; $deneme++) {
        try {
            Remove-Item -Recurse -Force $klasor -ErrorAction Stop
            $ok = $true
            Yaz ("   silindi: {0}" -f $klasor)
            break
        } catch {
            Start-Sleep -Milliseconds 700
        }
    }
    if (-not $ok) {
        $silindi = $false
        Yaz ("   '{0}' silinemedi - dosyalar hala kilitli." -f $klasor) "Red"
        $tutan = Kilitleyen-Surecler (Join-Path $Proje $klasor)
        if ($tutan.Count -gt 0) {
            Yaz "   Kilidi tutan surecler:" "Red"
            foreach ($s in $tutan) { Yaz ("     - {0} (PID {1})" -f $s.ProcessName, $s.Id) "Red" }
        } else {
            Yaz "   Kilidi tutan surec bulunamadi (antivirus veya Explorer olabilir)." "Yellow"
        }
    }
}

# Silinemediyse yeni bir cikti klasorune derle; is yine de tamamlansin.
$distArg = @()
$DistKullanilan = $DistYol
if (-not $silindi) {
    $damga = Get-Date -Format "yyyyMMdd-HHmmss"
    $DistKullanilan = Join-Path $Proje ("dist-" + $damga)
    $distArg = @("--distpath", $DistKullanilan)
    Yaz ("   Cozum: bunun yerine '{0}' klasorune derlenecek." -f (Split-Path $DistKullanilan -Leaf)) "Yellow"
    $Hedef = Join-Path $DistKullanilan "KrersnStudio"
}

Yaz "3) Derleniyor..." "Cyan"
$argumanlar = @("-m", "PyInstaller", "KrersnStudio.spec", "--noconfirm") + $distArg
& python @argumanlar
if ($LASTEXITCODE -ne 0) {
    Yaz "Derleme basarisiz oldu." "Red"
    exit 1
}

Yaz "4) Sonuc kontrolu..." "Cyan"
$dll = Join-Path $Hedef "_internal\libmpv-2.dll"
if (Test-Path $dll) {
    $mb = [math]::Round((Get-Item $dll).Length / 1MB, 1)
    Yaz ("   libmpv paketlendi ({0} MB)" -f $mb) "Green"
} else {
    Yaz "   UYARI: libmpv-2.dll pakette YOK - video oynatilamaz!" "Yellow"
    Yaz "   Proje kokune libmpv-2.dll koyup tekrar derleyin." "Yellow"
}

$exe = Join-Path $Hedef "By Krersn Studio.exe"
Write-Host ""
if (Test-Path $exe) {
    Yaz ("Hazir: {0}" -f $exe) "Green"
} else {
    Yaz "EXE bulunamadi, derleme ciktisini kontrol edin." "Red"
    exit 1
}
if (-not $silindi) {
    Write-Host ""
    Yaz "NOT: Eski 'dist' klasoru silinemedi. Bilgisayari yeniden baslattiktan" "Yellow"
    Yaz "     sonra elle silebilirsiniz; yeni derleme yukaridaki klasorde." "Yellow"
}
