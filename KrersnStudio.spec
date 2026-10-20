# -*- mode: python ; coding: utf-8 -*-
#
# Derleme:
#   cd C:\Users\msi\Desktop\ip
#   Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
#   python -m PyInstaller KrersnStudio.spec --noconfirm
#
# libmpv-2.dll ARTIK OTOMATİK paketleniyor; elle kopyalamaya gerek yok.
# Bu "onedir" bir derleme (COLLECT var), yani --onefile gibi her açılışta
# %TEMP% klasörüne açma maliyeti YOK: dosyalar olduğu yerde kalır.
# Eskiden DLL elle kopyalanıyordu; dist klasörü her silindiğinde kopyalama
# unutulunca "libmpv yüklenemedi" hatası çıkıyordu. Bu yüzden otomatikleşti.

import os

# DLL projenin kökünde aranır; adı farklıysa ilk bulunan kullanılır.
_ADAYLAR = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll", "libmpv-1.dll", "libmpv.dll")
_KOK = os.path.abspath(os.getcwd())

def _mpv_dll():
    for ad in _ADAYLAR:
        yol = os.path.join(_KOK, ad)
        if os.path.isfile(yol):
            # python-mpv yalnızca mpv-2.dll / libmpv-2.dll / mpv-1.dll arar.
            hedef_ad = ad if ad in ("mpv-2.dll", "libmpv-2.dll", "mpv-1.dll") else "libmpv-2.dll"
            return yol, hedef_ad
    return None, None

_dll_yolu, _dll_adi = _mpv_dll()
if _dll_yolu:
    # ('.',) -> exe ile aynı klasöre (dist\KrersnStudio\) konur.
    _binaries = [(_dll_yolu, ".")]
    print(f"[spec] libmpv paketleniyor: {_dll_yolu} -> {_dll_adi}")
else:
    _binaries = []
    print("[spec] UYARI: libmpv DLL bulunamadi! Proje kokune libmpv-2.dll koyun, "
          "yoksa uygulama video oynatamaz.")

a = Analysis(
    ['iptv.py'],
    pathex=[],
    binaries=_binaries,
    datas=[('krersn.ico', '.'), ('krersn.png', '.')],
    hiddenimports=['PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageOps',
                   'PIL.ImageTk', 'PIL._tkinter_finder',
                   'mpv', 'customtkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['vlc'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='By Krersn Studio',
    icon='krersn.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # UPX libmpv'yi bozar; sıkıştırma dışı bırakılıyor.
    upx_exclude=['libmpv-2.dll', 'mpv-2.dll', 'mpv-1.dll', 'libmpv-1.dll'],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['libmpv-2.dll', 'mpv-2.dll', 'mpv-1.dll', 'libmpv-1.dll'],
    name='KrersnStudio',
)
