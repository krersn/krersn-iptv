# coding: utf-8
"""
By Krersn Studio — hızlı açılış, tembel yükleme, akıcı arayüz.
Grid düzenli kapak görselleri ile içerik tarama.
"""
import hashlib
import io
import json
import os
import platform
import queue
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox
from urllib.parse import urlsplit
import customtkinter as ctk
import requests
from PIL import Image, ImageDraw, ImageOps

# ============================== VERİ KLASÖRÜ ==============================
def havuz_kapat(havuz):
    """İş havuzunu bekleyen işleri iptal ederek kapatır.

    ThreadPoolExecutor'ın iş parçacıkları daemon DEĞİL ve Python çıkarken
    hepsini join ediyor. cancel_futures verilmezse kuyruktaki yüzlerce afiş
    indirmesi sonuna kadar çalışır ve uygulama kapandıktan sonra süreç
    dakikalarca ayakta kalır (dosyaları kilitler).
    """
    if havuz is None:
        return
    try:
        havuz.shutdown(wait=False, cancel_futures=True)
    except TypeError:                 # Python < 3.9
        try:
            havuz.shutdown(wait=False)
        except Exception:
            pass
    except Exception:
        pass

def _klasor_yazilabilir(klasor):
    try:
        os.makedirs(klasor, exist_ok=True)
        deneme = os.path.join(klasor, ".yazma_denemesi")
        with open(deneme, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(deneme)
        return True
    except Exception:
        return False

def _veri_klasoru():
    """Ayarların yazılacağı klasör.

    Uygulamanın bulunduğu klasör salt okunur olabilir (Program Files, ağ
    sürücüsü, USB). Bu yüzden hiçbir ayar dosyası çalışma klasörüne
    yazılmaz; ev klasörü, o da olmazsa geçici klasör kullanılır.
    """
    adaylar = [os.path.join(os.path.expanduser("~"), ".iptv_panel")]
    if platform.system() == "Windows":
        for cevre in ("APPDATA", "LOCALAPPDATA"):
            kok = os.environ.get(cevre)
            if kok:
                adaylar.append(os.path.join(kok, "KrersnIPTV"))
    adaylar.append(os.path.join(tempfile.gettempdir(), "KrersnIPTV"))
    for klasor in adaylar:
        if _klasor_yazilabilir(klasor):
            return klasor
    return adaylar[0]

APP_DIR = _veri_klasoru()

# ============================== libmpv YÜKLEME ==============================
# python-mpv yalnızca %PATH% içinde şu adları arar: mpv-2.dll, libmpv-2.dll,
# mpv-1.dll. Bu yüzden DLL'i önce diskte bulup klasörünü PATH'e ekliyoruz.
MPV_DLL_NAMES = ("mpv-2.dll", "libmpv-2.dll", "mpv-1.dll",
                 "libmpv-1.dll", "libmpv.dll", "mpv.dll")
MPV_PYTHON_NAMES = ("mpv-2.dll", "libmpv-2.dll", "mpv-1.dll")
_MPV_ALT_KLASORLER = ("", "_internal", "mpv", "lib", "bin", "dll", "libmpv")
_MPV_ATLA = {"_tcl_data", "_tk_data", "tcl8", "PIL", "certifi", "setuptools",
             "customtkinter", "__pycache__", "build", "cache", "posters",
             "charset_normalizer", "numpy", "share", "locale"}

def _kok_dizin_mi(yol):
    """Sürücü kökü veya onun bir altı mı? (C:\\, C:\\Users, /, /home)

    os.path.splitdrive kullanılmıyor: Windows yolları başka bir işletim
    sisteminde çözümlenmediği için test edilemez hale geliyordu.
    """
    metin = str(yol or "").replace("\\", "/")
    surucu_onekli = len(metin) >= 2 and metin[1] == ":" and metin[0].isalpha()
    if not (metin.startswith("/") or surucu_onekli):
        return False                       # göreli yol: karar verme
    kalan = metin[2:] if surucu_onekli else metin
    parcalar = [p for p in kalan.split("/") if p and p != "."]
    return len(parcalar) <= 1

def _mpv_kokler(derin=False):
    """DLL'in aranacağı kök klasörler (exe/betik konumu ve üst klasörleri).

    derin=True iken yalnızca uygulamanın kendi konumu döner: çalışma klasörü
    (cwd) rastgele bir yer olabilir, orada derin arama hem yavaştır hem de
    alakasız bir DLL bulabilir.
    """
    kokler = []
    def ekle(yol):
        if not yol:
            return
        yol = os.path.abspath(yol)
        if yol not in kokler:
            kokler.append(yol)
    if getattr(sys, "frozen", False):
        ekle(getattr(sys, "_MEIPASS", None))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        ekle(exe_dir)
        if derin:
            return kokler          # derin tarama sadece uygulamanın kendi klasöründe
        # dist\KrersnStudio -> dist -> proje kökü. DLL derleme sonrası proje
        # kökünde unutulmuş olabiliyor, bu yüzden 3 üst klasör de taranıyor.
        # Daha yukarı çıkılmıyor: C:\Users veya C:\ taramak hem yavaş hem
        # de alakasız bir DLL bulma riski taşır.
        ust = exe_dir
        for _ in range(3):
            yeni = os.path.dirname(ust)
            if not yeni or yeni == ust or _kok_dizin_mi(yeni):
                break
            ust = yeni
            ekle(ust)
    else:
        ekle(os.path.dirname(os.path.abspath(__file__)))
    if not derin:
        ekle(os.getcwd())
    return kokler

def _mpv_arama_klasorleri():
    klasorler = []
    def ekle(yol):
        if yol and yol not in klasorler and os.path.isdir(yol):
            klasorler.append(yol)
    for kok in _mpv_kokler():
        for alt in _MPV_ALT_KLASORLER:
            ekle(os.path.join(kok, alt) if alt else kok)
    return klasorler

def _mpv_derin_ara(kok, derinlik=2, sinir=400):
    """Son çare: kök altında sınırlı derinlikte DLL araması."""
    bulunan = []
    sayac = 0
    try:
        temel = kok.rstrip(os.sep).count(os.sep)
        for klasor, alt_klasorler, dosyalar in os.walk(kok):
            sayac += 1
            if sayac > sinir:
                break
            if klasor.rstrip(os.sep).count(os.sep) - temel >= derinlik:
                alt_klasorler[:] = []
            else:
                alt_klasorler[:] = [d for d in alt_klasorler
                                    if d not in _MPV_ATLA and not d.startswith(".")]
            kucuk = {d.lower(): d for d in dosyalar}
            for ad in MPV_DLL_NAMES:
                if ad in kucuk:
                    bulunan.append(os.path.join(klasor, kucuk[ad]))
                    return bulunan
    except Exception:
        pass
    return bulunan

def _mpv_dll_bul():
    for klasor in MPV_SEARCH_DIRS:
        try:
            kucuk = {d.lower(): d for d in os.listdir(klasor)}
        except Exception:
            continue
        for ad in MPV_DLL_NAMES:
            if ad in kucuk:
                return os.path.join(klasor, kucuk[ad])
    for kok in _mpv_kokler(derin=True):
        bulunan = _mpv_derin_ara(kok)
        if bulunan:
            return bulunan[0]
    return None

def _mpv_yolu_hazirla(dll_yolu):
    """DLL klasörünü PATH'e ekler, gerekirse tanınan bir adla kopyasını yapar.

    Dönüş: (kullanılacak_yol, durum_metni)
    """
    klasor = os.path.dirname(dll_yolu)
    ad = os.path.basename(dll_yolu)
    os.environ["PATH"] = klasor + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(klasor)
    except Exception:
        pass
    if ad.lower() in MPV_PYTHON_NAMES:
        return dll_yolu, ""
    # python-mpv bu adı aramıyor: tanınan adla bir kopya/bağlantı oluştur.
    hedef_klasor = os.path.join(APP_DIR, "mpv")
    hedef = os.path.join(hedef_klasor, "mpv-2.dll")
    try:
        os.makedirs(hedef_klasor, exist_ok=True)
        if not (os.path.isfile(hedef)
                and os.path.getsize(hedef) == os.path.getsize(dll_yolu)):
            try:
                if os.path.exists(hedef):
                    os.remove(hedef)
                os.link(dll_yolu, hedef)          # aynı diskteyse kopya maliyeti yok
            except Exception:
                import shutil
                shutil.copy2(dll_yolu, hedef)
        os.environ["PATH"] = hedef_klasor + os.pathsep + os.environ["PATH"]
        try:
            os.add_dll_directory(hedef_klasor)
        except Exception:
            pass
        return hedef, f"{ad} dosyası mpv-2.dll adıyla kopyalandı."
    except Exception as e:
        return dll_yolu, f"{ad} tanınan bir ad değil ve kopyalanamadı: {e}"

def _mpv_on_yukle(dll_yolu):
    """DLL'i doğrudan yükleyip sorunu erkenden ve anlaşılır biçimde yakalar."""
    if platform.system() != "Windows":
        return ""
    try:
        import ctypes
        ctypes.WinDLL(dll_yolu)
        return ""
    except OSError as e:
        kod = getattr(e, "winerror", None)
        if kod == 193:
            return ("DLL bulundu ama mimarisi uyumsuz (WinError 193). "
                    "64-bit Python ile 64-bit libmpv, 32-bit ile 32-bit "
                    "kullanılmalı. Şu anki Python: "
                    f"{platform.architecture()[0]}.")
        if kod == 126:
            return ("DLL bulundu ama bağımlılıkları eksik (WinError 126). "
                    "Microsoft Visual C++ Redistributable (x64) kurun.")
        return f"DLL yüklenemedi: {e}"
    except Exception as e:
        return f"DLL yüklenemedi: {e}"

MPV_SEARCH_DIRS = _mpv_arama_klasorleri()
MPV_DLL_PATH = None
MPV_DURUM = ""
if platform.system() == "Windows":
    MPV_DLL_PATH = _mpv_dll_bul()
    if MPV_DLL_PATH:
        MPV_DLL_PATH, _not = _mpv_yolu_hazirla(MPV_DLL_PATH)
        _yukleme_hatasi = _mpv_on_yukle(MPV_DLL_PATH)
        MPV_DURUM = _yukleme_hatasi or _not
    else:
        MPV_DURUM = "libmpv-2.dll hiçbir klasörde bulunamadı."

try:
    import mpv
except Exception as _err:
    mpv = None
    MPV_IMPORT_ERROR = _err
else:
    MPV_IMPORT_ERROR = None

def mpv_hedef_klasor():
    """DLL'in konması gereken klasör (exe'nin yanı)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

# ============================== KİMLİK / SİMGE ==============================
APP_NAME = "By Krersn Studio"
APP_ID = "KrersnStudio.IPTV"

def varlik_yolu(ad):
    for klasor in MPV_SEARCH_DIRS:
        yol = os.path.join(klasor, ad)
        if os.path.isfile(yol):
            return yol
    return None

APP_ICON_ICO = varlik_yolu("krersn.ico")
APP_ICON_PNG = varlik_yolu("krersn.png")

def simge_uygula(pencere):
    def _ayarla():
        try:
            if APP_ICON_ICO and platform.system() == "Windows":
                pencere.iconbitmap(APP_ICON_ICO)
            elif APP_ICON_PNG:
                if not hasattr(pencere, "_simge_ref"):
                    pencere._simge_ref = tk.PhotoImage(file=APP_ICON_PNG)
                pencere.iconphoto(False, pencere._simge_ref)
        except Exception:
            pass
    _ayarla()
    try:
        pencere.after(300, _ayarla)
    except Exception:
        pass

def gorev_cubugu_kimligi():
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

# ============================== TASARIM ==============================
C = {
    "bg": "#0F1115",
    "panel": "#161920",
    "panel2": "#1C2029",
    "line": "#252A34",
    "hover": "#222732",
    "sel": "#2A3140",
    "text": "#E8EAED",
    "muted": "#8A929F",
    "accent": "#E0B04C",
    "accent_dk": "#B98D33",
    "live": "#E5484D",
}

_FONT_CACHE = {}

def ui_font(size=12, weight="normal"):
    key = (size, weight)
    font = _FONT_CACHE.get(key)
    if font is None:
        system = platform.system()
        family = "Segoe UI" if system == "Windows" else ("SF Pro Text" if system == "Darwin" else "DejaVu Sans")
        font = ctk.CTkFont(family=family, size=size, weight=weight)
        _FONT_CACHE[key] = font
    return font

def mono_font(size=12, weight="normal"):
    key = ("mono", size, weight)
    font = _FONT_CACHE.get(key)
    if font is None:
        system = platform.system()
        family = ("Consolas" if system == "Windows"
                  else ("Menlo" if system == "Darwin" else "DejaVu Sans Mono"))
        font = ctk.CTkFont(family=family, size=size, weight=weight)
        _FONT_CACHE[key] = font
    return font

def canvas_font(size=12, bold=False):
    system = platform.system()
    family = "Segoe UI" if system == "Windows" else ("Helvetica Neue" if system == "Darwin" else "DejaVu Sans")
    return (family, size, "bold" if bold else "normal")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# ============================== DOSYALAR ==============================
CACHE_DIR = os.path.join(APP_DIR, "cache")
POSTER_DIR = os.path.join(APP_DIR, "posters")
# Göreli yol KULLANILMIYOR: çalışma klasörü yazılabilir olmayabilir.
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
FAV_FILE = os.path.join(APP_DIR, "favorites.json")
# Eski sürümlerin çalışma klasörüne bıraktığı dosyalar (sadece okunur, taşınır)
LEGACY_CONFIG = os.path.abspath("config.json")
LEGACY_FAV = os.path.abspath("favorites.json")
CACHE_TTL_CATEGORIES = 24 * 3600
CACHE_TTL_STREAMS = 6 * 3600
DETAIL_TTL = 7 * 24 * 3600   # film/dizi künyesi nadiren değişir
EPG_TTL = 10 * 60            # canlı yayın akışı sık değişir

for _d in (APP_DIR, CACHE_DIR, POSTER_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception as e:
        print(f"Klasör oluşturulamadı ({_d}): {e}")

def _json_oku(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Okunamadı ({path}): {e}")
        return None

def _json_yaz(path, veri, indent=2, ensure_ascii=True):
    """Önce geçici dosyaya yazıp yerine koyar: yarım kalan yazma dosyayı bozmaz.

    Dönüş: (başarılı_mı, hata_metni)
    """
    gecici = path + ".tmp"
    try:
        klasor = os.path.dirname(path)
        if klasor:
            os.makedirs(klasor, exist_ok=True)
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(veri, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())
        os.replace(gecici, path)
        return True, ""
    except Exception as e:
        try:
            if os.path.exists(gecici):
                os.remove(gecici)
        except Exception:
            pass
        mesaj = f"{e.__class__.__name__}: {e}"
        print(f"Yazılamadı ({path}): {mesaj}")
        return False, mesaj

def load_config():
    if os.path.exists(CONFIG_FILE):
        veri = _json_oku(CONFIG_FILE)
        if isinstance(veri, dict):
            return veri
    # Eski sürüm çalışma klasörüne yazmışsa oradan al ve kalıcı yere taşı
    if os.path.exists(LEGACY_CONFIG):
        veri = _json_oku(LEGACY_CONFIG)
        if isinstance(veri, dict):
            _json_yaz(CONFIG_FILE, veri)
            return veri
    return {}

def save_config(url, username, password, auto_login=True):
    ok, hata = _json_yaz(CONFIG_FILE,
                         {"url": url, "username": username, "password": password,
                          "auto_login": bool(auto_login)})
    return ok, hata

def set_auto_login(flag):
    cfg = load_config()
    if not cfg:
        return False, "kayıtlı oturum yok"
    cfg["auto_login"] = bool(flag)
    return _json_yaz(CONFIG_FILE, cfg)

def has_saved_session(cfg):
    return bool(cfg.get("url") and cfg.get("username") and cfg.get("password"))

def clear_config():
    for path in (CONFIG_FILE, LEGACY_CONFIG):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Silinemedi ({path}): {e}")

def load_favorites():
    for path in (FAV_FILE, LEGACY_FAV):
        if os.path.exists(path):
            veri = _json_oku(path)
            if isinstance(veri, dict):
                for key in ("live", "vod", "series"):
                    veri.setdefault(key, [])
                if path != FAV_FILE:
                    _json_yaz(FAV_FILE, veri, indent=None, ensure_ascii=False)
                return veri
    return {"live": [], "vod": [], "series": []}

def save_favorites(favorites):
    return _json_yaz(FAV_FILE, favorites, indent=None, ensure_ascii=False)

def _digest(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()

def _hex_rgb(hex_kod):
    hex_kod = hex_kod.lstrip("#")
    return tuple(int(hex_kod[i:i + 2], 16) for i in (0, 2, 4))

def _daire_maskesi(boyut):
    """Kenarı pürüzsüz daire maskesi (4 kat büyük çizilip küçültülür)."""
    kat = 4
    maske = Image.new("L", (boyut * kat, boyut * kat), 0)
    ImageDraw.Draw(maske).ellipse((0, 0, boyut * kat - 1, boyut * kat - 1), fill=255)
    return maske.resize((boyut, boyut), Image.LANCZOS)

def bos_daire(boyut, arka_plan):
    """Logo gelene kadar gösterilen boş daire."""
    if not isinstance(arka_plan, tuple):
        arka_plan = _hex_rgb(arka_plan)
    tuval = Image.new("RGBA", (boyut, boyut), arka_plan + (255,))
    tuval.putalpha(_daire_maskesi(boyut))
    return tuval

def dairesel_logo(img, boyut, arka_plan):
    """Kanal logosunu kare tuvale ortalayıp daire maskesiyle kırpar.

    Afişlerden farklı olarak logo KIRPILMAZ, oranı korunarak içeri sığdırılır;
    böylece geniş kanal logolarının kenarları kesilmez.

    Yuvarlaklık görüntünün alfa kanalına işleniyor; CTkLabel'ın corner_radius
    seçeneği kullanılmıyor, çünkü büyük yarıçapta görüntüyü hiç çizmiyor.
    """
    if not isinstance(arka_plan, tuple):
        arka_plan = _hex_rgb(arka_plan)
    tuval = Image.new("RGBA", (boyut, boyut), arka_plan + (255,))
    logo = img.convert("RGBA")
    # Dikdörtgen daireye köşegeninden sığar: yarı köşegen ≤ yarıçap.
    # Böylece kare logonun köşeleri kesilmez, geniş logo da gereksiz küçülmez.
    yari_kosegen = max(1.0, (logo.width ** 2 + logo.height ** 2) ** 0.5 / 2.0)
    hedef = (boyut / 2.0) * 0.86          # kenarda nefes payı
    # Büyük logo küçültülür; küçük logo daire içinde kaybolmasın diye
    # en fazla 2 kat büyütülür (fazlası bulanıklaşmaya yol açar).
    olcek = min(hedef / yari_kosegen, 2.0)
    if olcek != 1.0:
        logo = logo.resize((max(1, int(logo.width * olcek)),
                            max(1, int(logo.height * olcek))), Image.LANCZOS)
    tuval.paste(logo, ((boyut - logo.width) // 2, (boyut - logo.height) // 2), logo)
    tuval.putalpha(_daire_maskesi(boyut))
    return tuval

def cache_read_raw(key, ttl):
    path = os.path.join(CACHE_DIR, _digest(key) + ".json")
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl:
            with open(path, "rb") as f:
                return f.read()
    except Exception:
        pass
    return None

def cache_write_raw(key, raw):
    path = os.path.join(CACHE_DIR, _digest(key) + ".json")
    try:
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, path)
    except Exception:
        pass

def cache_drop(key):
    """Tek bir önbellek girdisini siler (bozuk/işe yaramaz yanıtlar için)."""
    for ek in (".json", ".json.tmp"):
        try:
            yol = os.path.join(CACHE_DIR, _digest(key) + ek)
            if os.path.exists(yol):
                os.remove(yol)
        except Exception:
            pass

def cache_clear_all(afisler=False):
    klasorler = [CACHE_DIR] + ([POSTER_DIR] if afisler else [])
    silinen = 0
    for klasor in klasorler:
        try:
            for name in os.listdir(klasor):
                try:
                    os.remove(os.path.join(klasor, name))
                    silinen += 1
                except Exception:
                    pass
        except Exception:
            pass
    return silinen

def bring_to_front(win, tries=5, _first=True):
    try:
        if not win.winfo_exists():
            return
        win.deiconify()
        if _first:
            win.attributes("-topmost", True)
        win.lift()
        win.focus_force()
    except Exception:
        return
    if tries > 1:
        win.after(120, lambda: bring_to_front(win, tries - 1, False))
    else:
        try:
            win.attributes("-topmost", False)
            win.lift()
        except Exception:
            pass

def fmt_time(ms):
    if not ms or ms < 0:
        ms = 0
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

# ============================== AYARLAR / KALİTE ==============================
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
QUALITIES = [("auto", "Otomatik"), ("high", "Yüksek"), ("medium", "Orta"), ("low", "Düşük")]
QUALITY_NAMES = dict(QUALITIES)
QUALITY_CODES = {name: code for code, name in QUALITIES}
QUALITY_ORDER = ["high", "medium", "low"]

DEFAULT_SETTINGS = {
    "quality": "auto",
    "live_protocol": "auto",
    "buffer_ms": 2000,
    "hw_accel": "any",
    "auto_downgrade": True,
    "posters": True,
    # Yayına açılması için tanınan süre (sn). Bu süre dolmadan alternatif
    # biçime geçilmez; hızlı ardışık denemeler sağlayıcıda "çok fazla
    # bağlantı" hatasına ve geçici engellemeye yol açabiliyor.
    "open_timeout": 10,
}

PRESETS = {
    "Zayıf internet": {"quality": "low", "live_protocol": "auto", "buffer_ms": 8000,
                       "hw_accel": "any", "auto_downgrade": True, "posters": False,
                       "open_timeout": 20},
    "Dengeli": dict(DEFAULT_SETTINGS),
    "Düşük gecikme": {"quality": "high", "live_protocol": "ts", "buffer_ms": 800,
                      "hw_accel": "any", "auto_downgrade": False, "posters": True,
                      "open_timeout": 8},
}

CACHE_HOURS = 6

def load_settings():
    data = dict(DEFAULT_SETTINGS)
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key in DEFAULT_SETTINGS:
                if key in saved:
                    data[key] = saved[key]
            if "buffer_ms" not in saved and "live_caching" in saved:
                try:
                    data["buffer_ms"] = int(saved["live_caching"])
                except Exception:
                    pass
    except Exception as e:
        print(f"Ayarlar okunamadı: {e}")
    return data

def save_settings(settings):
    clean = {key: settings.get(key, DEFAULT_SETTINGS[key]) for key in DEFAULT_SETTINGS}
    return _json_yaz(SETTINGS_FILE, clean, ensure_ascii=False)

def build_url(source, quality, settings):
    base = source["base"].rstrip("/")
    user, pwd, sid = source["user"], source["pass"], source["id"]
    kind = source.get("kind", "vod")
    if kind == "live":
        protocol = settings.get("live_protocol", "auto")
        use_hls = protocol == "hls" or (protocol == "auto" and quality in ("medium", "low"))
        return f"{base}/live/{user}/{pwd}/{sid}." + ("m3u8" if use_hls else "ts")
    folder = "movie" if kind == "vod" else "series"
    ext = source.get("ext") or ("mp4" if kind == "vod" else "mkv")
    return f"{base}/{folder}/{user}/{pwd}/{sid}.{ext}"

def build_mpv_options(settings, kind, quality, extra_buffer=0):
    is_live = kind == "live"
    buffer_ms = max(300, int(settings.get("buffer_ms", 2000)) + extra_buffer)
    secs = round(buffer_ms / 1000.0, 2)
    profile = "low-latency" if (is_live and buffer_ms <= 1500) else None
    opts = {
        "network-timeout": 10 if is_live else 15,
        "user-agent": "IPTVPanel/3.0",
        "stream-lavf-o": ("reconnect=1,reconnect_streamed=1,"
                          "reconnect_on_network_error=1,reconnect_delay_max=5"),
        "cache": "yes",
        "cache-secs": secs if is_live else max(10.0, secs + 5),
        "demuxer-readahead-secs": secs if is_live else max(10.0, secs + 5),
        "demuxer-max-bytes": "32MiB" if is_live else "96MiB",
        "demuxer-max-back-bytes": "16MiB" if is_live else "48MiB",
        "cache-pause": "yes",
        "cache-pause-wait": max(0.3, secs / 2),
        "cache-pause-initial": "yes" if buffer_ms >= 1500 else "no",
        "hwdec": "no" if settings.get("hw_accel") == "none" else "auto-safe",
        "framedrop": "vo",
        "keep-open": "no",
    }
    if is_live:
        opts.update({
            "video-sync": "audio",
            "demuxer-lavf-probe-info": "nostreams",
            "demuxer-lavf-analyzeduration": 0.5,
            "hr-seek": "no",
        })
    else:
        opts.update({
            "hr-seek": "yes",
            "hr-seek-framedrop": "yes",
        })
    if quality == "low":
        opts["hls-bitrate"] = "min"
    elif quality in ("high", "medium"):
        opts["hls-bitrate"] = "max"
    if quality == "low":
        opts.update({
            "vd-lavc-skiploopfilter": "all",
            "vd-lavc-skipframe": "nonref",
            "vd-lavc-fast": "yes",
            "scale": "bilinear",
            "dscale": "bilinear",
            "cscale": "bilinear",
            "dither": "no",
            "deband": "no",
        })
    elif quality == "medium":
        opts.update({
            "vd-lavc-skiploopfilter": "nonref",
            "vd-lavc-fast": "yes",
            "deband": "no",
        })
    else:
        opts.update({
            "vd-lavc-skiploopfilter": "default",
            "vd-lavc-skipframe": "none",
        })
    return opts, profile

# ============================== SANAL LİSTE ==============================
class VirtualList(ctk.CTkFrame):
    def __init__(self, master, row_height=32, font_size=12, empty_text="Liste boş",
                 on_select=None, on_activate=None, on_context=None, show_meta=True):
        super().__init__(master, fg_color=C["panel"], corner_radius=10)
        self.row_h = row_height
        self.font = canvas_font(font_size)
        self.meta_font = canvas_font(max(9, font_size - 1))
        self.char_w = font_size * 0.58
        self.empty_text = empty_text
        self.show_meta = show_meta
        self.on_select = on_select
        self.on_activate = on_activate
        self.on_context = on_context
        self._items = []
        self._offset = 0.0
        self._hover = -1
        self._sel = -1
        self._pool = []
        self._empty_id = None

        self.canvas = tk.Canvas(self, bg=C["panel"], highlightthickness=0, bd=0, takefocus=1)
        self.sb = ctk.CTkScrollbar(self, command=self.yview, width=12,
                                   fg_color="transparent",
                                   button_color=C["line"], button_hover_color=C["muted"])
        self.canvas.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        self.sb.pack(side="right", fill="y", padx=(2, 4), pady=6)

        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-3>", self._on_right)
        self.canvas.bind("<Enter>", self._grab_wheel)
        self.canvas.bind("<Key>", self._on_key)

    def set_items(self, items, keep_scroll=False):
        self._items = items or []
        self._sel = -1
        self._hover = -1
        if not keep_scroll:
            self._offset = 0.0
        self._redraw()

    def update_item(self, idx, **alanlar):
        """Tek satırı günceller; seçim ve kaydırma konumu korunur."""
        if 0 <= idx < len(self._items):
            self._items[idx].update(alanlar)
            self._redraw()

    def set_placeholder(self, text):
        self.empty_text = text
        self._items = []
        self._offset = 0.0
        self._sel = -1
        self._redraw()

    def count(self):
        return len(self._items)

    def selected(self):
        return self._items[self._sel] if 0 <= self._sel < len(self._items) else None

    def select_index(self, idx, notify=True):
        if not (0 <= idx < len(self._items)):
            return
        self._sel = idx
        self._ensure_visible(idx)
        self._redraw()
        if notify and self.on_select:
            self.on_select(self._items[idx], idx)

    def yview(self, *args):
        if not args:
            return (0.0, 1.0)
        total = len(self._items) * self.row_h
        h = max(1, self.canvas.winfo_height())
        if args[0] == "moveto":
            self._set_offset(float(args[1]) * total)
        elif args[0] == "scroll":
            step = self.row_h if args[2] == "units" else h
            self._set_offset(self._offset + int(args[1]) * step)
        return None

    def _set_offset(self, value):
        h = max(1, self.canvas.winfo_height())
        max_off = max(0, len(self._items) * self.row_h - h)
        value = max(0, min(value, max_off))
        if abs(value - self._offset) < 0.5:
            return
        self._offset = value
        self._redraw()

    def _sync_scrollbar(self):
        total = max(1, len(self._items) * self.row_h)
        h = max(1, self.canvas.winfo_height())
        if total <= h:
            self.sb.set(0, 1)
        else:
            self.sb.set(self._offset / total, (self._offset + h) / total)

    def _ensure_visible(self, idx):
        h = max(1, self.canvas.winfo_height())
        top = idx * self.row_h
        if top < self._offset:
            self._set_offset(top)
        elif top + self.row_h > self._offset + h:
            self._set_offset(top + self.row_h - h)

    def _grab_wheel(self, _e=None):
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", self._on_wheel)
        self.canvas.bind("<Button-5>", self._on_wheel)

    def _on_wheel(self, event):
        num = getattr(event, "num", None)
        if num == 4:
            delta = -3
        elif num == 5:
            delta = 3
        else:
            delta = -3 if event.delta > 0 else 3
        self._set_offset(self._offset + delta * self.row_h)
        return "break"

    def _index_at(self, y):
        idx = int((y + self._offset) // self.row_h)
        return idx if 0 <= idx < len(self._items) else -1

    def _on_motion(self, event):
        idx = self._index_at(event.y)
        if idx != self._hover:
            self._hover = idx
            self._paint_rows()

    def _on_leave(self, _event):
        if self._hover != -1:
            self._hover = -1
            self._paint_rows()

    def _on_click(self, event):
        self.canvas.focus_set()
        idx = self._index_at(event.y)
        if idx < 0:
            return
        self._sel = idx
        self._paint_rows()
        if self.on_select:
            self.on_select(self._items[idx], idx)

    def _on_double(self, event):
        idx = self._index_at(event.y)
        if idx >= 0 and self.on_activate:
            self.on_activate(self._items[idx], idx)

    def _on_right(self, event):
        idx = self._index_at(event.y)
        if idx < 0:
            return
        self._sel = idx
        self._paint_rows()
        if self.on_context:
            self.on_context(event, self._items[idx], idx)

    def _on_key(self, event):
        if not self._items:
            return
        h = max(1, self.canvas.winfo_height())
        page = max(1, h // self.row_h - 1)
        key = event.keysym
        if key == "Down":
            self.select_index(min(self._sel + 1, len(self._items) - 1))
        elif key == "Up":
            self.select_index(max(self._sel - 1, 0))
        elif key == "Next":
            self.select_index(min(self._sel + page, len(self._items) - 1))
        elif key == "Prior":
            self.select_index(max(self._sel - page, 0))
        elif key == "Home":
            self.select_index(0)
        elif key == "End":
            self.select_index(len(self._items) - 1)
        elif key == "Return" and self.on_activate and self._sel >= 0:
            self.on_activate(self._items[self._sel], self._sel)
        else:
            return
        return "break"

    def _make_row(self):
        cv = self.canvas
        return {
            "bg": cv.create_rectangle(0, 0, 0, 0, width=0, fill=C["panel"]),
            "bar": cv.create_rectangle(0, 0, 0, 0, width=0, fill=C["panel"]),
            "text": cv.create_text(0, 0, anchor="w", fill=C["text"], font=self.font, text=""),
            "meta": cv.create_text(0, 0, anchor="e", fill=C["muted"], font=self.meta_font, text=""),
        }

    def _redraw(self):
        cv = self.canvas
        h, w = cv.winfo_height(), cv.winfo_width()
        if h <= 1 or w <= 1:
            return
        max_off = max(0, len(self._items) * self.row_h - h)
        if self._offset > max_off:
            self._offset = max_off
        need = h // self.row_h + 2
        while len(self._pool) < need:
            self._pool.append(self._make_row())
        if not self._items:
            if self._empty_id is None:
                self._empty_id = cv.create_text(0, 0, fill=C["muted"], font=self.font, text="")
            cv.coords(self._empty_id, w / 2, min(64, h / 2))
            cv.itemconfigure(self._empty_id, state="normal", text=self.empty_text)
        elif self._empty_id is not None:
            cv.itemconfigure(self._empty_id, state="hidden")
        self._paint_rows()
        self._sync_scrollbar()

    def _paint_rows(self):
        cv = self.canvas
        h, w = cv.winfo_height(), cv.winfo_width()
        if h <= 1 or w <= 1 or not self._pool:
            return
        first = int(self._offset // self.row_h)
        max_chars = max(8, int((w - (110 if self.show_meta else 40)) / self.char_w))
        for i, row in enumerate(self._pool):
            idx = first + i
            y = idx * self.row_h - self._offset
            if idx >= len(self._items) or y >= h:
                for key in row:
                    cv.itemconfigure(row[key], state="hidden")
                continue
            item = self._items[idx]
            bg = C["sel"] if idx == self._sel else (C["hover"] if idx == self._hover else C["panel"])
            cv.coords(row["bg"], 0, y, w, y + self.row_h - 1)
            cv.itemconfigure(row["bg"], state="normal", fill=bg)
            cv.coords(row["bar"], 0, y + 4, 3, y + self.row_h - 5)
            cv.itemconfigure(row["bar"], state="normal",
                             fill=C["accent"] if idx == self._sel else bg)
            text = item.get("text", "")
            if len(text) > max_chars:
                text = text[:max_chars - 1] + "…"
            cv.coords(row["text"], 14, y + self.row_h / 2)
            cv.itemconfigure(row["text"], state="normal", text=text,
                             fill=item.get("color", C["text"]))
            meta = item.get("meta", "") if self.show_meta else ""
            cv.coords(row["meta"], w - 12, y + self.row_h / 2)
            cv.itemconfigure(row["meta"], state="normal" if meta else "hidden",
                             text=meta, fill=C["muted"])

# ============================== İÇERİK GRİD ==============================
class ContentGrid(ctk.CTkFrame):
    COLS = 5              # sabit: her satırda 5 afiş
    MIN_COLS = 2          # pencere daralırsa okunaklı kalsın diye alt sınır
    MAX_COLS = 5
    CARD_PAD = 6          # kart başına tek taraf boşluk (toplam 2x)
    SCROLL_RESERVE = 34   # kaydırma çubuğu + iç kenar payı
    MIN_CARD_W = 150      # bunun altına inmek yerine kolon azaltılır
    MAX_CARD_W = 320      # çok geniş ekranda afiş devleşmesin
    LIVE_MAX_CARD_W = 232 # kanal logosu dairesi gereksiz büyümesin
    POSTER_RATIO = 1.5    # 2:3 afiş oranı
    TITLE_BLOCK = 61      # başlık + alt bilgi + boşluklar
    MASTER_W = 420        # diske kaydedilen ana afiş (yeniden ölçekleme kaynağı)
    MASTER_H = 630
    LOGO_MASTER = 420     # canlı TV: dairesel kanal logosunun ana ölçüsü
    # geriye dönük uyumluluk (dışarıdan okunabiliyor)
    CARD_W = 203
    CARD_H = 336
    IMG_W = 183
    IMG_H = 274

    def __init__(self, master, on_select=None, on_activate=None, on_context=None):
        super().__init__(master, fg_color=C["bg"])
        self.on_select = on_select
        self.on_activate = on_activate
        self.on_context = on_context
        self._items = []
        self._cards = []
        self._selected = -1
        self._poster_refs = {}
        self._masters = {}
        self.circular = False      # canlı TV'de kanal logoları yuvarlak
        self._bos_daire_ref = {}
        self._nesil = 0            # liste değişince artar; eski indirmeler iptal olur
        self._isler = []
        self._pool = ThreadPoolExecutor(max_workers=6)
        self._alive = True
        self.cols = self.COLS
        self.card_w = self.CARD_W
        self.card_h = self.CARD_H
        self.img_w = self.IMG_W
        self.img_h = self.IMG_H
        self._resize_after = None
        self._last_width = 0

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=C["bg"],
                                              scrollbar_button_color=C["line"],
                                              scrollbar_button_hover_color=C["muted"])
        self.scroll.pack(fill="both", expand=True)
        self.grid_frame = ctk.CTkFrame(self.scroll, fg_color=C["bg"])
        self.grid_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self._placeholder_label = ctk.CTkLabel(self.grid_frame, text="Kategori seçin",
                                                font=ui_font(13), text_color=C["muted"])
        self._placeholder_label.grid(row=0, column=0, columnspan=self.cols, pady=60)
        self._apply_columns(self.cols)
        try:
            self.bind("<Configure>", self._on_resize, add="+")
        except Exception:
            pass

    # ---- yerleşim ölçüleri ----
    def _metrics(self, width):
        """Sabit 5 kolon; kart genişliği pencereye göre büyür.
        Pencere çok darsa kolon sayısı düşürülür."""
        usable = max(0, int(width) - self.SCROLL_RESERVE)
        cols = self.COLS
        while cols > self.MIN_COLS and usable / cols < self.MIN_CARD_W + self.CARD_PAD * 2:
            cols -= 1
        ust_sinir = self.LIVE_MAX_CARD_W if self.circular else self.MAX_CARD_W
        card_w = int(usable / cols) - self.CARD_PAD * 2
        card_w = max(self.MIN_CARD_W, min(ust_sinir, card_w))
        card_w -= card_w % 2                      # tek piksel titremesini önler
        img_w = card_w - 20
        # Yuvarlak kanal logosu kare kutuya oturur; afişler 2:3 kalır.
        img_h = img_w if self.circular else int(round(img_w * self.POSTER_RATIO))
        card_h = img_h + self.TITLE_BLOCK
        return cols, card_w, card_h, img_w, img_h

    def _apply_columns(self, cols):
        for i in range(self.COLS + 1):
            try:
                self.grid_frame.grid_columnconfigure(
                    i, weight=1 if i < cols else 0,
                    uniform="poster" if i < cols else "")
            except Exception:
                pass

    def _on_resize(self, event=None):
        width = getattr(event, "width", 0) or self.winfo_width()
        if width <= 1 or abs(width - self._last_width) < 6:
            return
        self._last_width = width
        if self._resize_after:
            try:
                self.after_cancel(self._resize_after)
            except Exception:
                pass
        self._resize_after = self.after(120, lambda w=width: self._relayout(w))

    def _relayout(self, width):
        self._resize_after = None
        if not self._alive:
            return
        cols, card_w, card_h, img_w, img_h = self._metrics(width)
        if (cols, card_w, img_w) == (self.cols, self.card_w, self.img_w):
            return
        boyut_degisti = (card_w, img_w) != (self.card_w, self.img_w)
        self.cols, self.card_w, self.card_h = cols, card_w, card_h
        self.img_w, self.img_h = img_w, img_h
        self._apply_columns(cols)
        if not (self._items and self._cards):
            try:
                self._placeholder_label.grid_configure(columnspan=cols)
            except Exception:
                pass
            return
        for i, card in enumerate(self._cards):
            try:
                card.grid_configure(row=i // cols, column=i % cols)
                if boyut_degisti:
                    card.configure(width=card_w, height=card_h)
                    card._img_label.configure(width=img_w, height=img_h)
                    card._title_label.configure(wraplength=card_w - 20)
            except Exception:
                pass
        if boyut_degisti:
            # Afişler diskteki ana görselden yeniden ölçekleniyor: ağ trafiği yok.
            for ctk_img in self._poster_refs.values():
                try:
                    ctk_img.configure(size=(img_w, img_h))
                except Exception:
                    pass

    def _sync_metrics(self):
        width = self.winfo_width()
        if width > 1:
            cols, card_w, card_h, img_w, img_h = self._metrics(width)
            self.cols, self.card_w, self.card_h = cols, card_w, card_h
            self.img_w, self.img_h = img_w, img_h
            self._apply_columns(self.cols)
        return self.cols

    def set_items(self, items, session=None):
        self._cleanup()
        self._items = items or []
        self._selected = -1
        # Canlı TV listesinde logolar yuvarlak, film/dizide afiş dikdörtgen.
        self.circular = bool(self._items) and all(
            (it.get("data") or {}).get("kind") == "live" for it in self._items[:12])
        nesil = self._nesil
        cols = self._sync_metrics()
        if not self._items:
            self._placeholder_label.configure(text="Bu kategoride içerik yok")
            self._placeholder_label.grid(row=0, column=0, columnspan=cols, pady=60)
            return
        self._placeholder_label.grid_forget()
        for i, item in enumerate(self._items):
            row = i // cols
            col = i % cols
            card = self._create_card(item, i, row, col)
            self._cards.append(card)
            url = item.get("data", {}).get("icon", "")
            if url and session:
                self._isler.append(
                    self._pool.submit(self._load_poster, url, i, session, nesil))

    def set_placeholder(self, text):
        self._cleanup()
        self._items = []
        cols = self._sync_metrics()
        self._placeholder_label.configure(text=text)
        self._placeholder_label.grid(row=0, column=0, columnspan=cols, pady=60)

    def selected(self):
        if 0 <= self._selected < len(self._items):
            return self._items[self._selected]
        return None

    def _cleanup(self):
        # Liste değişti: önceki listenin bekleyen afiş indirmelerini iptal et.
        # Aksi halde 2000 kartlık bir kategoriden çıkıldığında yeni listenin
        # afişleri o kuyruğun arkasında dakikalarca bekliyor.
        self._nesil += 1
        for is_ in self._isler:
            try:
                is_.cancel()
            except Exception:
                pass
        self._isler = []
        for card in self._cards:
            try:
                card.destroy()
            except Exception:
                pass
        self._cards = []
        self._poster_refs = {}
        self._masters = {}

    def _create_card(self, item, index, row, col):
        card = ctk.CTkFrame(self.grid_frame, width=self.card_w, height=self.card_h,
                            fg_color=C["panel"], corner_radius=10, border_width=0)
        card.grid(row=row, column=col, padx=self.CARD_PAD, pady=self.CARD_PAD, sticky="n")
        card.grid_propagate(False)
        # Dairesel modda yuvarlaklık görüntünün alfa kanalından gelir;
        # etikete corner_radius verilmez (CTk büyük yarıçapta görüntüyü gizliyor).
        img_label = ctk.CTkLabel(card, text="", font=ui_font(28),
                                 text_color=C["muted"],
                                 width=self.img_w, height=self.img_h,
                                 fg_color="transparent" if self.circular else C["panel2"],
                                 corner_radius=0 if self.circular else 6)
        img_label.pack(padx=10, pady=(10, 6))
        if self.circular:
            img_label.configure(image=self._bos_daire_gorsel(), text="")
        title = item.get("text", "")
        if len(title) > 40:
            title = title[:39] + "…"
        title_label = ctk.CTkLabel(card, text=title, font=ui_font(12, "bold"),
                                   text_color=C["text"], wraplength=self.card_w - 20,
                                   height=34, justify="center")
        title_label.pack(padx=8, pady=(0, 1))
        meta_label = ctk.CTkLabel(card, text=item.get("meta", ""), font=ui_font(10),
                                  text_color=C["muted"], height=14)
        meta_label.pack(padx=8, pady=(0, 6))
        for w in (card, img_label, title_label, meta_label):
            w.bind("<Button-1>", lambda e, idx=index: self._on_click(idx))
            w.bind("<Double-Button-1>", lambda e, idx=index: self._on_double(idx))
            w.bind("<Button-3>", lambda e, idx=index: self._on_right(e, idx))
        card._img_label = img_label
        card._title_label = title_label
        card._index = index
        return card

    def _bos_daire_gorsel(self):
        """Logo yüklenene kadar gösterilen boş daire (kartlar paylaşır)."""
        anahtar = self.img_w
        gorsel = self._bos_daire_ref.get(anahtar) if self._bos_daire_ref else None
        if gorsel is None:
            ham = bos_daire(max(2, self.img_w), C["panel2"])
            gorsel = ctk.CTkImage(light_image=ham, dark_image=ham,
                                  size=(self.img_w, self.img_h))
            self._bos_daire_ref = {anahtar: gorsel}
        return gorsel

    def _on_right(self, event, index):
        self._on_click(index)
        if self.on_context and 0 <= index < len(self._items):
            self.on_context(event, self._items[index], index)

    def _on_click(self, index):
        self._selected = index
        for i, card in enumerate(self._cards):
            card.configure(border_width=2 if i == index else 0,
                           border_color=C["accent"] if i == index else C["panel"])
        if self.on_select and 0 <= index < len(self._items):
            self.on_select(self._items[index], index)

    def _on_double(self, index):
        self._selected = index
        if self.on_activate and 0 <= index < len(self._items):
            self.on_activate(self._items[index], index)

    def _load_poster(self, url, index, session, nesil):
        if nesil != self._nesil or not self._alive:
            return                      # liste değişti: indirmeye hiç başlama
        try:
            # Disk önbelleğinde tek bir "ana" görsel tutuluyor. Kart boyutu
            # değişince görüntü bundan yeniden ölçekleniyor, yani pencereyi
            # boyutlandırmak yeniden indirme yapmıyor.
            dairesel = self.circular
            if dairesel:
                path = os.path.join(
                    POSTER_DIR,
                    _digest(f"{url}|daire{self.LOGO_MASTER}") + ".png")
            else:
                path = os.path.join(
                    POSTER_DIR,
                    _digest(f"{url}|ana{self.MASTER_W}x{self.MASTER_H}") + ".jpg")
            if os.path.exists(path):
                img = Image.open(path)
                img.load()
                if dairesel:
                    img = img.convert("RGBA")
            else:
                resp = session.get(url, timeout=8)
                resp.raise_for_status()
                ham = Image.open(io.BytesIO(resp.content))
                if dairesel:
                    # Kanal logosu kırpılmaz; daire içine sığdırılır.
                    img = dairesel_logo(ham, self.LOGO_MASTER, C["panel2"])
                    img.save(path, "PNG")
                else:
                    # Oranı bozmadan kutuyu dolduran kırpma (afişler yamulmuyor)
                    img = ImageOps.fit(ham.convert("RGB"),
                                       (self.MASTER_W, self.MASTER_H),
                                       Image.LANCZOS, centering=(0.5, 0.45))
                    img.save(path, "JPEG", quality=88)
            if nesil != self._nesil or not self._alive:
                return                  # indirme bitti ama liste değişmiş
            if 0 <= index < len(self._cards):
                self.after(0, self._apply_poster, index, img, nesil)
        except Exception:
            pass

    def _apply_poster(self, index, master, nesil):
        if nesil != self._nesil:
            return                      # eski listenin afişi yeni karta yapışmasın
        if not (self._alive and 0 <= index < len(self._cards)):
            return
        try:
            ctk_img = ctk.CTkImage(light_image=master, dark_image=master,
                                   size=(self.img_w, self.img_h))
            self._cards[index]._img_label.configure(image=ctk_img, text="")
            self._poster_refs[index] = ctk_img
            self._masters[index] = master
        except Exception:
            pass

    def destroy(self):
        self._alive = False
        self._nesil += 1
        havuz_kapat(self._pool)
        super().destroy()

# ============================== DETAY PANELİ ==============================
def _metin(value, limit=0):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("n/a", "null", "none", "0000-00-00"):
        return ""
    return text[:limit] + "…" if limit and len(text) > limit else text

def _puan_degeri(info):
    for key in ("rating", "imdb_rating", "vote_average"):
        try:
            value = float(str(info.get(key, "")).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if key == "rating" and value <= 5 and info.get("rating_5based"):
            value *= 2
        return min(10.0, value)
    try:
        value = float(str(info.get("rating_5based", "")).replace(",", "."))
        if value > 0:
            return min(10.0, value * 2)
    except (TypeError, ValueError):
        pass
    return None

def _yildizlar(puan):
    dolu = int(round(puan / 2.0))
    return "★" * dolu + "☆" * (5 - dolu)

def _sure_metni(info):
    ham = _metin(info.get("duration"))
    if ham and ham not in ("00:00:00",):
        parcalar = ham.split(":")
        if len(parcalar) == 3:
            try:
                saat, dakika = int(parcalar[0]), int(parcalar[1])
                if saat or dakika:
                    return f"{saat} sa {dakika} dk" if saat else f"{dakika} dk"
            except ValueError:
                pass
        else:
            return ham
    for key in ("episode_run_time", "duration_secs"):
        try:
            sayi = int(float(info.get(key)))
        except (TypeError, ValueError):
            continue
        if sayi <= 0:
            continue
        if key == "duration_secs":
            sayi //= 60
        saat, dakika = divmod(sayi, 60)
        return f"{saat} sa {dakika} dk" if saat else f"{dakika} dk"
    return ""

def _epg_coz(value):
    ham = _metin(value)
    if not ham:
        return ""
    try:
        import base64
        return base64.b64decode(ham + "=" * (-len(ham) % 4)).decode("utf-8", "replace").strip()
    except Exception:
        return ham

def _epg_saat(value):
    ham = _metin(value)
    if len(ham) >= 16:
        return ham[11:16]
    return ""


class DetailPanel:
    """Kart tıklanınca açılan bağımsız künye penceresi.

    Ana pencereye gömülü DEĞİL: kullanıcı fareyle istediği yere sürükleyebilir.
    Kapatmak pencereyi yok etmez, gizler; böylece tekrar tekrar açılabilir.
    Pencere herhangi bir nedenle yok olursa bir sonraki açılışta yeniden kurulur.
    """
    WIDTH = 420
    HEIGHT = 760
    MIN_H = 420
    POSTER_W = 210
    POSTER_H = 315
    ROWS = [("genre", "Tür"), ("duration", "Süre"), ("release", "Yayın"),
            ("country", "Ülke"), ("director", "Yönetmen"), ("cast", "Oyuncular"),
            ("seasons", "Sezon / Bölüm"), ("now", "Şimdi"), ("next", "Sırada")]

    def __init__(self, master, session=None, on_play=None,
                 on_favorite=None, on_close=None):
        self.master = master
        self.session = session
        self.on_play = on_play
        self.on_favorite = on_favorite
        self.on_close = on_close
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._alive = True
        self._token = 0
        self._poster_ref = None
        self._bos_ref = None
        self._circular = False
        self._record = {}
        self._gecerli_baslik = ""
        self._geometri = None      # kullanıcının taşıdığı konum hatırlanır
        self.win = None

    # ---- pencere kurulumu ----
    def _pencere_var(self):
        win = self.win
        try:
            return win is not None and bool(win.winfo_exists())
        except Exception:
            return False

    def _pencere_kur(self):
        """Pencereyi (yeniden) kurar. Zaten varsa dokunmaz."""
        if self._pencere_var():
            return True
        if not self._alive:
            return False
        try:
            self.win = ctk.CTkToplevel(self.master)
        except Exception as e:
            print(f"Künye penceresi açılamadı: {e}")
            self.win = None
            return False
        win = self.win
        win.title(APP_NAME)
        win.configure(fg_color=C["panel"])
        win.minsize(360, self.MIN_H)
        win.geometry(self._geometri or self._ilk_konum())
        # Kapatma pencereyi YOK ETMEZ, gizler: tekrar açılabilir kalır.
        win.protocol("WM_DELETE_WINDOW", self.hide)
        win.bind("<Escape>", lambda e: self.hide())
        simge_uygula(win)

        head = ctk.CTkFrame(win, fg_color=C["panel2"], corner_radius=0, height=52)
        head.pack(fill="x")
        head.pack_propagate(False)
        self.title_label = ctk.CTkLabel(head, text=self._gecerli_baslik,
                                        font=ui_font(14, "bold"),
                                        text_color=C["text"], anchor="w",
                                        wraplength=self.WIDTH - 76, justify="left")
        self.title_label.pack(side="left", fill="x", expand=True, padx=(16, 6), pady=8)
        ctk.CTkButton(head, text="✕", width=30, height=30, corner_radius=15,
                      fg_color=C["panel"], hover_color=C["live"], text_color=C["text"],
                      font=ui_font(13), command=self.hide).pack(side="right", padx=12)

        self.body = ctk.CTkScrollableFrame(win, fg_color=C["panel"],
                                           scrollbar_button_color=C["line"],
                                           scrollbar_button_hover_color=C["muted"])
        self.body.pack(fill="both", expand=True, padx=2, pady=(6, 0))

        self.poster_label = ctk.CTkLabel(self.body, text="", width=self.POSTER_W,
                                         height=self.POSTER_H, fg_color=C["panel2"],
                                         corner_radius=8, font=ui_font(26),
                                         text_color=C["muted"])
        self.poster_label.pack(pady=(4, 10))

        self.rating_label = ctk.CTkLabel(self.body, text="", font=ui_font(15, "bold"),
                                         text_color=C["accent"])
        self.rating_label.pack(pady=(0, 2))
        self.rating_note = ctk.CTkLabel(self.body, text="", font=ui_font(9),
                                        text_color=C["muted"])
        self.rating_note.pack(pady=(0, 8))

        self.rows = {}
        for key, baslik in self.ROWS:
            satir = ctk.CTkFrame(self.body, fg_color="transparent")
            ctk.CTkLabel(satir, text=baslik, font=ui_font(10, "bold"),
                         text_color=C["muted"], width=96,
                         anchor="nw").pack(side="left", anchor="n", padx=(4, 8))
            deger_lbl = ctk.CTkLabel(satir, text="", font=ui_font(11),
                                     text_color=C["text"], anchor="w", justify="left",
                                     wraplength=self.WIDTH - 140)
            deger_lbl.pack(side="left", fill="x", expand=True)
            self.rows[key] = (satir, deger_lbl)

        self.plot_head = ctk.CTkLabel(self.body, text="Özet", font=ui_font(10, "bold"),
                                      text_color=C["muted"], anchor="w")
        self.plot_label = ctk.CTkLabel(self.body, text="", font=ui_font(11),
                                       text_color=C["text"], anchor="w", justify="left",
                                       wraplength=self.WIDTH - 44)
        self.status_label = ctk.CTkLabel(self.body, text="", font=ui_font(11),
                                         text_color=C["muted"])

        foot = ctk.CTkFrame(win, fg_color=C["panel"], height=54)
        foot.pack(fill="x", padx=12, pady=10)
        foot.pack_propagate(False)
        self.play_btn = ctk.CTkButton(foot, text="▶  Oynat", height=38, corner_radius=8,
                                      fg_color=C["accent"], hover_color=C["accent_dk"],
                                      text_color=C["bg"], font=ui_font(12, "bold"),
                                      command=self._play)
        self.play_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.fav_btn = ctk.CTkButton(foot, text="☆", width=46, height=38, corner_radius=8,
                                     fg_color=C["panel2"], hover_color=C["line"],
                                     text_color=C["accent"], font=ui_font(15),
                                     command=self._favorite)
        self.fav_btn.pack(side="left")
        return True

    def _ilk_konum(self):
        """İlk açılışta ana pencerenin sağına, ekran dışına taşmadan yerleşir."""
        try:
            self.master.update_idletasks()
            ekran_w = self.master.winfo_screenwidth()
            ekran_h = self.master.winfo_screenheight()
            x = self.master.winfo_rootx() + self.master.winfo_width() + 12
            y = self.master.winfo_rooty()
            yukseklik = max(self.MIN_H, min(self.HEIGHT, ekran_h - 80))
            if x + self.WIDTH > ekran_w:              # sağda yer yoksa üste bindir
                x = max(0, ekran_w - self.WIDTH - 20)
            y = max(0, min(y, ekran_h - yukseklik - 40))
            return f"{self.WIDTH}x{yukseklik}+{int(x)}+{int(y)}"
        except Exception:
            return f"{self.WIDTH}x{self.HEIGHT}"

    def _konumu_hatirla(self):
        if not self._pencere_var():
            return
        try:
            self._geometri = self.win.geometry()
        except Exception:
            pass

    # ---- yer tutucu görsel (image=None kullanılmıyor) ----
    def _bos_gorsel(self):
        if self._circular:
            ham = bos_daire(self.POSTER_W, C["panel2"])
            olcu = (self.POSTER_W, self.POSTER_W)
        else:
            ham = Image.new("RGBA", (self.POSTER_W, self.POSTER_H),
                            _hex_rgb(C["panel2"]) + (255,))
            olcu = (self.POSTER_W, self.POSTER_H)
        self._bos_ref = ctk.CTkImage(light_image=ham, dark_image=ham, size=olcu)
        return self._bos_ref

    # ---- dış arayüz ----
    def show(self, rec, is_favorite=False):
        self._token += 1
        token = self._token
        self._record = rec or {}
        self._circular = self._record.get("kind") == "live"
        self._gecerli_baslik = _metin(self._record.get("name"), 90)
        zaten_acik = self.is_open()
        if not self._pencere_kur():
            return token
        win = self.win
        try:
            win.title(f"{self._gecerli_baslik or 'Künye'} — {APP_NAME}")
            self.title_label.configure(text=self._gecerli_baslik)
            self.fav_btn.configure(text="★" if is_favorite else "☆")
            if self._circular:
                self.poster_label.configure(width=self.POSTER_W, height=self.POSTER_W,
                                            fg_color="transparent", corner_radius=0)
            else:
                self.poster_label.configure(width=self.POSTER_W, height=self.POSTER_H,
                                            fg_color=C["panel2"], corner_radius=8)
            self.poster_label.configure(image=self._bos_gorsel(), text="")
            self._poster_ref = None
            for satir, _ in self.rows.values():
                satir.pack_forget()
            self.plot_head.pack_forget()
            self.plot_label.pack_forget()
            self.status_label.configure(text="Bilgiler alınıyor…")
            self.status_label.pack(pady=14)
            self._apply_basic(self._record)
            try:
                self.body._parent_canvas.yview_moveto(0.0)
            except Exception:
                pass
            # İlk açılışta öne getir; zaten açıksa odağı çalmadan yükselt,
            # böylece afişler arasında gezerken odak zıplamaz.
            if zaten_acik:
                win.lift()
            else:
                win.deiconify()
                bring_to_front(win, tries=2)
        except Exception as e:
            print(f"Künye penceresi güncellenemedi: {e}")
            return token
        url = self._record.get("icon", "")
        if url and self.session:
            self._pool.submit(self._load_poster, url, token, self._circular)
        return token

    def apply_details(self, token, info, kind):
        if token != self._token or not self._alive or not self._pencere_var():
            return
        try:
            self.status_label.pack_forget()
            info = info if isinstance(info, dict) else {}
            rec = self._record or {}

            puan = _puan_degeri(info) or _puan_degeri(rec)
            if puan:
                self.rating_label.configure(text=f"{_yildizlar(puan)}   {puan:.1f} / 10")
                self.rating_note.configure(text="sağlayıcı künyesi (IMDb/TMDB)")
            else:
                self.rating_label.configure(text="")
                self.rating_note.configure(text="")

            degerler = {
                "genre": _metin(info.get("genre")),
                "duration": _sure_metni(info),
                "release": _metin(info.get("releasedate") or info.get("release_date")
                                  or rec.get("year")),
                "country": _metin(info.get("country")),
                "director": _metin(info.get("director"), 120),
                "cast": _metin(info.get("cast") or info.get("actors"), 220),
                "seasons": "", "now": "", "next": "",
            }
            if kind == "series":
                sezon = info.get("_season_count") or 0
                bolum = info.get("_episode_count") or 0
                if sezon or bolum:
                    degerler["seasons"] = f"{sezon} sezon · {bolum} bölüm"
            if kind == "live":
                epg = info.get("_epg") or []
                for idx, anahtar in enumerate(("now", "next")):
                    if idx < len(epg) and isinstance(epg[idx], dict):
                        baslik = _epg_coz(epg[idx].get("title"))
                        bas = _epg_saat(epg[idx].get("start"))
                        son = _epg_saat(epg[idx].get("end") or epg[idx].get("stop"))
                        aralik = f"{bas}–{son}  " if bas else ""
                        if baslik:
                            degerler[anahtar] = f"{aralik}{baslik}"[:160]

            dolu = False
            for key, _ in self.ROWS:
                satir, deger_lbl = self.rows[key]
                metin = degerler.get(key, "")
                if metin:
                    deger_lbl.configure(text=metin)
                    satir.pack(fill="x", pady=3)
                    dolu = True
                else:
                    satir.pack_forget()

            ozet = _metin(info.get("plot") or info.get("description") or rec.get("plot"))
            if kind == "live" and not ozet:
                epg = info.get("_epg") or []
                if epg and isinstance(epg[0], dict):
                    ozet = _epg_coz(epg[0].get("description"))
            if ozet:
                self.plot_head.pack(fill="x", padx=4, pady=(12, 2))
                self.plot_label.pack(fill="x", padx=4, pady=(0, 10))
                self.plot_label.configure(text=ozet)
                dolu = True
            if not dolu and not puan:
                self.status_label.configure(text="Bu içerik için ek bilgi yok.")
                self.status_label.pack(pady=14)
        except Exception as e:
            print(f"Künye doldurulamadı: {e}")

    def detail_failed(self, token, error):
        if token != self._token or not self._alive or not self._pencere_var():
            return
        try:
            self.status_label.configure(text=f"Bilgi alınamadı: {error}"[:120])
            self.status_label.pack(pady=14)
        except Exception:
            pass

    def set_favorite(self, is_favorite):
        if not self._pencere_var():
            return
        try:
            self.fav_btn.configure(text="★" if is_favorite else "☆")
        except Exception:
            pass

    def hide(self):
        """Kapat: pencere yok edilmez, gizlenir; konumu hatırlanır."""
        self._token += 1
        self._konumu_hatirla()
        if self._pencere_var():
            try:
                self.win.withdraw()
            except Exception:
                pass
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass

    def pencereyi_devret(self):
        """Penceresini oynatıcıya bırakır; panel bir sonraki açılışta yenisini kurar.

        Böylece 'ana pencere + önizleme + oynatıcı' üçlüsü yerine en fazla
        iki pencere açık kalıyor.
        """
        if not self._pencere_var():
            return None
        win = self.win
        self._token += 1                 # bekleyen afiş işleri bu pencereye yazmasın
        self._konumu_hatirla()
        self.win = None
        try:
            win.protocol("WM_DELETE_WINDOW", lambda: None)
        except Exception:
            pass
        return win

    def is_open(self):
        if not self._pencere_var():
            return False
        try:
            return self.win.state() == "normal"
        except Exception:
            return False

    def destroy(self):
        self._alive = False
        havuz_kapat(self._pool)
        if self._pencere_var():
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None

    # ---- iç ----
    def _apply_basic(self, rec):
        """Ayrıntı gelene kadar elde olan bilgiyi göster."""
        puan = _puan_degeri(rec)
        if puan:
            self.rating_label.configure(text=f"{_yildizlar(puan)}   {puan:.1f} / 10")
            self.rating_note.configure(text="sağlayıcı künyesi (IMDb/TMDB)")
        else:
            self.rating_label.configure(text="")
            self.rating_note.configure(text="")

    def _play(self):
        if self.on_play:
            self.on_play()

    def _favorite(self):
        if self.on_favorite:
            self.on_favorite()

    def _load_poster(self, url, token, dairesel):
        try:
            if dairesel:
                olcu = (self.POSTER_W, self.POSTER_W)
                path = os.path.join(
                    POSTER_DIR, _digest(f"{url}|detaydaire{self.POSTER_W}") + ".png")
            else:
                olcu = (self.POSTER_W, self.POSTER_H)
                path = os.path.join(
                    POSTER_DIR,
                    _digest(f"{url}|detay{self.POSTER_W}x{self.POSTER_H}") + ".jpg")
            if os.path.exists(path):
                img = Image.open(path)
                img.load()
                if dairesel:
                    img = img.convert("RGBA")
            else:
                resp = self.session.get(url, timeout=10)
                resp.raise_for_status()
                ham = Image.open(io.BytesIO(resp.content))
                if dairesel:
                    img = dairesel_logo(ham, self.POSTER_W, C["panel2"])
                    img.save(path, "PNG")
                else:
                    img = ImageOps.fit(ham.convert("RGB"), olcu,
                                       Image.LANCZOS, centering=(0.5, 0.45))
                    img.save(path, "JPEG", quality=90)
            if self._alive:
                self._ui(self._apply_poster, token, img, olcu)
        except Exception:
            pass

    def _ui(self, fn, *args):
        """İş parçacığından arayüze güvenli geçiş."""
        if not (self._alive and self._pencere_var()):
            return
        try:
            self.win.after(0, lambda: fn(*args))
        except Exception:
            pass

    def _apply_poster(self, token, master, olcu):
        if token != self._token or not self._alive or not self._pencere_var():
            return
        try:
            ctk_img = ctk.CTkImage(light_image=master, dark_image=master, size=olcu)
            self.poster_label.configure(image=ctk_img, text="")
            self._poster_ref = ctk_img
        except Exception:
            pass
# ============================== POSTER ==============================
class PosterLoader:
    def __init__(self, root, session):
        self.root = root
        self.session = session
        self._q = queue.LifoQueue()
        self._mem = OrderedDict()
        self._lock = threading.Lock()
        self._token = 0
        threading.Thread(target=self._worker, daemon=True).start()

    def next_token(self):
        with self._lock:
            self._token += 1
            return self._token

    def current_token(self):
        with self._lock:
            return self._token

    def request(self, url, token, callback, box=(300, 430)):
        cached = self._mem.get(url)
        if cached is not None:
            callback(token, cached)
            return
        self._q.put((url, token, callback, box))

    def _remember(self, url, image):
        self._mem[url] = image
        if len(self._mem) > 150:
            self._mem.popitem(last=False)

    def _worker(self):
        while True:
            try:
                url, token, callback, box = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if token != self.current_token():
                continue
            path = os.path.join(POSTER_DIR, _digest(url) + ".jpg")
            image = None
            try:
                if os.path.exists(path):
                    image = Image.open(path)
                    image.load()
                else:
                    resp = self.session.get(url, timeout=6)
                    resp.raise_for_status()
                    buf = Image.open(io.BytesIO(resp.content))
                    try:
                        buf.draft("RGB", box)
                    except Exception:
                        pass
                    buf = buf.convert("RGB")
                    buf.thumbnail(box, Image.BILINEAR)
                    buf.save(path, "JPEG", quality=85)
                    image = buf
                self._remember(url, image)
            except Exception:
                image = None
            try:
                self.root.after(0, callback, token, image)
            except Exception:
                pass

# ============================== PARÇA ETİKETLERİ ==============================
# IPTV akışlarında dil kodları çoğunlukla ISO 639 (tur/tr/eng/en) gelir.
DIL_ADLARI = {
    "tr": "Türkçe", "tur": "Türkçe", "tk": "Türkçe",
    "en": "İngilizce", "eng": "İngilizce",
    "de": "Almanca", "ger": "Almanca", "deu": "Almanca",
    "fr": "Fransızca", "fre": "Fransızca", "fra": "Fransızca",
    "es": "İspanyolca", "spa": "İspanyolca",
    "it": "İtalyanca", "ita": "İtalyanca",
    "ru": "Rusça", "rus": "Rusça",
    "ar": "Arapça", "ara": "Arapça",
    "fa": "Farsça", "per": "Farsça", "fas": "Farsça",
    "ku": "Kürtçe", "kur": "Kürtçe",
    "az": "Azerice", "aze": "Azerice",
    "pt": "Portekizce", "por": "Portekizce",
    "nl": "Felemenkçe", "dut": "Felemenkçe", "nld": "Felemenkçe",
    "pl": "Lehçe", "pol": "Lehçe",
    "ro": "Rumence", "rum": "Rumence", "ron": "Rumence",
    "el": "Yunanca", "gre": "Yunanca", "ell": "Yunanca",
    "bg": "Bulgarca", "bul": "Bulgarca",
    "sr": "Sırpça", "srp": "Sırpça",
    "hr": "Hırvatça", "hrv": "Hırvatça",
    "uk": "Ukraynaca", "ukr": "Ukraynaca",
    "he": "İbranice", "heb": "İbranice",
    "hi": "Hintçe", "hin": "Hintçe",
    "ja": "Japonca", "jpn": "Japonca",
    "ko": "Korece", "kor": "Korece",
    "zh": "Çince", "chi": "Çince", "zho": "Çince",
    "sv": "İsveççe", "swe": "İsveççe",
    "no": "Norveççe", "nor": "Norveççe",
    "da": "Danca", "dan": "Danca",
    "fi": "Fince", "fin": "Fince",
    "cs": "Çekçe", "cze": "Çekçe", "ces": "Çekçe",
    "hu": "Macarca", "hun": "Macarca",
    "und": "", "mul": "Çok dilli",
}

KANAL_ADLARI = {1: "Mono", 2: "Stereo", 3: "2.1", 6: "5.1", 8: "7.1"}

def dil_adi(kod):
    kod = str(kod or "").strip().lower()
    if not kod:
        return ""
    ad = DIL_ADLARI.get(kod)
    if ad is not None:
        return ad
    return kod.upper()

def kodek_adi(ham):
    kod = str(ham or "").strip().lower()
    if not kod:
        return ""
    esle = {"aac": "AAC", "ac3": "AC3", "eac3": "E-AC3", "mp3": "MP3",
            "dts": "DTS", "truehd": "TrueHD", "opus": "Opus", "flac": "FLAC",
            "vorbis": "Vorbis", "pcm_s16le": "PCM", "h264": "H.264",
            "hevc": "H.265", "mpeg2video": "MPEG-2", "vp9": "VP9",
            "av1": "AV1", "mpeg4": "MPEG-4", "subrip": "SRT", "ass": "ASS",
            "webvtt": "VTT", "dvb_subtitle": "DVB", "hdmv_pgs_subtitle": "PGS",
            "dvd_subtitle": "VOB"}
    return esle.get(kod, kod.upper()[:10])

def _parca_id(deger):
    """mpv aid/sid/vid değerini tam sayıya çevirir ('no'/False -> None)."""
    if deger is None or deger is False:
        return None
    if isinstance(deger, bool):
        return None
    try:
        sayi = int(deger)
    except (TypeError, ValueError):
        return None
    return sayi if sayi > 0 else None

def parca_etiketi(entry, tur, sira):
    """Parça için okunaklı etiket üretir.

    Örnek: 'Türkçe · AC3 5.1 ★'  /  'İngilizce · SRT (Zorunlu)'
    """
    parcalar = []
    ad = dil_adi(entry.get("lang"))
    baslik = str(entry.get("title") or "").strip()
    if ad and baslik:
        # Başlık zaten dili içeriyorsa tekrarlama
        parcalar.append(baslik if ad.lower() in baslik.lower() else f"{ad} · {baslik}")
    elif ad:
        parcalar.append(ad)
    elif baslik:
        parcalar.append(baslik)
    elif tur == "video":
        pass          # aşağıda çözünürlük/kodek ana etiket olur
    else:
        parcalar.append({"audio": "Ses", "sub": "Altyazı"}
                        .get(tur, "Parça") + f" {sira}")

    teknik = []
    kodek = kodek_adi(entry.get("codec"))
    if kodek:
        teknik.append(kodek)
    if tur == "audio":
        try:
            kanal = int(entry.get("audio-channels") or 0)
            if kanal:
                teknik.append(KANAL_ADLARI.get(kanal, f"{kanal} kanal"))
        except (TypeError, ValueError):
            pass
    elif tur == "video":
        try:
            en = int(entry.get("demux-w") or 0)
            boy = int(entry.get("demux-h") or 0)
            if en and boy:
                teknik.insert(0, f"{en}×{boy}")
        except (TypeError, ValueError):
            pass
    if teknik:
        parcalar.append(" ".join(teknik))
    if not parcalar:
        parcalar.append(f"Görüntü {sira}")

    etiket = " · ".join(parcalar)
    ekler = []
    if entry.get("forced"):
        ekler.append("Zorunlu")
    if entry.get("external"):
        ekler.append("Dış dosya")
    if ekler:
        etiket += " (" + ", ".join(ekler) + ")"
    if entry.get("default"):
        etiket += " ★"
    return etiket[:60]

# ============================== OYNATICI ==============================
class PlayerWindow:
    SUB_OFF = "Kapalı"
    SUB_FILE = "Dosyadan yükle…"
    TRACK_OFF = "Kapalı"

    def __init__(self, master, source, title, backend, settings, on_close=None,
                 mevcut_pencere=None):
        self.master = master
        self.source = dict(source)
        self.kind = source.get("kind", "vod")
        self.is_live = self.kind == "live"
        self.settings = dict(settings)
        self.quality = self.settings.get("quality", "auto")
        self.backend = backend
        self.on_close = on_close
        self.mpv = None
        self.url = ""
        self.volume = 90
        self.muted = False
        self.fullscreen = False
        self.controls_visible = True
        self.extra_buffer = 0
        self._seek_after = None
        self._hide_after = None
        self._tick_after = None
        self._seek_active = 0
        self._seek_pending = 0
        self._resume_to = 0
        self._duration_ms = 0
        self._position_ms = 0
        self._show_remaining = False
        self._live_since = 0.0
        self._stats_cache = ""
        self._last_state = None
        self._stalls = 0
        self._stall_since = time.time()
        self._notice_until = 0
        self._opened_at = 0
        self._stats_skip = 0
        self._fallback_tried = False
        self._basarisiz = False
        self._deneme = 0
        self._denenenler = []
        self._stratejiler = []
        self._son_deneme_an = 0.0
        self._tracks_ready = False
        self._track_tries = 0
        self._audio_map = {}
        self._sub_map = {}
        self._video_map = {}
        self._son_sid = None
        self._goruntu_penceresi = None
        self._closed = False
        self._played_any = False
        self._end_error = False
        self._acildi = False          # bu yüklemede görüntü geldi mi
        self._kopma_an = 0.0          # bağlantı kopması başladığı an
        self._kopma_deneme = 0
        self._son_kopma_deneme = 0.0
        self._ag_sonuc = None         # (zaman, internet var mı)
        self._ag_yoklaniyor = False
        self._ag_son_yoklama = 0.0
        self._ended = False
        self._file_loaded = False
        self._last_mouse = 0.0

        # Önizleme penceresi açıksa ÜÇÜNCÜ pencere açmak yerine onu devral.
        self.win = self._pencereyi_hazirla(master, mevcut_pencere)
        self.win.title(f"{title} — {APP_NAME}")
        simge_uygula(self.win)
        self.win.minsize(860, 520)
        self.win.configure(fg_color="#000000")
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.video_frame = tk.Frame(self.win, bg="black", highlightthickness=0, bd=0)
        self.video_frame.pack(fill="both", expand=True)
        self.overlay = ctk.CTkLabel(self.video_frame, text="Bağlanıyor…", font=ui_font(13),
                                    text_color=C["muted"], fg_color="transparent")
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")

        self._build_controls()
        self._bind_keys()
        self.win.update_idletasks()
        bring_to_front(self.win)
        self.win.after(50, self.start)

    def _pencereyi_hazirla(self, master, mevcut):
        """Verilen pencereyi temizleyip yeniden kullanır; yoksa yenisini açar."""
        kullanilabilir = False
        try:
            kullanilabilir = mevcut is not None and bool(mevcut.winfo_exists())
        except Exception:
            kullanilabilir = False
        if not kullanilabilir:
            win = ctk.CTkToplevel(master)
            win.geometry("1160x700")
            return win
        win = mevcut
        try:
            for dizi in win.bind():
                try:
                    win.unbind(dizi)
                except Exception:
                    pass
            for cocuk in list(win.winfo_children()):
                try:
                    cocuk.destroy()
                except Exception:
                    pass
            win.configure(fg_color="#000000")
            # Önizleme penceresi dar; video için genişlet ama konumu koru.
            win.update_idletasks()
            x, y = win.winfo_rootx(), win.winfo_rooty()
            ekran_w, ekran_h = win.winfo_screenwidth(), win.winfo_screenheight()
            en, boy = 1160, 700
            x = max(0, min(x, ekran_w - en - 20)) if ekran_w > en + 40 else 0
            y = max(0, min(y, ekran_h - boy - 60)) if ekran_h > boy + 80 else 0
            win.geometry(f"{en}x{boy}+{int(x)}+{int(y)}")
            win.deiconify()
        except Exception as e:
            print(f"Pencere devralınamadı, yenisi açılıyor: {e}")
            return ctk.CTkToplevel(master)
        return win

    def _menu(self, parent, values, command, width=132):
        return ctk.CTkOptionMenu(
            parent, width=width, height=32, font=ui_font(11), values=values,
            fg_color=C["panel2"], button_color=C["line"], button_hover_color=C["accent"],
            text_color=C["text"], dropdown_fg_color=C["panel2"],
            dropdown_text_color=C["text"], dropdown_hover_color=C["line"],
            dropdown_font=ui_font(11), command=command)

    def _build_controls(self):
        bar = ctk.CTkFrame(self.win, height=168, corner_radius=0, fg_color=C["panel"])
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.bar = bar

        top = ctk.CTkFrame(bar, fg_color="transparent", height=26)
        top.pack(fill="x", padx=16, pady=(8, 0))
        top.pack_propagate(False)

        if self.is_live:
            self.live_badge = ctk.CTkLabel(top, text="● CANLI", font=ui_font(11, "bold"),
                                           text_color=C["live"])
            self.live_badge.pack(side="left")
            self.seek = None
            self.pos_label = ctk.CTkLabel(top, text="00:00", font=mono_font(11),
                                          text_color=C["text"], anchor="w")
            self.pos_label.pack(side="left", padx=(12, 0))
            self.dur_label = ctk.CTkLabel(top, text="", font=mono_font(11),
                                          text_color=C["muted"], anchor="e")
            self.dur_label.pack(side="right")
        else:
            self.pos_label = ctk.CTkLabel(top, text="00:00", width=92, anchor="w",
                                          font=mono_font(12), text_color=C["text"])
            self.pos_label.pack(side="left")
            self.seek = ctk.CTkSlider(top, from_=0, to=1000, height=16,
                                      button_color=C["accent"], button_hover_color=C["accent_dk"],
                                      progress_color=C["accent"], fg_color=C["line"],
                                      command=self.on_seek_move)
            self.seek.set(0)
            self.seek.pack(side="left", fill="x", expand=True, padx=10)
            self.dur_label = ctk.CTkLabel(top, text="--:--", width=92, anchor="e",
                                          font=mono_font(12), text_color=C["muted"])
            self.dur_label.pack(side="left")
            self.dur_label.bind("<Button-1>", lambda e: self.toggle_remaining())
            try:
                self.seek.bind("<ButtonRelease-1>", self._on_seek_release, add="+")
            except Exception:
                pass

        info = ctk.CTkFrame(bar, fg_color="transparent", height=18)
        info.pack(fill="x", padx=16, pady=(2, 0))
        info.pack_propagate(False)
        self.stats_label = ctk.CTkLabel(info, text="", font=ui_font(10),
                                        text_color=C["muted"], anchor="w")
        self.stats_label.pack(side="left")
        self.state_label = ctk.CTkLabel(info, text="Bağlanıyor…", font=ui_font(10),
                                        text_color=C["muted"], anchor="e")
        self.state_label.pack(side="right")
        self.time_label = self.pos_label  # geriye dönük uyumluluk

        parca = ctk.CTkFrame(bar, fg_color="transparent", height=52)
        parca.pack(fill="x", padx=16, pady=(6, 0))
        parca.pack_propagate(False)
        self.parca_satiri = parca

        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 10))

        self.btn_play = ctk.CTkButton(row, text="❚❚", width=42, height=42, corner_radius=21,
                                      fg_color=C["accent"], hover_color=C["accent_dk"],
                                      text_color=C["bg"], font=ui_font(14, "bold"),
                                      command=self.play_pause)
        self.btn_play.pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="■", width=34, height=34, corner_radius=17,
                      fg_color=C["panel2"], hover_color=C["line"], text_color=C["text"],
                      font=ui_font(12), command=self.stop).pack(side="left", padx=4)
        self.btn_mute = ctk.CTkButton(row, text="🔊", width=34, height=34, corner_radius=17,
                                      fg_color=C["panel2"], hover_color=C["line"],
                                      text_color=C["text"], font=ui_font(12),
                                      command=self.toggle_mute)
        self.btn_mute.pack(side="left", padx=(10, 4))
        self.vol_slider = ctk.CTkSlider(row, from_=0, to=100, width=86, height=14,
                                        button_color=C["accent"], button_hover_color=C["accent_dk"],
                                        progress_color=C["accent"], fg_color=C["line"],
                                        command=self.set_volume)
        self.vol_slider.set(self.volume)
        self.vol_slider.pack(side="left", padx=(0, 14))
        self.btn_fs = ctk.CTkButton(row, text="Tam ekran", width=88, height=32,
                                    fg_color=C["panel2"], hover_color=C["line"],
                                    text_color=C["text"], font=ui_font(11),
                                    command=self.toggle_fullscreen)
        self.btn_fs.pack(side="right")
        self.btn_video = ctk.CTkButton(row, text="⚙  Görüntü", width=104, height=32,
                                       fg_color=C["panel2"], hover_color=C["line"],
                                       text_color=C["text"], font=ui_font(11),
                                       command=self.goruntu_ayarlari)
        self.btn_video.pack(side="right", padx=6)

        # --- parça seçicileri kendi satırında: dar pencerede taşmıyor ---
        def secici(ana, etiket, menu_degerleri, komut, baslangic, genislik=150):
            kutu = ctk.CTkFrame(ana, fg_color="transparent")
            kutu.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ctk.CTkLabel(kutu, text=etiket, font=ui_font(10, "bold"),
                         text_color=C["muted"], anchor="w").pack(fill="x")
            menu = self._menu(kutu, menu_degerleri, komut, width=genislik)
            menu.set(baslangic)
            menu.pack(fill="x")
            return menu

        self.quality_menu = secici(parca, "KALİTE", [name for _, name in QUALITIES],
                                   self.on_quality_change,
                                   QUALITY_NAMES.get(self.quality, "Otomatik"), 104)
        self.video_menu = secici(parca, "GÖRÜNTÜ AKIŞI", ["Görüntü yok"],
                                 self.on_video_change, "Görüntü yok", 140)
        self.video_menu.configure(state="disabled")
        self.audio_menu = secici(parca, "SES", ["Ses yok"], self.on_audio_change,
                                 "Ses yok", 150)
        self.sub_menu = secici(parca, "ALTYAZI", [self.SUB_OFF, self.SUB_FILE],
                               self.on_subtitle_change, self.SUB_OFF, 150)

    def _bind_keys(self):
        w = self.win
        w.bind("<space>", lambda e: self.play_pause())
        w.bind("<f>", lambda e: self.toggle_fullscreen())
        w.bind("<F11>", lambda e: self.toggle_fullscreen())
        w.bind("<Escape>", lambda e: self.exit_fullscreen())
        w.bind("<m>", lambda e: self.toggle_mute())
        w.bind("<Left>", lambda e: self.nudge(-10000))
        w.bind("<Right>", lambda e: self.nudge(10000))
        w.bind("<Shift-Left>", lambda e: self.nudge(-60000))
        w.bind("<Shift-Right>", lambda e: self.nudge(60000))
        w.bind("<j>", lambda e: self.nudge(-5000))
        w.bind("<l>", lambda e: self.nudge(5000))
        w.bind("<k>", lambda e: self.play_pause())
        w.bind("<s>", lambda e: self.toggle_subtitle())
        w.bind("<a>", lambda e: self.dongu_ses())
        w.bind("<v>", lambda e: self.goruntu_ayarlari())
        w.bind("<z>", lambda e: self.altyazi_gecikme(-0.1))
        w.bind("<x>", lambda e: self.altyazi_gecikme(0.1))
        w.bind("<Control-Left>", lambda e: self.ses_gecikme(-0.1))
        w.bind("<Control-Right>", lambda e: self.ses_gecikme(0.1))
        w.bind("<Up>", lambda e: self.change_volume(5))
        w.bind("<Down>", lambda e: self.change_volume(-5))
        w.bind("<F1>", lambda e: self.kisayol_yardimi())
        w.bind("<question>", lambda e: self.kisayol_yardimi())
        w.bind("<Motion>", self._on_motion)
        self.video_frame.bind("<Double-Button-1>", lambda e: self.toggle_fullscreen())
        self.video_frame.bind("<Button-1>", lambda e: self.win.focus_set())

    KISAYOLLAR = [
        "Boşluk / K    Oynat – duraklat",
        "← →           10 sn geri / ileri",
        "Shift + ← →   1 dk geri / ileri",
        "J / L         5 sn geri / ileri",
        "↑ ↓           Ses seviyesi",
        "M             Sessiz",
        "S             Altyazıyı aç / kapat",
        "A             Ses parçasını değiştir",
        "Z / X         Altyazı gecikmesi −/+",
        "Ctrl + ← →    Ses gecikmesi −/+",
        "V             Görüntü ayarları",
        "F / F11       Tam ekran",
        "Esc           Tam ekrandan çık",
        "F1            Bu liste",
    ]

    def kisayol_yardimi(self):
        self._notice_until = time.time() + 9
        try:
            self.overlay.configure(
                text="KISAYOLLAR\n\n" + "\n".join(self.KISAYOLLAR),
                font=mono_font(11), justify="left")
            self.overlay.place(relx=0.5, rely=0.5, anchor="center")
            self.win.after(9200, self._yardimi_kapat)
        except Exception:
            pass

    def _yardimi_kapat(self):
        if self._closed:
            return
        try:
            self.overlay.configure(font=ui_font(13), justify="center")
            if time.time() >= self._notice_until:
                self.overlay.place_forget()
        except Exception:
            pass

    def notice(self, text, seconds=3):
        self._notice_until = time.time() + seconds
        self.overlay.configure(text=text)
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")

    # python-mpv'de mpv["ad"] OPSİYONU okur (options/ad), ÇALIŞMA ZAMANI ÖZELLİĞİNİ değil.
    # time-pos, duration, track-list, core-idle gibi değerler opsiyon olmadığı için
    # eski sözlük erişimi daima hata verip varsayılana düşüyordu. Doğrusu getattr/setattr.
    @staticmethod
    def _prop_name(name):
        return name.replace("-", "_")

    def _get(self, name, default=None):
        player = self.mpv
        if player is None:
            return default
        try:
            value = getattr(player, self._prop_name(name))
        except Exception:
            return default
        return default if value is None else value

    def _set(self, name, value):
        player = self.mpv
        if player is None:
            return False
        try:
            setattr(player, self._prop_name(name), value)
            return True
        except Exception:
            return False

    def _cmd(self, *args):
        if self.mpv is None:
            return False
        try:
            self.mpv.command(*args)
            return True
        except Exception:
            return False

    def _ensure_player(self):
        if self.mpv is not None:
            return True
        if mpv is None:
            self.overlay.configure(text=f"libmpv yüklenemedi: {MPV_IMPORT_ERROR or ''}")
            return False
        handle = self.video_frame.winfo_id()
        base = dict(
            wid=str(handle),
            vo="gpu",
            profile="fast",
            hwdec=("no" if self.settings.get("hw_accel") == "none" else "auto-safe"),
            osc="no",
            osd_level="0",
            border="no",
            input_default_bindings="no",
            input_vo_keyboard="yes",
            input_cursor="yes",
            cursor_autohide="1500",
            terminal="no",
            idle="yes",
            force_window="no",
            keep_open="no",
            ytdl="no",
            audio_client_name=APP_NAME,
            title=APP_NAME,
            msg_level="all=no",
        )
        if platform.system() == "Windows":
            base["gpu_context"] = "d3d11"
        soft = {k: v for k, v in base.items() if k not in ("gpu_context", "profile", "hwdec")}
        minimal = {k: v for k, v in soft.items() if k not in ("vo", "msg_level")}
        for attempt in (base, soft, minimal):
            try:
                self.mpv = mpv.MPV(**attempt)
                break
            except Exception as e:
                print(f"libmpv denemesi başarısız: {e}")
        if self.mpv is None:
            self.overlay.configure(text="Oynatıcı başlatılamadı (libmpv).")
            return False
        for event_name in ("end-file", "end_file"):
            try:
                self.mpv.event_callback(event_name)(self._on_end_file)
                break
            except Exception:
                continue
        self._register_input()
        self._parca_gozlemcileri()
        return True

    def _ui(self, fn, *args):
        if self._closed:
            return
        try:
            self.win.after(0, lambda: fn(*args))
        except Exception:
            pass

    def _register_input(self):
        actions = {
            "MBTN_LEFT_DBL": self.toggle_fullscreen,
            "SPACE": self.play_pause,
            "f": self.toggle_fullscreen,
            "F11": self.toggle_fullscreen,
            "ESC": self.exit_fullscreen,
            "m": self.toggle_mute,
            "LEFT": lambda: self.nudge(-10000),
            "RIGHT": lambda: self.nudge(10000),
            "Shift+LEFT": lambda: self.nudge(-60000),
            "Shift+RIGHT": lambda: self.nudge(60000),
            "j": lambda: self.nudge(-5000),
            "l": lambda: self.nudge(5000),
            "k": self.play_pause,
            "s": self.toggle_subtitle,
            "a": self.dongu_ses,
            "v": self.goruntu_ayarlari,
            "z": lambda: self.altyazi_gecikme(-0.1),
            "x": lambda: self.altyazi_gecikme(0.1),
            "UP": lambda: self.change_volume(5),
            "DOWN": lambda: self.change_volume(-5),
        }
        def make(action):
            def handler(state="d-", *_args):
                if str(state).startswith("u"):
                    return
                self._ui(action)
            return handler
        for keydef, action in actions.items():
            try:
                self.mpv.register_key_binding(keydef, make(action))
            except Exception as e:
                print(f"Kısayol bağlanamadı ({keydef}): {e}")
        try:
            self.mpv.observe_property("mouse-pos", self._on_mpv_mouse)
        except Exception:
            pass

    def _on_mpv_mouse(self, _name=None, _value=None):
        now = time.time()
        if now - self._last_mouse < 0.2:
            return
        self._last_mouse = now
        self._ui(self._on_motion)

    _END_EOF = 0
    _END_ERROR = 4

    def _on_end_file(self, event):
        try:
            data = getattr(event, "data", None)
            if data is None:
                data = event
            raw = getattr(data, "reason", None)
            if raw is None and isinstance(data, dict):
                raw = data.get("reason")
        except Exception:
            return
        if isinstance(raw, str):
            text = raw.lower()
            if "error" in text:
                self._end_error = True
            elif "eof" in text:
                self._ended = True
            return
        try:
            code = int(raw)
        except (TypeError, ValueError):
            return
        if code == self._END_ERROR:
            self._end_error = True
        elif code == self._END_EOF:
            self._ended = True

    def _apply_options(self):
        options, profile = build_mpv_options(self.settings, self.kind, self.quality,
                                             self.extra_buffer)
        if profile:
            self._cmd("apply-profile", profile)
        for key, value in options.items():
            self._set(key, value)

    def _state(self):
        if self._basarisiz or self._end_error:
            return "error"
        if self.mpv is None:
            return "buffering"
        if self._ended:
            return "ended"
        if self._get("pause", False):
            return "paused"
        if self._get("paused-for-cache", False):
            return "buffering"
        if self._get("idle-active", False):
            return "ended" if self._played_any else "buffering"
        if self._get("core-idle", True):
            return "buffering"
        return "playing"

    def start(self, resume_to=0):
        try:
            if not self._ensure_player():
                return
            self.url = build_url(self.source, self.quality, self.settings)
            self._end_error = False
            self._ended = False
            self._file_loaded = False
            self._acildi = False
            self._apply_options()
            self._set("pause", False)
            self._set("volume", self.volume)
            self._set("mute", bool(self.muted))
            if not self.is_live and resume_to > 0:
                self._set("start", f"+{max(0.0, resume_to / 1000.0):.3f}")
            else:
                self._set("start", "none")
            self._resume_to = 0
            self._duration_ms = 0
            self._position_ms = max(0, int(resume_to or 0))
            self._stats_cache = ""
            self._live_since = time.time()
            self._seek_active = 0
            if not self.is_live:
                self._update_time_labels(self._position_ms, 0)
            self._cmd("loadfile", self.url, "replace")
            self._last_state = None
            self._notice_until = 0
            self._opened_at = time.time()
            self._tracks_ready = False
            self._track_tries = 0
            self._audio_map = {}
            self._sub_map = {}
            self._video_map = {}
            self.btn_play.configure(text="❚❚")
            try:
                self.overlay.configure(text_color=C["muted"], font=ui_font(13))
            except Exception:
                pass
            if self._tick_after is None:
                self._tick()
        except Exception as e:
            self.overlay.configure(text=f"Başlatılamadı: {e}")

    def reload(self, keep_position=True, message=None):
        position = 0
        if keep_position and not self.is_live:
            position = self.position_ms()
        if message:
            self.notice(message, 4)
        self._cmd("stop")
        self.win.after(80, lambda: self.start(resume_to=position))

    @staticmethod
    def _to_ms(value):
        try:
            if value is None:
                return None
            ms = int(float(value) * 1000)
            return ms if ms >= 0 else None
        except Exception:
            return None

    def position_ms(self):
        for name in ("time-pos", "playback-time"):
            ms = self._to_ms(self._get(name))
            if ms is not None:
                self._position_ms = ms
                return ms
        # konum okunamadıysa yüzdeden türet
        if self._duration_ms > 0:
            try:
                pct = self._get("percent-pos")
                if pct is not None:
                    self._position_ms = int(self._duration_ms * float(pct) / 100.0)
            except Exception:
                pass
        return self._position_ms

    def duration_ms(self):
        ms = self._to_ms(self._get("duration")) or 0
        if ms <= 0:
            # bazı akışlarda duration boş gelir: kalan + geçen ile tahmin et
            remaining = self._to_ms(self._get("time-remaining"))
            current = self._to_ms(self._get("time-pos"))
            if remaining is not None and current is not None:
                ms = remaining + current
        if ms <= 0:
            ms = self._to_ms(self._get("demuxer-cache-time")) or 0
            if ms and self._position_ms and ms < self._position_ms:
                ms = 0
        if ms > 0:
            self._duration_ms = ms
        return self._duration_ms

    def toggle_remaining(self):
        self._show_remaining = not self._show_remaining
        self._update_time_labels(self._position_ms, self._duration_ms)

    def _seek_target_ms(self):
        if self._duration_ms <= 0:
            return None
        ratio = max(0.0, min(1.0, self._seek_pending / 1000.0))
        return int(self._duration_ms * ratio)

    @staticmethod
    def _fmt_pair(ms, length):
        """Süre 1 saati aşıyorsa konum da s:dd:ss biçiminde yazılır (etiket zıplamaz)."""
        if length >= 3_600_000:
            total = int(max(0, ms) // 1000)
            h, rem = divmod(total, 3600)
            mm, ss = divmod(rem, 60)
            return f"{h}:{mm:02d}:{ss:02d}"
        return fmt_time(ms)

    def _update_time_labels(self, current, length, seeking=False):
        if self.is_live:
            return
        current = max(0, int(current or 0))
        length = max(0, int(length or 0))
        if length > 0:
            current = min(current, length)
        cur_text = ("⟩ " if seeking else "") + self._fmt_pair(current, length)
        if self.pos_label.cget("text") != cur_text:
            self.pos_label.configure(
                text=cur_text, text_color=C["accent"] if seeking else C["text"])
        if length > 0:
            dur_text = ("-" + self._fmt_pair(length - current, length)) \
                if self._show_remaining else self._fmt_pair(length, length)
        else:
            dur_text = "--:--"
        if self.dur_label.cget("text") != dur_text:
            self.dur_label.configure(text=dur_text)

    def on_quality_change(self, label):
        code = QUALITY_CODES.get(label, "auto")
        if code == self.quality:
            return
        self.quality = code
        self._stalls = 0
        self._zincir_sifirla()
        self.reload(message=f"{label} kaliteye geçiliyor…")

    def play_pause(self):
        try:
            if self._basarisiz:
                self._zincir_sifirla()
                self.overlay.configure(text_color=C["muted"])
                self.notice("Yeniden deneniyor…", 3)
                self.start()
                return
            if self._state() in ("ended", "error"):
                self.start()
                return
            paused = not bool(self._get("pause", False))
            self._set("pause", paused)
            self.btn_play.configure(text="▶" if paused else "❚❚")
        except Exception as e:
            print(f"Duraklatma hatası: {e}")

    def stop(self):
        try:
            self._cmd("stop")
            self._played_any = False
            self.btn_play.configure(text="▶")
            if self.seek:
                self.seek.set(0)
            self._position_ms = 0
            self._stats_cache = ""
            self.stats_label.configure(text="")
            if not self.is_live:
                self._update_time_labels(0, self._duration_ms)
            self._opened_at = 0
            self._kopma_an = 0.0
            self._kopma_deneme = 0
            self.notice("Durduruldu", 600)
        except Exception as e:
            print(f"Durdurma hatası: {e}")

    def nudge(self, delta_ms):
        if self.is_live:
            return
        length = self._duration_ms
        if length <= 0:
            self._cmd("seek", delta_ms / 1000.0, "relative")
            return
        target = max(0, min(length - 1000, self._position_ms + delta_ms))
        secs = target / 1000.0
        if not self._cmd("seek", secs, "absolute+exact"):
            self._cmd("seek", secs, "absolute")
        self._position_ms = target
        if self.seek is not None:
            self.seek.set(max(0, min(1000, int(target / length * 1000))))
        self._update_time_labels(target, length)
        self._seek_active = time.time()

    def on_seek_move(self, value):
        self._seek_pending = float(value)
        self._seek_active = time.time()
        target = self._seek_target_ms()
        if target is not None:
            self._update_time_labels(target, self._duration_ms, seeking=True)
        if self._seek_after:
            try:
                self.win.after_cancel(self._seek_after)
            except Exception:
                pass
        self._seek_after = self.win.after(140, self._apply_seek)

    def _on_seek_release(self, _event=None):
        if self._seek_after:
            try:
                self.win.after_cancel(self._seek_after)
            except Exception:
                pass
        self._apply_seek()

    def _apply_seek(self):
        self._seek_after = None
        target = self._seek_target_ms()
        if target is None:
            # süre bilinmiyorsa yüzde ile ara
            self._cmd("seek", self._seek_pending / 10.0, "absolute-percent")
        else:
            secs = target / 1000.0
            if not self._cmd("seek", secs, "absolute+exact"):
                self._cmd("seek", secs, "absolute")
            self._position_ms = target
            self._update_time_labels(target, self._duration_ms)
        self._seek_active = time.time()

    def set_volume(self, value):
        self.volume = int(value)
        self.muted = self.volume == 0
        self._set("volume", self.volume)
        self.btn_mute.configure(text="🔇" if self.muted else "🔊")

    def change_volume(self, delta):
        new = max(0, min(100, self.volume + delta))
        self.vol_slider.set(new)
        self.set_volume(new)

    def toggle_mute(self):
        if self.muted:
            restore = self.volume or 80
            self.vol_slider.set(restore)
            self.set_volume(restore)
        else:
            last = self.volume
            self.vol_slider.set(0)
            self.set_volume(0)
            self.volume = last
            self.muted = True
            self.btn_mute.configure(text="🔇")

    # ---------------------- PARÇA YÖNETİMİ ----------------------
    def _parca_listesi(self):
        """mpv track-list'i normalize eder."""
        ham = self._get("track-list") or []
        if isinstance(ham, dict):          # bazı sürümler sözlük döndürebiliyor
            ham = list(ham.values())
        sonuc = []
        for entry in ham:
            if not isinstance(entry, dict):
                continue
            try:
                kimlik = int(entry.get("id"))
            except (TypeError, ValueError):
                continue
            sonuc.append((entry.get("type"), kimlik, entry))
        return sonuc

    def _parcalari_topla(self, tur):
        """{etiket: id} sözlüğü; etiketler benzersizleştirilir."""
        esleme = {}
        sira = 0
        for parca_turu, kimlik, entry in self._parca_listesi():
            if parca_turu != tur:
                continue
            sira += 1
            etiket = parca_etiketi(entry, tur, sira)
            temel, sayac = etiket, 2
            while etiket in esleme and esleme[etiket] != kimlik:
                etiket = f"{temel} ({sayac})"
                sayac += 1
            esleme[etiket] = kimlik
        return esleme

    def _menuyu_tazele(self, menu, degerler, secili_etiket, bos_metin):
        """CTkOptionMenu'yu güvenli biçimde günceller."""
        try:
            menu.configure(values=degerler or [bos_metin])
            menu.set(secili_etiket or (degerler[0] if degerler else bos_metin))
        except Exception:
            pass

    def refresh_tracks(self, _ad=None, _deger=None):
        """Parça menülerini mpv'nin gerçek durumuna göre yeniden kurar.

        Eskiden yalnızca açılıştan sonra ~2 saniye boyunca deneniyordu; HLS
        akışlarında ses/altyazı parçaları daha geç göründüğü için menüler boş
        kalıyordu. Artık track-list özelliği değiştikçe çağrılıyor.
        """
        if self._closed or self.mpv is None:
            return False
        try:
            sesler = self._parcalari_topla("audio")
            altyazilar = self._parcalari_topla("sub")
            goruntuler = self._parcalari_topla("video")
        except Exception as e:
            print(f"Parça listesi okunamadı: {e}")
            return False

        self._audio_map = sesler
        self._sub_map = altyazilar
        self._video_map = goruntuler

        # --- ses ---
        aid = _parca_id(self._get("aid"))
        ses_etiketleri = list(sesler)
        secili = next((e for e, t in sesler.items() if t == aid), None)
        if ses_etiketleri:
            self._menuyu_tazele(self.audio_menu, ses_etiketleri + [self.TRACK_OFF],
                                secili or (self.TRACK_OFF if aid is None else ses_etiketleri[0]),
                                "Yok")
        else:
            self._menuyu_tazele(self.audio_menu, [], None, "Ses yok")

        # --- altyazı ---
        sid = _parca_id(self._get("sid"))
        alt_etiketleri = list(altyazilar)
        secili_alt = next((e for e, t in altyazilar.items() if t == sid), None)
        self._menuyu_tazele(
            self.sub_menu, [self.SUB_OFF] + alt_etiketleri + [self.SUB_FILE],
            secili_alt or self.SUB_OFF, self.SUB_OFF)

        # --- görüntü (birden fazla video parçası varsa anlamlı) ---
        if hasattr(self, "video_menu"):
            vid = _parca_id(self._get("vid"))
            gor_etiketleri = list(goruntuler)
            secili_gor = next((e for e, t in goruntuler.items() if t == vid), None)
            self._menuyu_tazele(self.video_menu, gor_etiketleri,
                                secili_gor or (gor_etiketleri[0] if gor_etiketleri else None),
                                "Görüntü yok")
            try:
                # Tek görüntü parçası varsa menüyü kullanılamaz yap (kafa karıştırmasın)
                self.video_menu.configure(state="normal" if len(gor_etiketleri) > 1 else "disabled")
            except Exception:
                pass
        self._tracks_ready = bool(sesler or altyazilar)
        return self._tracks_ready

    def _parca_gozlemcileri(self):
        """track-list ve seçili parça özelliklerini izle (kutup yerine olay)."""
        if self.mpv is None:
            return
        def yap(ad):
            def geri(_n=None, _d=None):
                self._ui(self.refresh_tracks)
            return geri
        for ozellik in ("track-list", "aid", "sid", "vid"):
            try:
                self.mpv.observe_property(ozellik, yap(ozellik))
            except Exception as e:
                print(f"'{ozellik}' izlenemedi: {e}")

    def on_audio_change(self, label):
        if label in (self.TRACK_OFF, "Ses yok", "Yok"):
            self._set("aid", "no")
            self.notice("Ses kapatıldı", 2)
            return
        track_id = self._audio_map.get(label)
        if track_id is None:
            return
        if self._set("aid", track_id):
            self.notice(f"Ses: {label}", 2)
        else:
            self.notice("Ses parçası değiştirilemedi", 3)
            self._ui(self.refresh_tracks)

    def on_subtitle_change(self, label):
        if label == self.SUB_FILE:
            self.load_subtitle()
            return
        if label == self.SUB_OFF:
            self._set("sid", "no")
            self.notice("Altyazı kapalı", 2)
            return
        track_id = self._sub_map.get(label)
        if track_id is None:
            return
        if self._set("sid", track_id):
            self._set("sub-visibility", True)
            self.notice(f"Altyazı: {label}", 2)
        else:
            self.notice("Altyazı değiştirilemedi", 3)
            self._ui(self.refresh_tracks)

    def on_video_change(self, label):
        track_id = self._video_map.get(label)
        if track_id is None:
            return
        if self._set("vid", track_id):
            self.notice(f"Görüntü: {label}", 2)

    def toggle_subtitle(self):
        """S kısayolu: altyazıyı aç/kapat (son seçilen parçaya döner)."""
        sid = _parca_id(self._get("sid"))
        if sid is not None:
            self._son_sid = sid
            self._set("sid", "no")
            self.notice("Altyazı kapalı", 2)
        else:
            hedef = getattr(self, "_son_sid", None)
            if hedef is None and self._sub_map:
                hedef = list(self._sub_map.values())[0]
            if hedef is None:
                self.notice("Altyazı parçası yok", 2)
                return
            self._set("sid", hedef)
            self._set("sub-visibility", True)
            self.notice("Altyazı açık", 2)
        self._ui(self.refresh_tracks)

    def dongu_ses(self):
        """A kısayolu: ses parçaları arasında sırayla geç."""
        kimlikler = list(self._audio_map.values())
        if len(kimlikler) < 2:
            self.notice("Tek ses parçası var", 2)
            return
        simdiki = _parca_id(self._get("aid"))
        try:
            sonraki = kimlikler[(kimlikler.index(simdiki) + 1) % len(kimlikler)]
        except ValueError:
            sonraki = kimlikler[0]
        self._set("aid", sonraki)
        etiket = next((e for e, t in self._audio_map.items() if t == sonraki), "")
        self.notice(f"Ses: {etiket}", 2)

    def load_subtitle(self):
        path = filedialog.askopenfilename(
            parent=self.win, title="Altyazı dosyası seç",
            filetypes=[("Altyazı dosyaları", "*.srt *.ass *.ssa *.vtt *.sub *.idx"),
                       ("Tümü", "*.*")])
        if not path:
            self._ui(self.refresh_tracks)
            return
        if self._cmd("sub-add", path, "select"):
            self._set("sub-visibility", True)
            self.notice(f"Altyazı yüklendi: {os.path.basename(path)}", 3)
            self.win.after(400, self.refresh_tracks)
        else:
            self._ui(self.refresh_tracks)
            messagebox.showerror("Altyazı", "Altyazı dosyası yüklenemedi.\n\n"
                                            f"{path}", parent=self.win)

    # ---------------------- SENKRON / GÖRÜNTÜ ----------------------
    def altyazi_gecikme(self, delta):
        try:
            simdi = float(self._get("sub-delay") or 0.0)
        except (TypeError, ValueError):
            simdi = 0.0
        yeni = round(simdi + delta, 2)
        self._set("sub-delay", yeni)
        self.notice(f"Altyazı gecikmesi: {yeni:+.2f} sn", 2)

    def ses_gecikme(self, delta):
        try:
            simdi = float(self._get("audio-delay") or 0.0)
        except (TypeError, ValueError):
            simdi = 0.0
        yeni = round(simdi + delta, 2)
        self._set("audio-delay", yeni)
        self.notice(f"Ses gecikmesi: {yeni:+.2f} sn", 2)

    def goruntu_ayarlari(self):
        if getattr(self, "_goruntu_penceresi", None) is not None:
            try:
                if self._goruntu_penceresi.win.winfo_exists():
                    bring_to_front(self._goruntu_penceresi.win, tries=2)
                    return
            except Exception:
                pass
        self._goruntu_penceresi = VideoSettingsWindow(self)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.win.attributes("-fullscreen", self.fullscreen)
        self.btn_fs.configure(text="Küçült" if self.fullscreen else "Tam ekran")
        if self.fullscreen:
            self._schedule_hide()
        else:
            self._show_controls()

    def exit_fullscreen(self):
        if self.fullscreen:
            self.toggle_fullscreen()
        else:
            self.close()

    def _on_motion(self, _event=None):
        if self.fullscreen:
            self._show_controls()
            self._schedule_hide()

    def _show_controls(self):
        if not self.controls_visible:
            self.bar.pack(fill="x", side="bottom")
            self.controls_visible = True

    def _schedule_hide(self):
        if self._hide_after:
            self.win.after_cancel(self._hide_after)
        self._hide_after = self.win.after(2500, self._hide_controls)

    def _hide_controls(self):
        self._hide_after = None
        if self.fullscreen and self.controls_visible:
            self.bar.pack_forget()
            self.controls_visible = False

    def _read_stats(self):
        parts = []
        try:
            width = self._get("dwidth") or self._get("width")
            height = self._get("dheight") or self._get("height")
            try:
                if width and height:
                    parts.append(f"{int(width)}×{int(height)}")
            except Exception:
                pass
            fps = self._get("estimated-vf-fps") or self._get("container-fps")
            try:
                if fps and float(fps) > 0:
                    parts.append(f"{float(fps):.0f} fps")
            except Exception:
                pass
            codec = self._get("video-codec") or self._get("video-format")
            if codec:
                parts.append(str(codec).upper()[:12])
            total = 0.0
            for name in ("video-bitrate", "audio-bitrate"):
                try:
                    total += float(self._get(name) or 0)
                except Exception:
                    pass
            if total > 0:
                parts.append(f"▼ {total / 1_000_000.0:.1f} Mb/s")
            cache = self._get("demuxer-cache-duration")
            try:
                if cache is not None:
                    parts.append(f"tampon {float(cache):.1f} sn")
            except Exception:
                pass
            dropped = 0
            for name in ("frame-drop-count", "decoder-frame-drop-count"):
                try:
                    dropped += int(self._get(name) or 0)
                except Exception:
                    pass
            if dropped:
                parts.append(f"{dropped} kare atlandı")
            hw = self._get("hwdec-current")
            if hw and str(hw) not in ("no", "none"):
                parts.append(f"donanım: {hw}")
            if self.extra_buffer:
                parts.append(f"ön yükleme +{self.extra_buffer // 1000} sn")
        except Exception:
            pass
        return "  ·  ".join(parts)

    STATE_TEXTS = {
        "playing": "Oynatılıyor",
        "paused": "Duraklatıldı",
        "buffering": "Arabelleğe alınıyor…",
        "ended": "Bitti",
        "error": "Hata",
    }

    def _update_state_label(self, state):
        text = self.STATE_TEXTS.get(state, "")
        if self._basarisiz:
            text = "Açılamadı"
        elif self.is_live and state == "playing":
            text = "Canlı yayın"
        color = C["live"] if (state == "error" or self._basarisiz) else C["muted"]
        try:
            if self.state_label.cget("text") != text:
                self.state_label.configure(text=text, text_color=color)
        except Exception:
            pass

    def _update_live_labels(self, state):
        elapsed = self._to_ms(self._get("time-pos"))
        if elapsed is None:
            if self._live_since and state == "playing":
                elapsed = int((time.time() - self._live_since) * 1000)
            else:
                elapsed = 0
        text = f"izleme {fmt_time(elapsed)}"
        try:
            if self.pos_label.cget("text") != text:
                self.pos_label.configure(text=text)
            clock = time.strftime("%H:%M:%S")
            if self.dur_label.cget("text") != clock:
                self.dur_label.configure(text=clock)
        except Exception:
            pass

    def _handle_stall(self):
        now = time.time()
        if now - self._stall_since > 90:
            self._stalls = 0
            self._stall_since = now
        self._stalls += 1
        if self._stalls < 3 or not self.settings.get("auto_downgrade", True):
            return
        self._stalls = 0
        self._stall_since = now
        if self.is_live and self._kalite_dusur():
            self.reload(keep_position=False,
                        message=f"Bağlantı zayıf — {QUALITY_NAMES[self.quality].lower()} "
                                "kaliteye geçiliyor")
        elif self._tampon_arttir(3000):
            self.reload(message="Bağlantı zayıf — daha fazla ön yükleme yapılıyor")

    # ---------------------- AÇILMAYAN YAYIN ----------------------
    def _uzanti_adaylari(self):
        """Xtream VOD/dizi bağlantılarında en sık hata kaynağı yanlış uzantıdır."""
        ilk = str(self.source.get("ext") or "").lower()
        tumu = ["mp4", "mkv", "avi", "ts", "m3u8"] if self.kind == "vod" \
            else ["mkv", "mp4", "avi", "ts"]
        return [u for u in tumu if u != ilk]

    def _protokol_ayarla(self, protokol):
        self.settings["live_protocol"] = protokol
        return True

    def _uzanti_ayarla(self, uzanti):
        self.source["ext"] = uzanti
        return True

    def _tampon_arttir(self, miktar=4000):
        if self.extra_buffer >= 12000:
            return False
        self.extra_buffer = min(self.extra_buffer + miktar, 12000)
        return True

    def _kalite_dusur(self):
        simdiki = self.quality if self.quality in QUALITY_ORDER else "high"
        try:
            sonraki = QUALITY_ORDER[QUALITY_ORDER.index(simdiki) + 1]
        except (ValueError, IndexError):
            return False
        self.quality = sonraki
        try:
            self.quality_menu.set(QUALITY_NAMES[sonraki])
        except Exception:
            pass
        return True

    def _stratejileri_kur(self):
        """Sırayla denenecek, SINIRLI bir kurtarma listesi.

        Eskiden tek bir yedek deneme vardı; o da tükenince izleyiciye sonsuza
        kadar 'alternatif deneniyor' yazıyordu. Artık liste bitince net bir
        hata ekranı gösterilip döngü durduruluyor.
        """
        stratejiler = []
        if self.is_live:
            simdiki_hls = str(self.url or "").endswith(".m3u8")
            once, sonra = ("ts", "hls") if simdiki_hls else ("hls", "ts")
            stratejiler.append((f"{once.upper()} biçimi",
                                lambda p=once: self._protokol_ayarla(p)))
            stratejiler.append(("daha fazla ön yükleme",
                                lambda: self._tampon_arttir(4000)))
            stratejiler.append((f"{sonra.upper()} biçimi + tampon",
                                lambda p=sonra: (self._protokol_ayarla(p)
                                                 and self._tampon_arttir(4000))))
            stratejiler.append(("düşük kalite", self._kalite_dusur))
        else:
            for uzanti in self._uzanti_adaylari()[:3]:
                stratejiler.append((f".{uzanti} uzantısı",
                                    lambda u=uzanti: self._uzanti_ayarla(u)))
            stratejiler.append(("daha fazla ön yükleme",
                                lambda: self._tampon_arttir(4000)))
        self._stratejiler = stratejiler
        self._deneme = 0
        self._denenenler = []

    def _zincir_sifirla(self):
        """Kullanıcı elle tekrar denediğinde kurtarma listesini başa al."""
        self._basarisiz = False
        self._fallback_tried = False
        self._stratejiler = []
        self._deneme = 0
        self._denenenler = []
        self._son_deneme_an = 0.0
        self._kopma_an = 0.0
        self._kopma_deneme = 0
        self._son_kopma_deneme = 0.0

    def _watchdog(self, state):
        if state in ("playing", "paused"):
            # "paused" = kullanıcı duraklattı. Eskiden bu durum "açılmadı"
            # sayılıp yayın yeniden yükleniyor, duraklatma hemen bozuluyordu.
            return
        if self._basarisiz or self._opened_at == 0:
            return
        if self._acildi or self._kopma_an:
            # Yayın açılmıştı, sonradan koptu: biçim/kalite değiştirmeden
            # aynı yayına yeniden bağlan.
            self._kopma_kurtar(state)
            return
        bekleyen = time.time() - self._opened_at
        taninan = self._acilma_suresi()
        if bekleyen < taninan:
            # Süre dolmadan alternatif denenmez. Hata gelse bile bekleriz:
            # sunucu ilk saniyelerde hata döndürüp sonra akışa başlayabiliyor,
            # ayrıca hızlı ardışık bağlantılar sağlayıcıyı kilitliyor.
            if state == "error":
                kalan = max(0, int(taninan - bekleyen))
                self._geri_sayim_goster(kalan)
            return
        if time.time() - self._son_deneme_an < taninan:
            return
        sebep = "Yayın açılmadı" if state == "error" else "Yayın geç açılıyor"
        self._try_fallback(sebep)

    # ---------------------- KOPMA SONRASI YENİDEN BAĞLANMA ----------------------
    _KOPMA_AZAMI = 8   # internet varken art arda başarısız yeniden bağlanma sınırı

    def _sunucu_adresi(self):
        try:
            parca = urlsplit(self.url or "")
            host = parca.hostname
            port = parca.port or (443 if parca.scheme == "https" else 80)
            return host, port
        except Exception:
            return None, None

    def _ag_yokla(self):
        """İnternet/sunucu erişimini arka planda hızlıca dener (arayüzü kilitlemez)."""
        if self._ag_yoklaniyor:
            return
        if time.time() - self._ag_son_yoklama < 1.5:
            return
        host, port = self._sunucu_adresi()
        if not host:
            self._ag_sonuc = (time.time(), True)
            return
        self._ag_yoklaniyor = True
        self._ag_son_yoklama = time.time()

        def is_():
            ok = False
            try:
                baglanti = socket.create_connection((host, port), timeout=3)
                baglanti.close()
                ok = True
            except Exception:
                ok = False
            self._ag_sonuc = (time.time(), ok)
            self._ag_yoklaniyor = False

        threading.Thread(target=is_, daemon=True).start()

    def _gercek_son_mu(self, state):
        """VOD gerçekten bittiyse (sona yakın) yeniden bağlanma yapılmaz."""
        if self.is_live or state != "ended":
            return False
        uzunluk = self._duration_ms
        return uzunluk > 0 and self._position_ms >= uzunluk - 20000

    def _kopma_kurtar(self, state):
        now = time.time()
        if self._gercek_son_mu(state):
            return
        if not self._kopma_an:
            self._kopma_an = now
            self._kopma_deneme = 0
            self._son_kopma_deneme = 0.0
            self._ag_sonuc = None
        gecen = now - self._kopma_an
        # Kısa takılmaları mpv kendi tamponuyla atlatır; hata/bitişte hemen davran.
        esik = 1.5 if state in ("error", "ended") else (6 if self.is_live else 10)
        if gecen < esik:
            return
        if self._son_kopma_deneme:
            bekleme = min(20, 6 + 3 * (self._kopma_deneme - 1))
            if now - self._son_kopma_deneme < bekleme and state not in ("error", "ended"):
                return
            if now - self._son_kopma_deneme < 2:
                return
        sonuc = self._ag_sonuc
        if sonuc is None or now - sonuc[0] > 2.5:
            self._ag_yokla()
            return
        if not sonuc[1]:
            # İnternet yok: deneme hakkı harcamadan bekle, gelir gelmez bağlan.
            self._ag_sonuc = None
            self.notice("İnternet bağlantısı yok — bağlantı bekleniyor…", 4)
            return
        if self._kopma_deneme >= self._KOPMA_AZAMI:
            self._denenenler = [f"{self._kopma_deneme} kez yeniden bağlanma"]
            self._kopma_an = 0.0
            self._yayin_basarisiz()
            return
        self._kopma_deneme += 1
        self._son_kopma_deneme = now
        self._ag_sonuc = None
        self.reload(keep_position=not self.is_live,
                    message=f"Bağlantı koptu — yeniden bağlanılıyor… ({self._kopma_deneme})")

    def _acilma_suresi(self):
        try:
            return max(3, min(60, int(self.settings.get("open_timeout", 10))))
        except (TypeError, ValueError):
            return 10

    def _geri_sayim_goster(self, kalan):
        """Bekleme sırasında kullanıcıya ne olduğunu göster."""
        if kalan == getattr(self, "_son_geri_sayim", None):
            return
        self._son_geri_sayim = kalan
        toplam = len(self._stratejiler) or len(self._uzanti_adaylari())
        self.notice(f"Yayın yanıt vermiyor — {kalan} sn sonra alternatif denenecek"
                    + (f" ({toplam} seçenek)" if toplam else ""), 3)

    def _try_fallback(self, sebep):
        if not self._stratejiler:
            self._stratejileri_kur()
        while self._deneme < len(self._stratejiler):
            ad, uygula = self._stratejiler[self._deneme]
            self._deneme += 1
            try:
                basarili = bool(uygula())
            except Exception as e:
                print(f"Kurtarma adımı uygulanamadı ({ad}): {e}")
                basarili = False
            if not basarili:
                continue                # uygulanamayan adımı atla, sıradakine geç
            self._fallback_tried = True
            self._son_deneme_an = time.time()
            self._denenenler.append(ad)
            kalan = len(self._stratejiler) - self._deneme
            ek = f" ({kalan} seçenek kaldı)" if kalan else " (son deneme)"
            self.reload(keep_position=not self.is_live,
                        message=f"{sebep} — {ad} deneniyor…{ek}")
            return True
        self._yayin_basarisiz()
        return False

    def _yayin_basarisiz(self):
        """Kurtarma listesi tükendi: döngüyü durdur, net bilgi ver."""
        self._basarisiz = True
        self._opened_at = 0
        self._cmd("stop")
        denenen = ", ".join(self._denenenler) if self._denenenler else "—"
        metin = ("Yayın açılamadı.\n\n"
                 f"Denenenler: {denenen}\n\n"
                 "Bu içerik sağlayıcıda olmayabilir veya bağlantınız\n"
                 "yayını taşıyamıyor olabilir.\n\n"
                 "▶ düğmesine basarak yeniden deneyebilir,\n"
                 "kaliteyi değiştirerek başka bir akış isteyebilirsiniz.")
        self._notice_until = time.time() + 3600
        try:
            self.overlay.configure(text=metin, font=ui_font(12), justify="center",
                                   text_color=C["live"])
            self.overlay.place(relx=0.5, rely=0.5, anchor="center")
            self.btn_play.configure(text="↻")
            self.state_label.configure(text="Açılamadı", text_color=C["live"])
        except Exception:
            pass

    def _tick(self):
        if self._closed:
            return
        try:
            state = self._state()
            if state != self._last_state:
                previous = self._last_state
                self._last_state = state
                if state == "playing":
                    self._played_any = True
                    self._acildi = True
                    if self._kopma_an:
                        self._kopma_an = 0.0
                        self._kopma_deneme = 0
                        self._son_kopma_deneme = 0.0
                        self.notice("Bağlantı geri geldi", 2)
                    if time.time() > self._notice_until:
                        self.overlay.place_forget()
                    self.btn_play.configure(text="❚❚")
                elif state == "buffering":
                    if time.time() > self._notice_until:
                        self.overlay.configure(text="Bağlanıyor…")
                        self.overlay.place(relx=0.5, rely=0.5, anchor="center")
                    if previous == "playing":
                        self._handle_stall()
                elif state == "paused":
                    self.btn_play.configure(text="▶")
                elif state == "error" and not self._basarisiz:
                    if self._acildi or self._kopma_an:
                        self.notice("Bağlantı koptu — yeniden bağlanılıyor…", 5)
                    else:
                        self.notice("Yayın açılamadı, alternatif deneniyor…", 5)
                elif state == "ended":
                    self.btn_play.configure(text="▶")
            if time.time() > self._notice_until and state == "playing":
                self.overlay.place_forget()
            # Gözlemciler asıl kaynağımız; bu yalnızca yedek. Parça bulunana
            # kadar ~2 sn'de bir, bulunduktan sonra ~10 sn'de bir tazelenir.
            if state in ("playing", "paused"):
                self._track_tries += 1
                aralik = 40 if self._tracks_ready else 8
                if self._track_tries % aralik == 0:
                    self.refresh_tracks()
            self._watchdog(state)
            self._update_state_label(state)
            self._stats_skip = (self._stats_skip + 1) % 4
            if self._stats_skip == 0:
                stats = self._read_stats()
                if stats != self._stats_cache:
                    self._stats_cache = stats
                    self.stats_label.configure(text=stats)
            if self.is_live:
                self._update_live_labels(state)
            else:
                length = self.duration_ms()
                current = self.position_ms()
                dragging = (self._seek_after is not None
                            or (time.time() - self._seek_active) < 0.5)
                if not dragging:
                    if self.seek is not None and length > 0:
                        self.seek.set(max(0, min(1000, int(current / length * 1000))))
                    self._update_time_labels(current, length)
        except Exception:
            pass
        self._tick_after = self.win.after(250, self._tick)

    def close(self):
        if self._closed:
            return
        self._closed = True
        for handle in (self._tick_after, self._hide_after, self._seek_after):
            if handle:
                try:
                    self.win.after_cancel(handle)
                except Exception:
                    pass
        gp = getattr(self, "_goruntu_penceresi", None)
        if gp is not None:
            try:
                gp.kapat()
            except Exception:
                pass
        player, self.mpv = self.mpv, None
        if player is not None:
            def _shutdown():
                for action in ("stop", "terminate"):
                    try:
                        getattr(player, action)()
                    except Exception:
                        pass
            threading.Thread(target=_shutdown, daemon=True).start()
        try:
            self.win.destroy()
        except Exception:
            pass
        if self.on_close:
            self.on_close(self)

# ============================== GÖRÜNTÜ AYARLARI ==============================
class VideoSettingsWindow:
    """Oynatıcı için canlı görüntü/senkron ayarları.

    Değerler doğrudan mpv özelliklerine yazılır, anında etkili olur.
    """
    RENK_AYARLARI = [
        ("brightness", "Parlaklık", -100, 100, 0),
        ("contrast", "Kontrast", -100, 100, 0),
        ("saturation", "Doygunluk", -100, 100, 0),
        ("gamma", "Gama", -100, 100, 0),
        ("hue", "Ton", -100, 100, 0),
    ]
    ORANLAR = [("Otomatik", "-1"), ("16:9", "16:9"), ("4:3", "4:3"),
               ("21:9", "2.39"), ("1:1", "1")]
    KARISTIRMA = [("Kapalı", "no"), ("Açık", "yes")]

    def __init__(self, player):
        self.player = player
        self.win = ctk.CTkToplevel(player.win)
        self.win.title("Görüntü ve senkron — " + APP_NAME)
        self.win.geometry(self._konum())
        self.win.minsize(400, 480)
        self.win.configure(fg_color=C["bg"])
        self.win.protocol("WM_DELETE_WINDOW", self.kapat)
        simge_uygula(self.win)

        govde = ctk.CTkScrollableFrame(self.win, fg_color=C["bg"],
                                       scrollbar_button_color=C["line"],
                                       scrollbar_button_hover_color=C["muted"])
        govde.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        self._baslik(govde, "Renk")
        self.kaydiraclar = {}
        self.deger_etiketleri = {}
        for ozellik, ad, alt, ust, varsayilan in self.RENK_AYARLARI:
            self._renk_satiri(govde, ozellik, ad, alt, ust, varsayilan)

        self._baslik(govde, "Görüntü")
        self.oran_menu = self._menu(govde, "En-boy oranı",
                                    [ad for ad, _ in self.ORANLAR], self.oran_degisti)
        self.karistirma_menu = self._menu(govde, "Karıştırma giderme",
                                          [ad for ad, _ in self.KARISTIRMA],
                                          self.karistirma_degisti)
        self._kaydirac_satiri(govde, "zoom", "Yakınlaştırma", -1.0, 1.0, 0.0,
                              self.zoom_degisti, "{:+.2f}")

        self._baslik(govde, "Senkron")
        self._kaydirac_satiri(govde, "audio-delay", "Ses gecikmesi (sn)", -5.0, 5.0, 0.0,
                              self.ses_gecikmesi_degisti, "{:+.2f}")
        self._kaydirac_satiri(govde, "sub-delay", "Altyazı gecikmesi (sn)", -5.0, 5.0, 0.0,
                              self.altyazi_gecikmesi_degisti, "{:+.2f}")

        self._baslik(govde, "Altyazı görünümü")
        self._kaydirac_satiri(govde, "sub-scale", "Yazı boyutu", 0.3, 3.0, 1.0,
                              self.altyazi_boyutu_degisti, "{:.2f}x")
        self._kaydirac_satiri(govde, "sub-pos", "Dikey konum", 0, 150, 100,
                              self.altyazi_konumu_degisti, "{:.0f}")

        alt = ctk.CTkFrame(self.win, fg_color=C["bg"], height=52)
        alt.pack(fill="x", padx=10, pady=10)
        alt.pack_propagate(False)
        ctk.CTkButton(alt, text="Varsayılana döndür", height=36, corner_radius=8,
                      fg_color=C["panel2"], hover_color=C["line"], text_color=C["text"],
                      font=ui_font(11), command=self.sifirla).pack(side="left",
                                                                   fill="x", expand=True,
                                                                   padx=(0, 6))
        ctk.CTkButton(alt, text="Kapat", width=90, height=36, corner_radius=8,
                      fg_color=C["accent"], hover_color=C["accent_dk"],
                      text_color=C["bg"], font=ui_font(11, "bold"),
                      command=self.kapat).pack(side="left")

        self.oku()
        bring_to_front(self.win, tries=2)

    def _konum(self):
        """Oynatıcının sağına, ekran dışına taşmadan yerleş."""
        genislik, yukseklik = 430, 620
        try:
            ana = self.player.win
            ana.update_idletasks()
            ekran_w = ana.winfo_screenwidth()
            ekran_h = ana.winfo_screenheight()
            x = ana.winfo_rootx() + ana.winfo_width() + 12
            y = ana.winfo_rooty() + 40
            if x + genislik > ekran_w:
                x = max(0, ana.winfo_rootx() + ana.winfo_width() - genislik - 30)
            yukseklik = max(480, min(yukseklik, ekran_h - 100))
            y = max(0, min(y, ekran_h - yukseklik - 40))
            return f"{genislik}x{yukseklik}+{int(x)}+{int(y)}"
        except Exception:
            return f"{genislik}x{yukseklik}"

    # ---- kurulum yardımcıları ----
    def _baslik(self, ana, metin):
        ctk.CTkLabel(ana, text=metin.upper(), font=ui_font(10, "bold"),
                     text_color=C["muted"], anchor="w").pack(fill="x", padx=6,
                                                             pady=(14, 4))

    def _menu(self, ana, etiket, degerler, komut):
        satir = ctk.CTkFrame(ana, fg_color="transparent")
        satir.pack(fill="x", padx=6, pady=4)
        ctk.CTkLabel(satir, text=etiket, font=ui_font(11), text_color=C["text"],
                     width=150, anchor="w").pack(side="left")
        menu = ctk.CTkOptionMenu(
            satir, values=degerler, width=150, height=30, font=ui_font(11),
            fg_color=C["panel2"], button_color=C["line"], button_hover_color=C["accent"],
            text_color=C["text"], dropdown_fg_color=C["panel2"],
            dropdown_text_color=C["text"], dropdown_hover_color=C["line"],
            dropdown_font=ui_font(11), command=komut)
        menu.pack(side="right")
        return menu

    def _kaydirac_satiri(self, ana, anahtar, etiket, alt, ust, varsayilan, komut, bicim):
        satir = ctk.CTkFrame(ana, fg_color="transparent")
        satir.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(satir, text=etiket, font=ui_font(11), text_color=C["text"],
                     width=150, anchor="w").pack(side="left")
        deger = ctk.CTkLabel(satir, text=bicim.format(varsayilan), font=mono_font(10),
                             text_color=C["muted"], width=54, anchor="e")
        deger.pack(side="right")
        kaydirac = ctk.CTkSlider(satir, from_=alt, to=ust, height=16,
                                 button_color=C["accent"], button_hover_color=C["accent_dk"],
                                 progress_color=C["accent"], fg_color=C["line"],
                                 command=komut)
        kaydirac.pack(side="right", fill="x", expand=True, padx=8)
        self.kaydiraclar[anahtar] = kaydirac
        self.deger_etiketleri[anahtar] = (deger, bicim)
        return kaydirac

    def _renk_satiri(self, ana, ozellik, ad, alt, ust, varsayilan):
        def komut(deger, o=ozellik):
            self.renk_degisti(o, deger)
        self._kaydirac_satiri(ana, ozellik, ad, alt, ust, varsayilan, komut, "{:+.0f}")

    def _yaz(self, anahtar, deger):
        etiket_bilgi = self.deger_etiketleri.get(anahtar)
        if etiket_bilgi:
            etiket, bicim = etiket_bilgi
            try:
                etiket.configure(text=bicim.format(deger))
            except Exception:
                pass

    # ---- mpv'den oku ----
    def oku(self):
        p = self.player
        for ozellik, _ad, _a, _u, varsayilan in self.RENK_AYARLARI:
            try:
                deger = float(p._get(ozellik, varsayilan) or 0)
            except (TypeError, ValueError):
                deger = varsayilan
            self.kaydiraclar[ozellik].set(deger)
            self._yaz(ozellik, deger)
        for anahtar, ozellik, varsayilan in (("zoom", "video-zoom", 0.0),
                                             ("audio-delay", "audio-delay", 0.0),
                                             ("sub-delay", "sub-delay", 0.0),
                                             ("sub-scale", "sub-scale", 1.0),
                                             ("sub-pos", "sub-pos", 100)):
            try:
                deger = float(p._get(ozellik, varsayilan) or varsayilan)
            except (TypeError, ValueError):
                deger = varsayilan
            self.kaydiraclar[anahtar].set(deger)
            self._yaz(anahtar, deger)
        oran = str(p._get("video-aspect-override", "-1"))
        ad = next((a for a, d in self.ORANLAR if d == oran), "Otomatik")
        self.oran_menu.set(ad)
        kar = str(p._get("deinterlace", "no"))
        self.karistirma_menu.set("Açık" if kar in ("yes", "True", "1") else "Kapalı")

    # ---- olaylar ----
    def renk_degisti(self, ozellik, deger):
        self.player._set(ozellik, int(round(float(deger))))
        self._yaz(ozellik, float(deger))

    def zoom_degisti(self, deger):
        self.player._set("video-zoom", round(float(deger), 3))
        self._yaz("zoom", float(deger))

    def ses_gecikmesi_degisti(self, deger):
        self.player._set("audio-delay", round(float(deger), 2))
        self._yaz("audio-delay", float(deger))

    def altyazi_gecikmesi_degisti(self, deger):
        self.player._set("sub-delay", round(float(deger), 2))
        self._yaz("sub-delay", float(deger))

    def altyazi_boyutu_degisti(self, deger):
        self.player._set("sub-scale", round(float(deger), 2))
        self._yaz("sub-scale", float(deger))

    def altyazi_konumu_degisti(self, deger):
        self.player._set("sub-pos", int(round(float(deger))))
        self._yaz("sub-pos", float(deger))

    def oran_degisti(self, ad):
        deger = next((d for a, d in self.ORANLAR if a == ad), "-1")
        self.player._set("video-aspect-override", deger)

    def karistirma_degisti(self, ad):
        self.player._set("deinterlace", "yes" if ad == "Açık" else "no")

    def sifirla(self):
        p = self.player
        for ozellik, _ad, _a, _u, varsayilan in self.RENK_AYARLARI:
            p._set(ozellik, varsayilan)
        p._set("video-zoom", 0.0)
        p._set("audio-delay", 0.0)
        p._set("sub-delay", 0.0)
        p._set("sub-scale", 1.0)
        p._set("sub-pos", 100)
        p._set("video-aspect-override", "-1")
        p._set("deinterlace", "no")
        self.oku()
        p.notice("Görüntü ayarları sıfırlandı", 2)

    def kapat(self):
        try:
            self.win.destroy()
        except Exception:
            pass
        self.player._goruntu_penceresi = None

# ============================== VERİ KATMANI ==============================
def normalize(kind, raw):
    if kind == "series":
        return {
            "kind": "series",
            "name": str(raw.get("name", "Adsız")),
            "id": raw.get("series_id") or raw.get("id"),
            "cat": str(raw.get("category_id", "")),
            "icon": raw.get("cover") or raw.get("stream_icon") or "",
            "ext": "",
            "rating": raw.get("rating") or "",
            "year": str(raw.get("year") or str(raw.get("releaseDate", ""))[:4] or ""),
            "plot": str(raw.get("plot", ""))[:400],
        }
    return {
        "kind": kind,
        "name": str(raw.get("name", "Adsız")),
        "id": raw.get("stream_id") or raw.get("id"),
        "cat": str(raw.get("category_id", "")),
        "icon": raw.get("stream_icon") or raw.get("cover") or "",
        "ext": raw.get("container_extension") or ("" if kind == "live" else "mp4"),
        "rating": raw.get("rating") or "" if kind == "vod" else "",
        "year": str(raw.get("year") or "") if kind == "vod" else "",
        "plot": str(raw.get("plot", ""))[:400] if kind == "vod" else "",
    }

def make_item(rec):
    meta = ""
    if rec["kind"] != "live":
        parts = [p for p in (rec.get("year", ""),
                             f"★ {rec['rating']}" if rec.get("rating") else "") if p]
        meta = "    ".join(parts)
    return {"text": rec["name"], "meta": meta, "data": rec}

class Library:
    ACTIONS = {
        "live": ("get_live_categories", "get_live_streams"),
        "vod": ("get_vod_categories", "get_vod_streams"),
        "series": ("get_series_categories", "get_series"),
    }

    def __init__(self, session, base_url, username, password, ttl_hours=6):
        self.session = session
        self.base_url = base_url
        self.username = username
        self.password = password
        self.stream_ttl = max(1, int(ttl_hours)) * 3600
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.lock = threading.Lock()
        self.categories = {}
        self.by_category = {}
        self.full = {}
        self.supports_filter = {}

    def key(self, *parts):
        return "|".join([self.base_url, self.username] + [str(p) for p in parts])

    @staticmethod
    def _yaniti_coz(raw):
        """JSON'u çözer; sunucu hata bildirdiyse anlaşılır bir istisna fırlatır."""
        try:
            veri = json.loads(raw)
        except Exception:
            ornek = (raw or b"")[:160].decode("utf-8", "replace").strip().replace("\n", " ")
            raise RuntimeError(
                "Sunucu JSON yerine başka bir şey döndürdü. "
                f"Yanıtın başı: {ornek[:110] or '(boş)'}")
        if isinstance(veri, dict):
            kullanici = veri.get("user_info")
            if isinstance(kullanici, dict):
                if str(kullanici.get("auth", "1")) == "0":
                    raise RuntimeError("Sunucu girişi reddetti: kullanıcı adı, "
                                       "şifre veya abonelik geçersiz.")
                durum = str(kullanici.get("status", "")).lower()
                if durum and durum not in ("active", "1", "true"):
                    raise RuntimeError(f"Hesap durumu: {kullanici.get('status')}")
            for anahtar in ("error", "message", "msg"):
                deger = veri.get(anahtar)
                if isinstance(deger, str) and deger.strip():
                    raise RuntimeError(f"Sunucu hatası: {deger.strip()[:120]}")
        return veri

    def _request(self, action, cache_key, ttl, **params):
        # Önbellekten okunan girdi bozuksa atılır ve yeniden istenir.
        raw = cache_read_raw(cache_key, ttl)
        if raw is not None:
            try:
                veri = self._yaniti_coz(raw)
                # Boş liste de atılır: artık boş yanıt yazmıyoruz, yani
                # diskte boş bir liste varsa eski sürümden kalmış demektir.
                if isinstance(veri, list) and veri:
                    return veri
            except Exception:
                pass
            cache_drop(cache_key)

        query = {"username": self.username, "password": self.password, "action": action}
        query.update(params)
        resp = self.session.get(f"{self.base_url}/player_api.php", params=query, timeout=45)
        resp.raise_for_status()
        raw = resp.content
        veri = self._yaniti_coz(raw)
        # SADECE işe yarar yanıt saklanır. Eskiden hata/boş yanıtlar da
        # yazılıyordu; kategoriler 24 saat saklandığı için tek bir kötü yanıt
        # uygulamayı bir gün boyunca boş bırakabiliyordu.
        if isinstance(veri, list) and veri:
            cache_write_raw(cache_key, raw)
        return veri if isinstance(veri, list) else []

    def fetch_categories(self, kind):
        with self.lock:
            if kind in self.categories:
                return self.categories[kind]
        action = self.ACTIONS[kind][0]
        data = self._request(action, self.key(action), CACHE_TTL_CATEGORIES)
        cats = [{"id": str(c.get("category_id")), "name": str(c.get("category_name", "Adsız"))}
                for c in data]
        with self.lock:
            self.categories[kind] = cats
        return cats

    def fetch_category(self, kind, cat_id):
        with self.lock:
            cached = self.by_category.get((kind, cat_id))
            if cached is not None:
                return cached
            full = self.full.get(kind)
            supports = self.supports_filter.get(kind)
        if full is not None:
            items = [it for it in full if it["data"]["cat"] == cat_id]
            with self.lock:
                self.by_category[(kind, cat_id)] = items
            return items
        action = self.ACTIONS[kind][1]
        if supports is not False:
            data = self._request(action, self.key(action, cat_id), self.stream_ttl,
                                 category_id=cat_id)
            items = [make_item(normalize(kind, s)) for s in data]
            if items or supports is True:
                with self.lock:
                    if items:
                        self.supports_filter[kind] = True
                    self.by_category[(kind, cat_id)] = items
                return items
        full = self.fetch_full(kind)
        items = [it for it in full if it["data"]["cat"] == cat_id]
        with self.lock:
            self.by_category[(kind, cat_id)] = items
        return items

    def fetch_full(self, kind):
        with self.lock:
            if self.full.get(kind) is not None:
                return self.full[kind]
        action = self.ACTIONS[kind][1]
        data = self._request(action, self.key(action, "ALL"), self.stream_ttl)
        items = [make_item(normalize(kind, s)) for s in data]
        with self.lock:
            self.full[kind] = items
            if self.supports_filter.get(kind) is None:
                self.supports_filter[kind] = False
        return items

    def _raw_request(self, cache_key, ttl, **params):
        """player_api.php'den sözlük/liste ne dönerse döndür (fetch_* liste zorunlu kılıyor)."""
        raw = cache_read_raw(cache_key, ttl)
        if raw is not None:
            try:
                return self._yaniti_coz(raw)
            except Exception:
                cache_drop(cache_key)
        query = {"username": self.username, "password": self.password}
        query.update(params)
        resp = self.session.get(f"{self.base_url}/player_api.php",
                                params=query, timeout=30)
        resp.raise_for_status()
        raw = resp.content
        try:
            veri = self._yaniti_coz(raw)
        except Exception as e:
            print(f"Künye alınamadı: {e}")
            return {}
        if veri:
            cache_write_raw(cache_key, raw)
        return veri

    def fetch_details(self, kind, item_id):
        """Film/dizi için ayrıntılı bilgi; canlı yayın için kısa EPG."""
        item_id = str(item_id)
        if kind == "vod":
            data = self._raw_request(self.key("vod_info", item_id), DETAIL_TTL,
                                     action="get_vod_info", vod_id=item_id)
            if isinstance(data, dict):
                info = dict(data.get("info") or {})
                movie = data.get("movie_data") or {}
                for k, v in (movie.items() if isinstance(movie, dict) else []):
                    info.setdefault(k, v)
                return info
            return {}
        if kind == "series":
            data = self._raw_request(self.key("series_info", item_id), DETAIL_TTL,
                                     action="get_series_info", series_id=item_id)
            if isinstance(data, dict):
                info = dict(data.get("info") or {})
                episodes = data.get("episodes") or {}
                if isinstance(episodes, dict):
                    info["_season_count"] = len(episodes)
                    info["_episode_count"] = sum(
                        len(v) for v in episodes.values() if isinstance(v, list))
                return info
            return {}
        # live: kısa EPG (şimdi / sırada)
        data = self._raw_request(self.key("epg", item_id), EPG_TTL,
                                 action="get_short_epg", stream_id=item_id, limit=3)
        listings = []
        if isinstance(data, dict):
            listings = data.get("epg_listings") or []
        return {"_epg": listings if isinstance(listings, list) else []}

    def submit(self, fn, *args, on_done=None, on_error=None):
        def run():
            try:
                result = fn(*args)
            except Exception as e:
                if on_error:
                    on_error(e)
                return
            if on_done:
                on_done(result)
        self.pool.submit(run)

    def shutdown(self):
        havuz_kapat(self.pool)

# ============================== AYARLAR PENCERESİ ==============================
class SettingsWindow:
    PROTOCOL_LABELS = {"auto": "Otomatik", "ts": "TS", "hls": "HLS"}
    PROTOCOL_CODES = {"Otomatik": "auto", "TS": "ts", "HLS": "hls"}

    def __init__(self, master, settings, on_save):
        self.settings = dict(settings)
        self.on_save = on_save
        self.win = ctk.CTkToplevel(master)
        self.win.title(f"Ayarlar — {APP_NAME}")
        simge_uygula(self.win)
        self.win.geometry("520x660")
        self.win.configure(fg_color=C["bg"])
        self.win.transient(master)
        bring_to_front(self.win)

        head = ctk.CTkFrame(self.win, fg_color=C["panel"], corner_radius=0, height=60)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="Ayarlar", font=ui_font(16, "bold"),
                     text_color=C["text"]).pack(anchor="w", padx=20, pady=(11, 0))
        ctk.CTkLabel(head, text="Kanal açılmıyorsa yayın biçimini değiştirmeyi deneyin.",
                     font=ui_font(10), text_color=C["muted"]).pack(anchor="w", padx=20)

        body = ctk.CTkFrame(self.win, fg_color=C["bg"])
        body.pack(fill="both", expand=True, padx=18, pady=14)

        self._label(body, "Hazır profil")
        presets = ctk.CTkFrame(body, fg_color="transparent")
        presets.pack(fill="x", pady=(0, 4))
        for name in PRESETS:
            ctk.CTkButton(presets, text=name, height=34, font=ui_font(11), corner_radius=8,
                          fg_color=C["panel2"], hover_color=C["accent"], text_color=C["text"],
                          command=lambda n=name: self.apply_preset(n)).pack(
                              side="left", expand=True, fill="x", padx=3)

        self._buffer_ms = self.settings.get("buffer_ms", 2000)
        self._label(body, "Canlı TV kalitesi")
        self.quality = ctk.CTkSegmentedButton(
            body, values=[name for _, name in QUALITIES], font=ui_font(11), height=34,
            fg_color=C["panel2"], selected_color=C["accent"], selected_hover_color=C["accent_dk"],
            unselected_color=C["panel2"], unselected_hover_color=C["line"], text_color=C["text"])
        self.quality.set(QUALITY_NAMES.get(self.settings["quality"], "Otomatik"))
        self.quality.pack(fill="x")
        self._hint(body, "Film ve dizi tek dosya olarak gelir; orada kalite seçimi indirme "
                         "hızını değiştirmez, yalnızca işlemci yükünü azaltır.")

        self._label(body, "Canlı yayın biçimi")
        self.protocol = ctk.CTkSegmentedButton(
            body, values=["Otomatik", "TS", "HLS"], font=ui_font(11), height=34,
            fg_color=C["panel2"], selected_color=C["accent"], selected_hover_color=C["accent_dk"],
            unselected_color=C["panel2"], unselected_hover_color=C["line"], text_color=C["text"])
        self.protocol.set(self.PROTOCOL_LABELS.get(self.settings["live_protocol"], "Otomatik"))
        self.protocol.pack(fill="x")
        self._hint(body, "Kanallar açılmıyorsa TS deneyin. HLS kalite seçimine izin verir.")

        self._label(body, "Yayına açılma süresi")
        acilma = ctk.CTkFrame(body, fg_color="transparent")
        acilma.pack(fill="x")
        self._acilma_deger = ctk.CTkLabel(acilma, text="", font=mono_font(11),
                                          text_color=C["accent"], width=58, anchor="e")
        self._acilma_deger.pack(side="right")
        self.acilma = ctk.CTkSlider(acilma, from_=3, to=30, number_of_steps=27, height=16,
                                    button_color=C["accent"], button_hover_color=C["accent_dk"],
                                    progress_color=C["accent"], fg_color=C["line"],
                                    command=self._acilma_degisti)
        self.acilma.set(int(self.settings.get("open_timeout", 10)))
        self.acilma.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self._acilma_degisti(self.acilma.get())
        self._hint(body, "Bir yayın bu süre içinde başlamazsa alternatif biçim denenir. "
                         "Çok kısa tutmak sağlayıcıda 'çok fazla bağlantı' hatasına yol açar.")

        self._label(body, "Diğer")
        self.hw = self._switch(body, "Donanım hızlandırma", self.settings["hw_accel"] != "none")
        self.downgrade = self._switch(body, "Takılmada kaliteyi düşür",
                                      self.settings["auto_downgrade"])
        self.posters = self._switch(body, "Afişleri indir", self.settings["posters"])

        ctk.CTkButton(body, text="Liste önbelleğini temizle", height=34, font=ui_font(11),
                      corner_radius=8, fg_color=C["panel2"], hover_color=C["line"],
                      text_color=C["text"], command=self._clear_cache).pack(fill="x", pady=(14, 0))

        footer = ctk.CTkFrame(self.win, fg_color=C["panel"], corner_radius=0, height=62)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        ctk.CTkButton(footer, text="Kaydet", width=120, height=36, corner_radius=8,
                      fg_color=C["accent"], hover_color=C["accent_dk"], text_color=C["bg"],
                      font=ui_font(12, "bold"), command=self.save).pack(side="right", padx=(6, 18),
                                                                       pady=13)
        ctk.CTkButton(footer, text="Vazgeç", width=90, height=36, corner_radius=8,
                      fg_color=C["panel2"], hover_color=C["line"], text_color=C["text"],
                      font=ui_font(11), command=self.win.destroy).pack(side="right", pady=13)

    def _label(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ui_font(11, "bold"),
                     text_color=C["muted"]).pack(anchor="w", pady=(16, 6))

    def _hint(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ui_font(10), text_color=C["muted"],
                     wraplength=460, justify="left").pack(anchor="w", pady=(6, 0))

    def _switch(self, parent, label, value):
        switch = ctk.CTkSwitch(parent, text=label, font=ui_font(11), text_color=C["text"],
                               progress_color=C["accent"], button_color=C["text"],
                               button_hover_color=C["accent_dk"])
        switch.pack(anchor="w", pady=5)
        switch.select() if value else switch.deselect()
        return switch

    def _acilma_degisti(self, deger):
        self._acilma_deger.configure(text=f"{int(float(deger))} sn")

    def _clear_cache(self):
        if not messagebox.askyesno(
                "Önbelleği temizle",
                "Kategori/içerik listeleri ve indirilen afişler silinsin mi?\n\n"
                "Favoriler ve giriş bilgileriniz SİLİNMEZ.",
                parent=self.win):
            return
        silinen = cache_clear_all(afisler=True)
        messagebox.showinfo("Önbellek",
                            f"{silinen} dosya silindi.\n\n"
                            "Listeler bir sonraki açılışta sunucudan yeniden alınacak.",
                            parent=self.win)

    def apply_preset(self, name):
        preset = PRESETS.get(name, DEFAULT_SETTINGS)
        try:
            self.acilma.set(int(preset.get("open_timeout", 10)))
            self._acilma_degisti(self.acilma.get())
        except Exception:
            pass
        self.quality.set(QUALITY_NAMES.get(preset.get("quality", "auto"), "Otomatik"))
        self.protocol.set(self.PROTOCOL_LABELS.get(preset.get("live_protocol", "auto"), "Otomatik"))
        self._buffer_ms = preset.get("buffer_ms", 2000)
        self.hw.select() if preset.get("hw_accel", "any") != "none" else self.hw.deselect()
        self.downgrade.select() if preset.get("auto_downgrade", True) else self.downgrade.deselect()
        self.posters.select() if preset.get("posters", True) else self.posters.deselect()

    def save(self):
        self.settings.update({
            "quality": QUALITY_CODES.get(self.quality.get(), "auto"),
            "live_protocol": self.PROTOCOL_CODES.get(self.protocol.get(), "auto"),
            "buffer_ms": int(self._buffer_ms),
            "hw_accel": "any" if self.hw.get() else "none",
            "auto_downgrade": bool(self.downgrade.get()),
            "posters": bool(self.posters.get()),
            "open_timeout": int(float(self.acilma.get())),
        })
        ok, hata = save_settings(self.settings)
        if not ok:
            messagebox.showwarning(
                "Ayarlar kaydedilemedi",
                "Ayarlar bu oturumda geçerli olacak ama diske yazılamadı."
                f"\n\nDosya:\n{SETTINGS_FILE}\n\nAyrıntı: {hata}")
        self.on_save(self.settings)
        self.win.destroy()

# ============================== UYGULAMA ==============================
class IPTVApp:
    TABS = [("📺 Canlı TV", "live"), ("🎬 Filmler", "vod"), ("📀 Diziler", "series")]

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        simge_uygula(self.root)
        self.root.geometry("1360x820")
        self.root.minsize(1080, 660)
        self.root.configure(fg_color=C["bg"])
        self.kind = "live"
        self.current = None
        self.search_after = None
        self.request_token = 0
        self.players = []
        self.library = None
        self.mpv_ready = threading.Event()
        self.alive = True
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "IPTVPanel/3.0"})
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=1)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.config = load_config()
        self.favorites = load_favorites()
        self.settings = load_settings()
        self.posters = PosterLoader(self.root, self.session)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        threading.Thread(target=self._init_player, daemon=True).start()
        self.boot()

    def boot(self):
        cfg = self.config
        if cfg.get("auto_login", True) and has_saved_session(cfg):
            self.library = Library(self.session, str(cfg["url"]).rstrip("/"),
                                   cfg["username"], cfg["password"],
                                   ttl_hours=CACHE_HOURS)
            self.show_main()
            threading.Thread(target=self._verify_session, daemon=True).start()
        else:
            self.show_login()

    def _verify_session(self):
        lib = self.library
        try:
            resp = self.session.get(f"{lib.base_url}/player_api.php",
                                    params={"username": lib.username, "password": lib.password},
                                    timeout=12)
            resp.raise_for_status()
            info = resp.json().get("user_info", {})
        except Exception:
            self.ui(self._session_offline)
            return
        if not info or str(info.get("auth", 1)) == "0":
            self.ui(self._session_invalid)
            return
        self.ui(self._session_ok, info)

    def _session_ok(self, info):
        text = str(info.get("username", self.library.username))
        exp = info.get("exp_date")
        if exp:
            try:
                text += " · bitiş " + time.strftime("%d.%m.%Y", time.localtime(int(exp)))
            except Exception:
                pass
        active = info.get("active_cons")
        limit = info.get("max_connections")
        if active is not None and limit:
            text += f" · {active}/{limit} bağlantı"
        if hasattr(self, "account_label"):
            self.account_label.configure(text=text)

    def _session_offline(self):
        if hasattr(self, "account_label"):
            self.account_label.configure(text="çevrimdışı — önbellekten gösteriliyor")

    def _session_invalid(self):
        set_auto_login(False)
        self.config = load_config()
        self.show_login()
        if hasattr(self, "login_msg"):
            self.login_msg.configure(text="Kayıtlı oturum geçersiz. Bilgileri kontrol edin.")

    def _init_player(self):
        if mpv is not None:
            try:
                warmup = mpv.MPV(vo="null", ao="null", terminal="no",
                                 idle="yes", msg_level="all=no")
                warmup.terminate()
            except Exception as e:
                print(f"libmpv ısıtma başarısız: {e}")
        self.mpv_ready.set()

    def ui(self, fn, *args):
        if self.alive:
            try:
                self.root.after(0, fn, *args)
            except Exception:
                pass

    def show_login(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        wrap = ctk.CTkFrame(self.root, fg_color=C["panel"], corner_radius=16)
        wrap.place(relx=0.5, rely=0.5, anchor="center")
        inner = ctk.CTkFrame(wrap, fg_color="transparent")
        inner.pack(padx=44, pady=38)
        ctk.CTkLabel(inner, text=APP_NAME, font=ui_font(26, "bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(inner, text="Sunucu bilgilerinizle bağlanın", font=ui_font(12),
                     text_color=C["muted"]).pack(anchor="w", pady=(2, 22))

        def field(label, show=None, value=""):
            ctk.CTkLabel(inner, text=label, font=ui_font(11), text_color=C["muted"]).pack(anchor="w")
            entry = ctk.CTkEntry(inner, width=340, height=38, font=ui_font(12), show=show,
                                 fg_color=C["panel2"], border_color=C["line"], corner_radius=8)
            entry.pack(pady=(4, 14))
            if value:
                entry.insert(0, value)
            return entry

        self.url_entry = field("Sunucu adresi", value=self.config.get("url", ""))
        self.user_entry = field("Kullanıcı adı", value=self.config.get("username", ""))
        self.pass_entry = field("Parola", show="•", value=self.config.get("password", ""))

        self.remember = ctk.CTkCheckBox(inner, text="Oturumu açık tut", font=ui_font(11),
                                        fg_color=C["accent"], hover_color=C["accent_dk"],
                                        text_color=C["muted"], checkmark_color=C["bg"])
        self.remember.select()
        self.remember.pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(inner, text="Açık kalırsa uygulama bir dahaki açılışta doğrudan başlar.",
                     font=ui_font(10), text_color=C["muted"]).pack(anchor="w", pady=(0, 16))

        self.login_btn = ctk.CTkButton(inner, text="Bağlan", width=340, height=42, corner_radius=8,
                                       fg_color=C["accent"], hover_color=C["accent_dk"],
                                       text_color=C["bg"], font=ui_font(13, "bold"),
                                       command=self.login)
        self.login_btn.pack()

        self.login_msg = ctk.CTkLabel(inner, text="", font=ui_font(11), text_color=C["live"])
        self.login_msg.pack(pady=(10, 0))

        self.root.bind("<Return>", lambda e: self.login())
        self.pass_entry.focus_set()

    def login(self):
        url = self.url_entry.get().strip().rstrip("/")
        user = self.user_entry.get().strip()
        password = self.pass_entry.get().strip()
        if not (url and user and password):
            self.login_msg.configure(text="Tüm alanları doldurun.")
            return
        if not url.startswith("http"):
            url = "http://" + url
        self.login_btn.configure(state="disabled", text="Bağlanılıyor…")
        self.login_msg.configure(text="")

        def worker():
            try:
                resp = self.session.get(f"{url}/player_api.php",
                                        params={"username": user, "password": password}, timeout=12)
                resp.raise_for_status()
                info = resp.json().get("user_info", {})
                if not info or str(info.get("auth", 1)) == "0":
                    raise ValueError("Kullanıcı adı veya parola hatalı.")
                self.ui(self._login_ok, url, user, password)
            except Exception as e:
                self.ui(self._login_fail, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _login_ok(self, url, user, password):
        if self.remember.get():
            ok, hata = save_config(url, user, password, auto_login=True)
            if not ok:
                messagebox.showwarning(
                    "Giriş bilgileri kaydedilemedi",
                    "Bu oturum normal çalışacak, ancak bilgiler kaydedilemediği "
                    "için uygulamayı tekrar açtığınızda giriş yeniden sorulacak."
                    f"\n\nYazılmak istenen dosya:\n{CONFIG_FILE}"
                    f"\n\nAyrıntı: {hata}")
        else:
            clear_config()
        self.config = load_config()
        self.library = Library(self.session, url, user, password,
                               ttl_hours=CACHE_HOURS)
        self.root.unbind("<Return>")
        self.show_main()

    def _login_fail(self, message):
        self.login_btn.configure(state="normal", text="Bağlan")
        self.login_msg.configure(text=message[:130])

    def show_main(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        top = ctk.CTkFrame(self.root, height=58, corner_radius=0, fg_color=C["panel"])
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkLabel(top, text=APP_NAME, font=ui_font(15, "bold"),
                     text_color=C["text"]).pack(side="left", padx=(18, 14))
        self.account_label = ctk.CTkLabel(
            top, text=(self.library.username if self.library else ""),
            font=ui_font(10), text_color=C["muted"])
        self.account_label.pack(side="left", padx=(0, 14))

        self.tabs = ctk.CTkSegmentedButton(
            top, values=[label for label, _ in self.TABS], font=ui_font(12),
            fg_color=C["panel2"], selected_color=C["accent"], selected_hover_color=C["accent_dk"],
            unselected_color=C["panel2"], unselected_hover_color=C["line"],
            text_color=C["text"], height=34, command=self.on_tab_change)
        self.tabs.set(self.TABS[0][0])
        self.tabs.pack(side="left", padx=6)

        ctk.CTkButton(top, text="Oturumu kapat", width=110, height=32, font=ui_font(11),
                      fg_color=C["panel2"], hover_color=C["live"], text_color=C["text"],
                      corner_radius=8, command=self.logout).pack(side="right", padx=(6, 18))
        ctk.CTkButton(top, text="Ayarlar", width=80, height=32, font=ui_font(11),
                      fg_color=C["panel2"], hover_color=C["line"], text_color=C["text"],
                      corner_radius=8, command=self.open_settings).pack(side="right", padx=6)
        ctk.CTkButton(top, text="Yenile", width=70, height=32, font=ui_font(11),
                      fg_color=C["panel2"], hover_color=C["line"], text_color=C["text"],
                      corner_radius=8, command=self.refresh).pack(side="right", padx=6)
        ctk.CTkButton(top, text="Test", width=58, height=32, font=ui_font(11),
                      fg_color=C["panel2"], hover_color=C["line"], text_color=C["text"],
                      corner_radius=8, command=self.baglanti_testi).pack(side="right", padx=6)

        self.quality_menu = ctk.CTkOptionMenu(
            top, width=112, height=32, font=ui_font(11),
            values=[name for _, name in QUALITIES],
            fg_color=C["panel2"], button_color=C["line"], button_hover_color=C["accent"],
            text_color=C["text"], dropdown_fg_color=C["panel2"],
            dropdown_text_color=C["text"], dropdown_hover_color=C["line"],
            command=self.on_quality_change)
        self.quality_menu.set(QUALITY_NAMES.get(self.settings.get("quality", "auto"), "Otomatik"))
        self.quality_menu.pack(side="right", padx=6)

        self.search_entry = ctk.CTkEntry(top, width=260, height=32, font=ui_font(11),
                                         placeholder_text="Ara…", fg_color=C["panel2"],
                                         border_color=C["line"], corner_radius=8)
        self.search_entry.pack(side="right", padx=8)
        self.search_entry.bind("<KeyRelease>", self.on_search_key)

        body = ctk.CTkFrame(self.root, fg_color=C["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=10)

        left = ctk.CTkFrame(body, width=250, fg_color="transparent")
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="Kategoriler", font=ui_font(11, "bold"),
                     text_color=C["muted"]).pack(anchor="w", pady=(0, 6))
        self.cat_list = VirtualList(left, row_height=30, font_size=11,
                                    empty_text="Yükleniyor…", on_select=self.on_category)
        self.cat_list.pack(fill="both", expand=True)

        center = ctk.CTkFrame(body, fg_color="transparent")
        center.pack(side="left", fill="both", expand=True)

        self.content_header = ctk.CTkLabel(center, text="İçerikler", font=ui_font(11, "bold"),
                                           text_color=C["muted"])
        self.content_header.pack(anchor="w", pady=(0, 6))

        self.content_grid = ContentGrid(center,
                                        on_select=self.on_content_select,
                                        on_activate=self.on_content_activate,
                                        on_context=self.on_content_context)
        self.content_grid.pack(fill="both", expand=True)

        self.detail = DetailPanel(self.root, session=self.session,
                                  on_play=self.play_current,
                                  on_favorite=self.toggle_favorite)
        self.root.bind("<Escape>", lambda e: self.detail.hide())

        self.status = ctk.CTkLabel(self.root, text="Kategoriler alınıyor…", font=ui_font(10),
                                   text_color=C["muted"], fg_color=C["panel"], anchor="w", height=24)
        self.status.pack(fill="x", side="bottom")

        self.load_categories()

    def logout(self):
        if not messagebox.askyesno(
                "Oturumu kapat",
                "Oturum kapatılsın mı?\n\nBir dahaki açılışta giriş bilgileri tekrar sorulur."):
            return
        set_auto_login(False)
        self.config = load_config()
        self.show_login()

    def refresh(self):
        cache_clear_all()
        if self.library:
            eski = self.library
            self.library = Library(self.session, eski.base_url,
                                   eski.username, eski.password,
                                   ttl_hours=CACHE_HOURS)
            eski.shutdown()          # eski havuz sızmasın
        self.status.configure(text="Önbellek temizlendi, listeler yenileniyor…")
        self.load_categories()

    def open_settings(self):
        SettingsWindow(self.root, self.settings, self.apply_settings)

    def apply_settings(self, settings):
        self.settings = settings
        if hasattr(self, "quality_menu"):
            self.quality_menu.set(QUALITY_NAMES.get(settings.get("quality", "auto"), "Otomatik"))
        self.status.configure(text="Ayarlar kaydedildi. Yeni ayarlar sonraki oynatmada geçerli.")

    def on_quality_change(self, label):
        self.settings["quality"] = QUALITY_CODES.get(label, "auto")
        ok, hata = save_settings(self.settings)
        self.status.configure(
            text=f"Kalite: {label}" if ok else f"Kalite: {label} (kaydedilemedi: {hata})"[:160])

    def load_categories(self):
        kind = self.kind
        self.cat_list.set_placeholder("Yükleniyor…")
        self.content_grid.set_placeholder("Kategori seçin")
        self.status.configure(text="Kategoriler alınıyor…")
        self.library.submit(self.library.fetch_categories, kind,
                            on_done=lambda cats: self.ui(self._show_categories, kind, cats),
                            on_error=lambda e: self.ui(self._fail, f"Kategoriler alınamadı: {e}"))

    def _show_categories(self, kind, cats):
        if kind != self.kind:
            return
        items = [{"text": "  Favoriler", "meta": str(len(self.favorites.get(kind, []))),
                  "data": {"cat_id": "__fav__"}, "color": C["accent"]},
                 {"text": "  Tümü (tam liste)", "meta": "", "data": {"cat_id": "__all__"}}]
        items += [{"text": "  " + c["name"], "meta": "", "data": {"cat_id": c["id"]}} for c in cats]
        self.cat_list.set_items(items)
        self.status.configure(text=f"{len(cats)} kategori hazır")
        if len(items) > 2:
            self.cat_list.select_index(2)

    def _fail(self, message):
        metin = str(message).replace("\n", " ").strip()
        self.status.configure(text=metin[:300])
        print(f"[hata] {metin}")

    def on_tab_change(self, label):
        for text, kind in self.TABS:
            if text == label:
                self.kind = kind
                break
        self.search_entry.delete(0, "end")
        self.current = None
        panel = getattr(self, "detail", None)
        if panel is not None:
            panel.hide()
        self.load_categories()

    def on_category(self, item, _idx):
        cat_id = item["data"]["cat_id"]
        kind = self.kind
        self.request_token += 1
        token = self.request_token
        if cat_id == "__fav__":
            items = [make_item(rec) for rec in self._favorite_records()]
            self.content_header.configure(text=f"Favoriler — {len(items)} içerik")
            self.content_grid.set_items(items, session=self.session)
            return
        header = item["text"].strip()
        self.content_grid.set_placeholder("Yükleniyor…")
        self.content_header.configure(text=f"{header} — yükleniyor")
        self.status.configure(text="İçerik alınıyor…")
        if cat_id == "__all__":
            job, args = self.library.fetch_full, (kind,)
        else:
            job, args = self.library.fetch_category, (kind, cat_id)
        self.library.submit(job, *args,
                            on_done=lambda res: self.ui(self._show_content, token, header, res),
                            on_error=lambda e: self.ui(self._content_failed, token, e))

    def _show_content(self, token, header, items):
        if token != self.request_token:
            return
        self.content_grid.set_items(items, session=self.session)
        self.content_header.configure(text=f"{header} — {len(items)} içerik")
        self.status.configure(text="Hazır")

    def _content_failed(self, token, error):
        if token != self.request_token:
            return
        self.content_grid.set_placeholder("İçerik alınamadı")
        self.status.configure(text=f"Hata: {error}"[:160])

    # ---------------------- BAĞLANTI TEŞHİSİ ----------------------
    def baglanti_testi(self):
        """Sunucunun gerçekte ne döndürdüğünü tek ekranda gösterir."""
        if not self.library:
            messagebox.showwarning("Bağlantı testi", "Önce giriş yapın.")
            return
        self.status.configure(text="Bağlantı test ediliyor…")
        self.library.submit(self._tani_topla,
                            on_done=lambda r: self.ui(self._tani_goster, r),
                            on_error=lambda e: self.ui(self._tani_goster,
                                                       {"hata": str(e)}))

    def _tani_topla(self):
        """Ağ işi — arayüz iş parçacığında ÇALIŞMAZ."""
        lib = self.library
        rapor = {"sunucu": lib.base_url, "kullanici": lib.username}
        import time as _t

        def olc(etiket, fn):
            bas = _t.time()
            try:
                sonuc = fn()
                rapor[etiket] = {"ok": True, "sure": _t.time() - bas, "sonuc": sonuc}
            except Exception as e:
                rapor[etiket] = {"ok": False, "sure": _t.time() - bas,
                                 "hata": f"{e.__class__.__name__}: {e}"}

        # 1) Hesap bilgisi (onbellege girmez)
        def hesap():
            resp = lib.session.get(f"{lib.base_url}/player_api.php",
                                   params={"username": lib.username,
                                           "password": lib.password},
                                   timeout=20)
            rapor["http_durum"] = resp.status_code
            resp.raise_for_status()
            veri = json.loads(resp.content)
            if not isinstance(veri, dict):
                return {"biçim": type(veri).__name__}
            bilgi = veri.get("user_info") or {}
            return {
                "auth": bilgi.get("auth"),
                "durum": bilgi.get("status"),
                "bitiş": bilgi.get("exp_date"),
                "bağlantı": f"{bilgi.get('active_cons', '?')} / {bilgi.get('max_connections', '?')}",
            }
        olc("hesap", hesap)

        # 2) Kategoriler (onbellek atlanarak)
        for tur, etiket in (("live", "canlı"), ("vod", "film"), ("series", "dizi")):
            def kategoriler(t=tur):
                eylem = lib.ACTIONS[t][0]
                resp = lib.session.get(f"{lib.base_url}/player_api.php",
                                       params={"username": lib.username,
                                               "password": lib.password,
                                               "action": eylem},
                                       timeout=25)
                resp.raise_for_status()
                veri = lib._yaniti_coz(resp.content)
                if not isinstance(veri, list):
                    raise RuntimeError(f"liste değil: {type(veri).__name__}")
                return f"{len(veri)} kategori"
            olc(etiket, kategoriler)
        return rapor

    def _tani_goster(self, rapor):
        self.status.configure(text="Hazır")
        satirlar = []
        if rapor.get("hata"):
            satirlar.append(f"Test çalıştırılamadı: {rapor['hata']}")
        else:
            satirlar.append(f"Sunucu   : {rapor.get('sunucu', '?')}")
            satirlar.append(f"Kullanıcı: {rapor.get('kullanici', '?')}")
            if "http_durum" in rapor:
                satirlar.append(f"HTTP     : {rapor['http_durum']}")
            satirlar.append("")
            hesap = rapor.get("hesap", {})
            if hesap.get("ok"):
                bilgi = hesap["sonuc"]
                auth = str(bilgi.get("auth"))
                satirlar.append("HESAP")
                satirlar.append(f"  Giriş     : {'kabul' if auth == '1' else 'RED (auth=' + auth + ')'}")
                satirlar.append(f"  Durum     : {bilgi.get('durum')}")
                bitis = bilgi.get("bitiş")
                if bitis:
                    try:
                        bitis = time.strftime("%d.%m.%Y",
                                              time.localtime(int(bitis)))
                    except (TypeError, ValueError):
                        pass
                satirlar.append(f"  Bitiş     : {bitis or 'belirtilmemiş'}")
                satirlar.append(f"  Bağlantı  : {bilgi.get('bağlantı')}")
            else:
                satirlar.append(f"HESAP: BAŞARISIZ — {hesap.get('hata', '?')}")
            satirlar.append("")
            satirlar.append("KATEGORİLER")
            for etiket in ("canlı", "film", "dizi"):
                d = rapor.get(etiket, {})
                if d.get("ok"):
                    satirlar.append(f"  {etiket:8}: {d['sonuc']}  ({d['sure']:.1f} sn)")
                else:
                    satirlar.append(f"  {etiket:8}: HATA — {d.get('hata', '?')[:80]}")
        metin = "\n".join(satirlar)
        print("[bağlantı testi]\n" + metin)
        self._tani_penceresi(metin)

    def _tani_penceresi(self, metin):
        win = ctk.CTkToplevel(self.root)
        win.title(f"Bağlantı testi — {APP_NAME}")
        win.geometry("560x520")
        win.configure(fg_color=C["bg"])
        simge_uygula(win)
        kutu = ctk.CTkTextbox(win, font=mono_font(11), fg_color=C["panel"],
                              text_color=C["text"], wrap="word")
        kutu.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        kutu.insert("1.0", metin)
        kutu.configure(state="disabled")
        alt = ctk.CTkFrame(win, fg_color=C["bg"], height=48)
        alt.pack(fill="x", padx=12, pady=(0, 12))
        alt.pack_propagate(False)

        def kopyala():
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(metin)
                self.status.configure(text="Test sonucu panoya kopyalandı.")
            except Exception:
                pass
        ctk.CTkButton(alt, text="Panoya kopyala", height=36, corner_radius=8,
                      fg_color=C["panel2"], hover_color=C["line"], text_color=C["text"],
                      font=ui_font(11), command=kopyala).pack(side="left", fill="x",
                                                              expand=True, padx=(0, 6))
        ctk.CTkButton(alt, text="Kapat", width=90, height=36, corner_radius=8,
                      fg_color=C["accent"], hover_color=C["accent_dk"], text_color=C["bg"],
                      font=ui_font(11, "bold"), command=win.destroy).pack(side="left")
        bring_to_front(win, tries=2)

    def _favorite_records(self):
        records = []
        for fav in self.favorites.get(self.kind, []):
            if "kind" in fav:
                records.append(fav)
            else:
                records.append({
                    "kind": self.kind,
                    "name": fav.get("name", "Adsız"),
                    "id": fav.get("id"),
                    "cat": "",
                    "icon": fav.get("icon", ""),
                    "ext": fav.get("container_extension") or ("" if self.kind == "live" else "mp4"),
                    "rating": "", "year": "", "plot": "",
                })
        return records

    def on_search_key(self, _event=None):
        if self.search_after:
            self.root.after_cancel(self.search_after)
        self.search_after = self.root.after(300, self.run_search)

    def run_search(self):
        self.search_after = None
        query = self.search_entry.get().strip().lower()
        if len(query) < 2:
            selected = self.cat_list.selected()
            if selected:
                self.on_category(selected, 0)
            return
        kind = self.kind
        self.request_token += 1
        token = self.request_token
        self.content_header.configure(text="Aranıyor…")
        self.status.configure(text="Arama için tam liste hazırlanıyor…")

        def job():
            full = self.library.fetch_full(kind)
            return [it for it in full if query in it["text"].lower()][:4000]

        self.library.submit(job,
                            on_done=lambda res: self.ui(self._show_content, token, "Arama", res),
                            on_error=lambda e: self.ui(self._content_failed, token, e))

    def on_content_select(self, item, _idx):
        rec = item["data"]
        self.current = rec
        self.show_details(rec)

    def show_details(self, rec):
        panel = getattr(self, "detail", None)
        if panel is None:
            return
        token = panel.show(rec, is_favorite=self._is_favorite(rec))
        kind = rec.get("kind", self.kind)
        item_id = rec.get("id")
        if not item_id:
            panel.apply_details(token, {}, kind)
            return
        self.library.submit(
            self.library.fetch_details, kind, item_id,
            on_done=lambda info: self.ui(panel.apply_details, token, info, kind),
            on_error=lambda e: self.ui(panel.detail_failed, token, e))

    def _is_favorite(self, rec):
        sid = str(rec.get("id"))
        lst = self.favorites.get(rec.get("kind", self.kind), [])
        return any(str(f.get("id")) == sid for f in lst)

    def on_content_activate(self, item, idx):
        self.on_content_select(item, idx)
        self.play_current()

    def play_current(self):
        rec = self.current
        if not rec:
            return

        if not self.mpv_ready.is_set():
            self.status.configure(text="Oynatıcı hazırlanıyor…")
            self.root.after(200, self.play_current)
            return

        if mpv is None:
            self._mpv_hatasi()
            return

        lib = self.library
        if rec["kind"] in ("live", "vod"):
            source = {"kind": rec["kind"], "base": lib.base_url, "user": lib.username,
                      "pass": lib.password, "id": rec["id"], "ext": rec.get("ext")}
            self._open_player(source, rec["name"])
        else:
            self.status.configure(text="Bölümler alınıyor…")
            self.library.submit(self._fetch_series, rec["id"],
                                on_done=lambda data: self.ui(self._open_series, rec["name"], data),
                                on_error=lambda e: self.ui(self._fail, f"Dizi bilgisi alınamadı: {e}"))

    def _mpv_hatasi(self):
        """libmpv yüklenemediğinde ne yapılacağını açıkça anlatan uyarı."""
        hedef = mpv_hedef_klasor()
        satirlar = ["Video oynatıcı kitaplığı (libmpv) yüklenemedi.", ""]
        if MPV_DLL_PATH:
            satirlar += [f"DLL bulundu:\n{MPV_DLL_PATH}", ""]
            if MPV_DURUM:
                satirlar += [MPV_DURUM, ""]
        else:
            satirlar += [
                "Yapılması gereken: libmpv-2.dll dosyasını şu klasöre kopyalayın:",
                f"\n{hedef}\n",
                "Dosyayı mpv.io > Downloads > Windows libmpv (shared) paketinden "
                "alabilirsiniz. 64-bit Windows için 64-bit sürümü gerekir.",
                "",
            ]
        bakilan = MPV_SEARCH_DIRS[:8]
        if bakilan:
            satirlar += ["Bakılan klasörler:"]
            satirlar += ["  • " + d for d in bakilan]
            if len(MPV_SEARCH_DIRS) > len(bakilan):
                satirlar.append(f"  • … ve {len(MPV_SEARCH_DIRS) - len(bakilan)} klasör daha")
            satirlar.append("")
        if MPV_IMPORT_ERROR:
            satirlar.append(f"Teknik ayrıntı: {MPV_IMPORT_ERROR}")
        messagebox.showerror("Oynatıcı başlatılamadı", "\n".join(satirlar))

    def _fetch_series(self, series_id):
        lib = self.library
        key = lib.key("series_info", series_id)
        raw = cache_read_raw(key, 24 * 3600)
        if raw is None:
            resp = self.session.get(f"{lib.base_url}/player_api.php",
                                    params={"username": lib.username, "password": lib.password,
                                            "action": "get_series_info", "series_id": series_id},
                                    timeout=30)
            resp.raise_for_status()
            raw = resp.content
            cache_write_raw(key, raw)
        return json.loads(raw)

    def _open_player(self, source, title):
        # Önizleme penceresi açıksa üçüncü pencere yerine onu kullan.
        devralinan = None
        panel = getattr(self, "detail", None)
        if panel is not None and panel.is_open():
            devralinan = panel.pencereyi_devret()
        player = PlayerWindow(self.root, source, title, mpv, self.settings,
                              on_close=self._player_closed,
                              mevcut_pencere=devralinan)
        self.players.append(player)

    def _player_closed(self, player):
        if player in self.players:
            self.players.remove(player)

    def _open_series(self, series_name, info):
        episodes = (info or {}).get("episodes") or {}
        self.status.configure(text="Hazır")
        if not episodes:
            messagebox.showinfo("Dizi", "Bölüm bulunamadı.")
            return

        series_cover = info.get("info", {}).get("cover") or info.get("info", {}).get("stream_icon", "")

        win = ctk.CTkToplevel(self.root)
        win.title(f"{series_name} — {APP_NAME}")
        simge_uygula(win)
        win.geometry("1000x700")
        win.configure(fg_color=C["bg"])
        win.transient(self.root)
        bring_to_front(win)

        head = ctk.CTkFrame(win, fg_color=C["panel"], corner_radius=0, height=78)
        head.pack(fill="x")
        head.pack_propagate(False)
        ctk.CTkLabel(head, text=series_name, font=ui_font(16, "bold"),
                     text_color=C["text"]).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(head, text=str(info.get("info", {}).get("plot", ""))[:190], font=ui_font(11),
                     text_color=C["muted"], wraplength=900, justify="left").pack(anchor="w", padx=18)

        body = ctk.CTkFrame(win, fg_color=C["bg"])
        body.pack(fill="both", expand=True, padx=12, pady=10)

        left = ctk.CTkFrame(body, width=200, fg_color="transparent")
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        ctk.CTkLabel(left, text="Sezonlar", font=ui_font(11, "bold"),
                     text_color=C["muted"]).pack(anchor="w", pady=(0, 6))
        season_list = VirtualList(left, row_height=30, font_size=11)
        season_list.pack(fill="both", expand=True)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        ep_header = ctk.CTkLabel(right, text="Bölümler", font=ui_font(11, "bold"),
                                 text_color=C["muted"])
        ep_header.pack(anchor="w", pady=(0, 6))
        ep_list = VirtualList(right, row_height=32, font_size=12, empty_text="Sezon seçin")
        ep_list.pack(fill="both", expand=True)

        if series_cover:
            cover_frame = ctk.CTkFrame(body, width=180, fg_color=C["panel"], corner_radius=10)
            cover_frame.pack(side="right", fill="y", padx=(10, 0))
            cover_frame.pack_propagate(False)
            cover_label = ctk.CTkLabel(cover_frame, text="", width=160, height=240)
            cover_label.pack(padx=10, pady=10)

            def load_cover():
                try:
                    resp = self.session.get(series_cover, timeout=6)
                    resp.raise_for_status()
                    img = Image.open(io.BytesIO(resp.content))
                    img.thumbnail((160, 240), Image.BILINEAR)
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                    cover_label.configure(image=ctk_img, text="")
                    cover_label.image = ctk_img
                except Exception:
                    cover_label.configure(text="Kapak\nyüklenemedi")

            threading.Thread(target=load_cover, daemon=True).start()

        lib = self.library

        def play_episode(item, _idx):
            ep = item["data"]
            source = {"kind": "series", "base": lib.base_url, "user": lib.username,
                      "pass": lib.password, "id": ep.get("id"),
                      "ext": ep.get("container_extension") or "mkv"}
            label = f"{series_name} · S{ep.get('season','?')}B{ep.get('episode_num','?')}"
            self._open_player(source, label)

        ep_list.on_activate = play_episode

        def select_season(item, _idx):
            season = item["data"]
            rows = []
            for ep in episodes.get(season, []):
                if isinstance(ep, dict):
                    info_data = ep.get("info")
                    duration = info_data.get("duration", "") if isinstance(info_data, dict) else ""
                    rows.append({
                        "text": f"{ep.get('episode_num','?')}.  {ep.get('title','Bölüm')}",
                        "meta": str(duration),
                        "data": dict(ep, season=season),
                    })
                else:
                    rows.append({
                        "text": "Bölüm",
                        "meta": "",
                        "data": {"id": ep, "season": season, "episode_num": "?", "title": "Bölüm"},
                    })
            ep_header.configure(text=f"Sezon {season} — {len(rows)} bölüm")
            ep_list.set_items(rows)

        season_list.on_select = select_season
        seasons = sorted(episodes.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        season_list.set_items([{"text": f"  Sezon {s}", "meta": str(len(episodes[s])), "data": s}
                               for s in seasons])
        if seasons:
            season_list.select_index(0)

    def _fav_text(self):
        rec = self.current or {}
        sid = str(rec.get("id"))
        exists = any(str(f.get("id")) == sid for f in self.favorites.get(self.kind, []))
        return "Favorilerden çıkar" if exists else "Favorilere ekle"

    def toggle_favorite(self):
        rec = self.current
        if not rec:
            return
        lst = self.favorites.setdefault(self.kind, [])
        sid = str(rec.get("id"))
        existing = next((f for f in lst if str(f.get("id")) == sid), None)
        if existing:
            lst.remove(existing)
            self.status.configure(text="Favorilerden çıkarıldı.")
        else:
            lst.append(dict(rec))
            self.status.configure(text="Favorilere eklendi.")
        ok, hata = save_favorites(self.favorites)
        if not ok:
            self.status.configure(text=f"Favoriler kaydedilemedi: {hata}"[:160])
        panel = getattr(self, "detail", None)
        if panel is not None and panel.is_open():
            panel.set_favorite(self._is_favorite(rec))
        self._favori_sayacini_guncelle()
        selected = self.cat_list.selected()
        if selected and selected["data"]["cat_id"] == "__fav__":
            self.on_category(selected, 0)

    def _favori_sayacini_guncelle(self):
        """Kategori listesindeki 'Favoriler' satırının sayısını tazeler."""
        try:
            for idx, satir in enumerate(self.cat_list._items):
                if (satir.get("data") or {}).get("cat_id") == "__fav__":
                    self.cat_list.update_item(
                        idx, meta=str(len(self.favorites.get(self.kind, []))))
                    break
        except Exception:
            pass

    def on_content_context(self, event, item, idx):
        self.on_content_select(item, idx)
        menu = tk.Menu(self.root, tearoff=0, bg=C["panel2"], fg=C["text"],
                       activebackground=C["accent"], activeforeground=C["bg"],
                       bd=0, font=canvas_font(11))
        menu.add_command(label="Oynat", command=self.play_current)
        menu.add_command(label=self._fav_text(), command=self.toggle_favorite)
        menu.add_separator()
        menu.add_command(label="Bilgi", command=lambda: self._show_info(item["data"]))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_info(self, rec):
        self.show_details(rec)

    def quit(self):
        self.alive = False
        panel = getattr(self, "detail", None)
        if panel is not None:
            try:
                panel.destroy()
            except Exception:
                pass
        for player in list(self.players):
            try:
                player.close()
            except Exception:
                pass
        grid = getattr(self, "content_grid", None)
        if grid is not None:
            try:
                havuz_kapat(grid._pool)
            except Exception:
                pass
        if self.library:
            self.library.shutdown()
        try:
            self.root.destroy()
        except Exception:
            pass
        # Kesin çıkış: ağ isteğinin ortasında kalmış bir iş parçacığı süreci
        # ayakta tutup dosyaları kilitlemesin (yeniden derlemeyi engelliyordu).
        # Ayarlar/favoriler değiştikleri anda diske yazıldığı için kayıp olmaz.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

if __name__ == "__main__":
    gorev_cubugu_kimligi()
    root = ctk.CTk()
    app = IPTVApp(root)
    root.mainloop()