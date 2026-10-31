"""Media Renamer Pro 4.3

Képek és videók csoportos átnevezése a felvétel dátuma és egy téma alapján,
opcionálisan közös (dátum_téma) mappába mozgatva, vagy napok szerint
ÉÉÉÉ-HH-NN mappákba rendezve.

Kötelező függőség: Pillow.
Opcionális: tkinterdnd2 (fogd és vidd), python-vlc + VLC (beépített lejátszó),
send2trash (törlés lomtárba), sv-ttk (Sun Valley megjelenés), pillow-heif (iPhone HEIC fotók),
exifread és rawpy (RAW fotók dátuma és bélyegképe),
ffmpeg/ffprobe a PATH-on (videó dátum, bélyegkép).
"""
import os
import re
import sys
import json
import queue
import shutil
import string
import platform
import threading
import subprocess
import configparser
import io
from datetime import datetime, timedelta, timezone
from functools import partial

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageTk, ImageOps

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _BaseTk = TkinterDnD.Tk
    HAS_DND = True
except Exception:
    _BaseTk = tk.Tk
    HAS_DND = False

try:
    import vlc
except Exception:
    vlc = None

try:
    from send2trash import send2trash
except Exception:
    send2trash = None

try:
    import sv_ttk
except Exception:
    sv_ttk = None

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()  # ettől kezdve a PIL.Image.open a HEIC/HEIF fájlokat is megnyitja
    HAS_HEIF = True
except Exception:
    HAS_HEIF = False

try:
    import exifread
except Exception:
    exifread = None

try:
    import rawpy
except Exception:
    rawpy = None

APP_NAME = "Media Renamer Pro 4.3"
HEIF_EXTS = (".heic", ".heif")
# RAW-fájlok: a dátumot az exifread, a bélyegképet a rawpy (vagy a beágyazott kis előnézet) adja
RAW_EXTS = (".dng", ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".orf", ".rw2", ".raf", ".pef", ".srw")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp") + (HEIF_EXTS if HAS_HEIF else ()) + RAW_EXTS
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".mts")
# ISO BMFF (MP4/QuickTime) konténerek: ezek dátumát ffprobe nélkül, Pythonban is ki tudjuk olvasni
BMFF_EXTS = (".mp4", ".mov", ".m4v", ".3gp")
MEDIA_EXTS = IMAGE_EXTS + VIDEO_EXTS
DEFAULT_PATTERN = "{date}_{suffix}_{counter}"
THUMB_SIZE = (150, 150)

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
# Windowson (--noconsole EXE) ne villanjon fel konzolablak minden ffprobe hívásnál
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def resource_path(relative_path):
    """Abszolút útvonal létrehozása EXE és fejlesztői módhoz"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def is_video(path):
    return path.lower().endswith(VIDEO_EXTS)


def is_raw(path):
    return path.lower().endswith(RAW_EXTS)


def is_media(path):
    # A macOS a FAT/exFAT meghajtókra (SD-kártya, pendrive) "._IMG_1234.JPG" kísérőfájlokat ír:
    # ezek nem képek, nem szabad őket átnevezni vagy mozgatni
    return path.lower().endswith(MEDIA_EXTS) and not os.path.basename(path).startswith("._")


# ---------------------------------------------------------------------------
# Szövegek (hu/en)
# ---------------------------------------------------------------------------
TEXTS = {
    "hu": {
        "ready": "Kész",
        "loading": "Betöltés...",
        "loaded": "Betöltve {n} elem",
        "btn_folder": "Mappa kiválasztása",
        "btn_rename": "Átnevezés",
        "btn_refresh": "Frissítés",
        "btn_markall": "Minden kijelölése",
        "btn_unmark": "Kijelölés törlése",
        "btn_undo": "Visszavonás",
        "btn_delete": "Törlés",
        "btn_exit": "Kilépés",
        "chk_recursive": "Almappák is",
        "menu_settings": "Beállítások",
        "menu_edit": "Szerkesztés",
        "menu_templates": "Átnevezési sablonok",
        "menu_language": "Nyelv beállítása",
        "menu_appearance": "Megjelenés",
        "appearance_system": "Rendszer (alapértelmezett)",
        "appearance_flat-light": "Világos",
        "appearance_flat-dark": "Sötét",
        "appearance_sun-valley-light": "Sun Valley világos (Windows 11)",
        "appearance_sun-valley-dark": "Sun Valley sötét (Windows 11)",
        "appearance_needs_sv": "  (pip install sv-ttk)",
        "tpl_title": "Átnevezési sablon",
        "tpl_prompt": ("Sablon formátum. Használható mezők:\n"
                       "{date} = 2024-05-01_14-30-00   {day} = 2024-05-01   {time} = 14-30-00\n"
                       "{suffix} = téma   {seq} = sorszám (001, 002...)   {original} = eredeti név\n"
                       "{counter} = ütközésszámláló (csak ha kell, egyébként elhagyva)"),
        "tpl_invalid": "Érvénytelen sablon: {err}",
        "tpl_saved": "Sablon elmentve. Példa:\n{example}",
        "lang_title": "Nyelv",
        "lang_prompt": "Válassz nyelvet (hu/en):",
        "restart": "A változtatások érvényesítéséhez indítsd újra a programot!",
        "choose_folder": "Válassz médiamappát",
        "no_folder": "Előbb válassz egy mappát!",
        "none_selected_title": "Nincs kijelölve",
        "none_selected": "Jelölj ki legalább egy fájlt!",
        "busy": "Egy művelet még fut, várj egy kicsit.",
        "busy_exit": "Egy művelet még fut. Ha most kilépsz, félbeszakad. Biztosan kilépsz?",
        "suffix_title": "Téma választása",
        "suffix_prompt": "Mi legyen a képek/videók neve?:",
        "move_check": "File-ok másik könyvtárba mozgatása",
        "ok": "OK (Enter)",
        "cancel": "Mégse (Esc)",
        "reading_dates": "Dátumok olvasása... {i}/{n}",
        "renaming": "Átnevezés... {i}/{n}",
        "renamed": "{n} fájl átnevezve!",
        "moved_to": " (Átmozgatva ide: {folder})",
        "unchanged": "{n} fájl neve már megfelelt, nem változott.",
        "file_dates": ("{n} fájlban nem volt beágyazott felvételi dátum, "
                       "ezeknél a fájl dátuma lett használva."),
        "rename_errors": "{n} fájl nem nevezhető át:\n",
        "success": "Siker",
        "error": "Hiba",
        "info": "Info",
        "undo_none": "Nincs visszavonható művelet.",
        "undo_confirm": "Visszavonod az utolsó átnevezést/áthelyezést ({n} fájl)?",
        "undo_done": "{n} fájl visszaállítva.",
        "delete_confirm_title": "Törlés megerősítése",
        "delete_confirm_trash": "Biztosan a lomtárba helyezed a {n} kijelölt fájlt?",
        "delete_confirm_perm": ("A send2trash modul nincs telepítve, ezért a törlés VÉGLEGES lesz!\n"
                                "Biztosan törölni akarod a {n} kijelölt fájlt?"),
        "delete_none": "Válassz ki elemeket a törléshez!",
        "deleted": "{n} fájl törölve",
        "delete_errors": "Törlés hibákkal ({n}):\n",
        "load_error": "Betöltési hiba: {err}",
        "video_error": "Videólejátszási hiba: {err}",
        "player_title": "Videólejátszó - {name}",
        "open_error": "Hiba a megnyitáskor: {err}",
        "btn_daysort": "Rendezés napok szerint",
        "daysort_all": "Nincs kijelölt fájl. Rendezed mind a {n} betöltött fájlt?",
        "daysort_title": "Rendezés napok szerint - előnézet",
        "daysort_summary": ("{n} fájl kerül át {d} napi mappába (ÉÉÉÉ-HH-NN) ide: {folder}\n"
                            "Ebből {new} mappa új. Már a helyén van: {in_place} fájl."),
        "daysort_file_dates": ("{n} fájlban nincs beágyazott felvételi dátum, "
                               "ezeknél a fájl dátuma lesz használva (jelölés: *)."),
        "daysort_include_file": "Metaadat nélküli fájlok áthelyezése is (fájldátum alapján)",
        "daysort_col_day": "Nap",
        "daysort_col_file": "Fájl",
        "daysort_col_new": "Új név",
        "daysort_nothing": "Nincs áthelyezendő fájl: mind a megfelelő napi mappában van.",
        "daysort_moving": "Áthelyezés... {i}/{n}",
        "daysort_done": "{n} fájl áthelyezve {d} napi mappába.",
        "daysort_undo_hint": "Visszavonás: Szerkesztés → Visszavonás (Ctrl+Z).",
        "daysort_errors": "{n} fájl nem helyezhető át:\n",
    },
    "en": {
        "ready": "Ready",
        "loading": "Loading...",
        "loaded": "Loaded {n} items",
        "btn_folder": "Select folder",
        "btn_rename": "Rename",
        "btn_refresh": "Refresh",
        "btn_markall": "Select all",
        "btn_unmark": "Clear selection",
        "btn_undo": "Undo",
        "btn_delete": "Delete",
        "btn_exit": "Exit",
        "chk_recursive": "Include subfolders",
        "menu_settings": "Settings",
        "menu_edit": "Edit",
        "menu_templates": "Naming templates",
        "menu_language": "Language",
        "menu_appearance": "Appearance",
        "appearance_system": "System (default)",
        "appearance_flat-light": "Light",
        "appearance_flat-dark": "Dark",
        "appearance_sun-valley-light": "Sun Valley light (Windows 11)",
        "appearance_sun-valley-dark": "Sun Valley dark (Windows 11)",
        "appearance_needs_sv": "  (pip install sv-ttk)",
        "tpl_title": "Naming template",
        "tpl_prompt": ("Template format. Available fields:\n"
                       "{date} = 2024-05-01_14-30-00   {day} = 2024-05-01   {time} = 14-30-00\n"
                       "{suffix} = topic   {seq} = sequence (001, 002...)   {original} = original name\n"
                       "{counter} = collision counter (only when needed, otherwise omitted)"),
        "tpl_invalid": "Invalid template: {err}",
        "tpl_saved": "Template saved. Example:\n{example}",
        "lang_title": "Language",
        "lang_prompt": "Choose language (hu/en):",
        "restart": "Restart the program to apply the changes!",
        "choose_folder": "Choose a media folder",
        "no_folder": "Choose a folder first!",
        "none_selected_title": "Nothing selected",
        "none_selected": "Select at least one file!",
        "busy": "An operation is still running, please wait.",
        "busy_exit": "An operation is still running and will be interrupted. Exit anyway?",
        "suffix_title": "Choose topic",
        "suffix_prompt": "What should the pictures/videos be called?:",
        "move_check": "Move files to a separate folder",
        "ok": "OK (Enter)",
        "cancel": "Cancel (Esc)",
        "reading_dates": "Reading dates... {i}/{n}",
        "renaming": "Renaming... {i}/{n}",
        "renamed": "{n} files renamed!",
        "moved_to": " (Moved to: {folder})",
        "unchanged": "{n} files already had the right name and were left unchanged.",
        "file_dates": ("{n} files had no embedded capture date; "
                       "their file date was used instead."),
        "rename_errors": "{n} files could not be renamed:\n",
        "success": "Success",
        "error": "Error",
        "info": "Info",
        "undo_none": "Nothing to undo.",
        "undo_confirm": "Undo the last rename/move ({n} files)?",
        "undo_done": "{n} files restored.",
        "delete_confirm_title": "Confirm delete",
        "delete_confirm_trash": "Move the {n} selected files to the recycle bin?",
        "delete_confirm_perm": ("send2trash is not installed, so deletion will be PERMANENT!\n"
                                "Really delete the {n} selected files?"),
        "delete_none": "Select items to delete!",
        "deleted": "{n} files deleted",
        "delete_errors": "Deleted with errors ({n}):\n",
        "load_error": "Loading error: {err}",
        "video_error": "Video playback error: {err}",
        "player_title": "Video player - {name}",
        "open_error": "Error while opening: {err}",
        "btn_daysort": "Sort by day",
        "daysort_all": "No files selected. Sort all {n} loaded files?",
        "daysort_title": "Sort by day - preview",
        "daysort_summary": ("{n} files will be moved into {d} day folders (YYYY-MM-DD) in: {folder}\n"
                            "{new} of the folders are new. Already in place: {in_place} files."),
        "daysort_file_dates": ("{n} files have no embedded capture date; "
                               "their file date will be used (marked with *)."),
        "daysort_include_file": "Also move files without metadata (by file date)",
        "daysort_col_day": "Day",
        "daysort_col_file": "File",
        "daysort_col_new": "New name",
        "daysort_nothing": "Nothing to move: all files are already in the right day folder.",
        "daysort_moving": "Moving... {i}/{n}",
        "daysort_done": "{n} files moved into {d} day folders.",
        "daysort_undo_hint": "Undo: Edit → Undo (Ctrl+Z).",
        "daysort_errors": "{n} files could not be moved:\n",
    },
}


# ---------------------------------------------------------------------------
# Megjelenés (a "téma" szó a programban az átnevezési témát jelenti)
# ---------------------------------------------------------------------------
# "system": a gép saját ttk témája és színei (Windowson "vista"), úgy, mint eddig.
# "flat-*": a beépített "clam" ttk téma saját színekkel, nincs külső függőség.
# "sun-valley-*": a Windows 11 stílusú sv-ttk csomag (MIT), ha telepítve van.
APPEARANCES = ("system", "flat-light", "flat-dark", "sun-valley-light", "sun-valley-dark")
DEFAULT_APPEARANCE = "system"
SV_APPEARANCES = ("sun-valley-light", "sun-valley-dark")
# A régi verziók "light" értéket írtak a settings.ini-be, de nem használták semmire
_LEGACY_APPEARANCE = {"light": "system", "dark": "flat-dark"}

# Klasszikus Tk widgetek színei; a ttk widgeteket a ttk téma színezi.
#   canvas/thumb: a bélyegképrács és a bélyegkép háttere, warn: figyelmeztető szöveg
PALETTES = {
    "flat-light": {"bg": "#f3f4f6", "fg": "#1f2328", "field": "#ffffff", "canvas": "#ffffff",
                   "thumb": "#e5e7eb", "button": "#ffffff", "button_active": "#e3ebfa",
                   "border": "#d0d7de", "select_bg": "#2563eb", "select_fg": "#ffffff",
                   "disabled": "#8c959f", "warn": "#a05000"},
    "flat-dark": {"bg": "#1e1f22", "fg": "#e6e6e6", "field": "#2b2d31", "canvas": "#16171a",
                  "thumb": "#2b2d31", "button": "#2b2d31", "button_active": "#3a3d44",
                  "border": "#45484f", "select_bg": "#3b82f6", "select_fg": "#ffffff",
                  "disabled": "#6b6f76", "warn": "#f0a040"},
    # Az sv-ttk saját színei (theme/light.tcl, theme/dark.tcl)
    "sun-valley-light": {"bg": "#fafafa", "fg": "#1c1c1c", "field": "#ffffff", "canvas": "#ffffff",
                         "thumb": "#ececec", "button": "#ffffff", "button_active": "#e8e8e8",
                         "border": "#d0d0d0", "select_bg": "#2f60d8", "select_fg": "#ffffff",
                         "disabled": "#a0a0a0", "warn": "#a05000"},
    "sun-valley-dark": {"bg": "#1c1c1c", "fg": "#fafafa", "field": "#2a2a2a", "canvas": "#202020",
                        "thumb": "#2a2a2a", "button": "#2f2f2f", "button_active": "#3c3c3c",
                        "border": "#454545", "select_bg": "#2f60d8", "select_fg": "#ffffff",
                        "disabled": "#595959", "warn": "#f0a040"},
}
# A "system" megjelenésnél ezek maradnak (a korábbi verziók beégetett színei)
SYSTEM_COLORS = {"canvas": "white", "thumb": "#eeeeee", "warn": "#a05000"}


def normalize_appearance(name, sv_available=True):
    """Ismeretlen vagy nem elérhető megjelenés helyett az alapértelmezettet adja."""
    name = (name or "").strip().lower()
    name = _LEGACY_APPEARANCE.get(name, name)
    if name not in APPEARANCES or (name in SV_APPEARANCES and not sv_available):
        return DEFAULT_APPEARANCE
    return name


def appearance_colors(name):
    """A megjelenés extra színei (canvas, thumb, warn), a "system"-re is."""
    return PALETTES.get(name, SYSTEM_COLORS)


# ---------------------------------------------------------------------------
# Dátumok (GUI-független)
# ---------------------------------------------------------------------------
_EXIF_IFD = 0x8769
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_DATETIME_DIGITIZED = 0x9004
_TAG_DATETIME = 0x0132


def _parse_exif_datetime(value):
    try:
        text = str(value).strip().strip("\x00")[:19]
        dt = datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
        return dt if dt.year >= 1980 else None
    except (ValueError, TypeError):
        return None


_EXIFREAD_TAGS = ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime")


def get_raw_datetime(path):
    """RAW fájl dátuma az exifread csomaggal (a Pillow a legtöbb RAW-ot nem tudja megnyitni)."""
    if exifread is None:
        return None
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception as e:
        print(f"RAW EXIF hiba ({path}): {e}")
        return None
    for name in _EXIFREAD_TAGS:
        dt = _parse_exif_datetime(tags.get(name))
        if dt:
            return dt
    return None


def get_exif_datetime(path):
    """DateTimeOriginal > DateTimeDigitized > DateTime. PNG/TIFF/WebP/HEIC és RAW is jó."""
    if is_raw(path):
        dt = get_raw_datetime(path)
        if dt:
            return dt
        # exifread nélkül vagy ha az nem boldogult vele: a DNG és néhány régebbi RAW TIFF-ként is nyílik
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            sub = exif.get_ifd(_EXIF_IFD)
            for src, tag in ((sub, _TAG_DATETIME_ORIGINAL),
                             (sub, _TAG_DATETIME_DIGITIZED),
                             (exif, _TAG_DATETIME)):
                dt = _parse_exif_datetime(src.get(tag))
                if dt:
                    return dt
    except Exception as e:
        if not is_raw(path):
            print(f"EXIF hiba ({path}): {e}")
    return None


def parse_iso_datetime(text):
    """ISO 8601 dátum (pl. 2023-05-01T10:20:30.000000Z vagy ...+0200), időzóna nélkül.
    Kiírt eltolásnál (iPhone: ...+0200) a felvétel helyén mért időt adja, ahogy a fotók
    EXIF-je is, így külföldön készült fotók és videók ugyanarra az órára és napra esnek.
    A 'Z'/eltolás nélküli értéket UTC-nek veszi (QuickTime szabvány), és a gép helyi idejére váltja."""
    if not text:
        return None
    s = text.strip().replace("Z", "+00:00")
    dt = None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if dt is None or dt.year < 1980:  # 1904/1970 = üres QuickTime mező
        return None
    if dt.tzinfo is not None and not text.strip().upper().endswith("Z"):
        return dt.replace(tzinfo=None)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def ffprobe_available():
    return shutil.which("ffprobe") is not None


def probe_video(path):
    """{'duration': float|None, 'tags': {...}} az ffprobe alapján, vagy üres dict."""
    if not ffprobe_available():
        return {}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:format_tags:stream_tags=creation_time", "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, creationflags=_NO_WINDOW)
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout or "{}")
    except Exception as e:
        print(f"ffprobe hiba ({path}): {e}")
        return {}
    fmt = data.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    for stream in data.get("streams", []):
        ct = (stream.get("tags") or {}).get("creation_time")
        if ct and "creation_time" not in tags:
            tags["creation_time"] = ct
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    return {"duration": duration, "tags": tags}


# --- MP4/MOV fejléc olvasása ffprobe nélkül (ISO BMFF dobozok) ---------------
_QT_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
_MAX_MOOV = 64 * 1024 * 1024  # ennél nagyobb moov doboz gyanús, nem olvassuk be


def _iter_boxes(data, start=0, end=None):
    """(típus, tartalom kezdete, tartalom vége) a data[start:end] dobozaira."""
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size, header = int.from_bytes(data[pos + 8:pos + 16], "big"), 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def _read_moov(path):
    """A fájl legfelső szintű moov dobozának tartalma (a videóadatot átugorja), vagy None."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        pos = 0
        while pos + 8 <= file_size:
            f.seek(pos)
            header = f.read(16)
            size, kind = int.from_bytes(header[:4], "big"), header[4:8]
            hlen = 8
            if size == 1:
                size, hlen = int.from_bytes(header[8:16], "big"), 16
            elif size == 0:
                size = file_size - pos
            if size < hlen:
                return None
            if kind == b"moov":
                if size > _MAX_MOOV:
                    return None
                f.seek(pos + hlen)
                return f.read(size - hlen)
            pos += size
    return None


def _apple_creationdate(moov):
    """moov/meta (vagy moov/udta/meta) keys+ilst: com.apple.quicktime.creationdate
    (helyi idő + eltolás), vagy None."""
    metas = []
    for kind, start, end in _iter_boxes(moov):
        if kind == b"meta":
            metas.append((start, end))
        elif kind == b"udta":
            metas += [(s, e) for k, s, e in _iter_boxes(moov, start, end) if k == b"meta"]
    for start, end in metas:
        # A QuickTime meta doboz nem "full box"; az MP4-es igen (4 bájt verzió/jelzők)
        if moov[start + 4:start + 8] != b"hdlr":
            start += 4
        keys, ilst = [], None
        for sub, s, e in _iter_boxes(moov, start, end):
            if sub == b"keys":
                count = int.from_bytes(moov[s + 4:s + 8], "big")
                p = s + 8
                for _ in range(count):
                    ksize = int.from_bytes(moov[p:p + 4], "big")
                    if ksize < 8:
                        break
                    keys.append(moov[p + 8:p + ksize].decode("utf-8", "replace"))
                    p += ksize
            elif sub == b"ilst":
                ilst = (s, e)
        if not ilst:
            continue
        for item, s, e in _iter_boxes(moov, *ilst):
            index = int.from_bytes(item, "big")
            if not 1 <= index <= len(keys) or keys[index - 1] != "com.apple.quicktime.creationdate":
                continue
            for sub, ds, de in _iter_boxes(moov, s, e):
                if sub == b"data":
                    return moov[ds + 8:de].decode("utf-8", "replace").strip("\x00 ")
    return None


def read_bmff_metadata(path):
    """MP4/MOV/3GP fejléc: {'creation_time': ISO szöveg (UTC) | None,
    'apple_date': ISO szöveg eltolással | None, 'duration': mp | None}. Hiba esetén üres dict."""
    try:
        moov = _read_moov(path)
    except OSError:
        return {}
    if not moov:
        return {}
    result = {"creation_time": None, "apple_date": None, "duration": None}
    for kind, start, end in _iter_boxes(moov):
        if kind == b"mvhd" and end - start >= 32:
            version = moov[start]
            if version == 1:
                created = int.from_bytes(moov[start + 4:start + 12], "big")
                timescale = int.from_bytes(moov[start + 20:start + 24], "big")
                duration = int.from_bytes(moov[start + 24:start + 32], "big")
            else:
                created = int.from_bytes(moov[start + 4:start + 8], "big")
                timescale = int.from_bytes(moov[start + 12:start + 16], "big")
                duration = int.from_bytes(moov[start + 16:start + 20], "big")
            if created:
                try:
                    dt = _QT_EPOCH + timedelta(seconds=created)
                    result["creation_time"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except OverflowError:
                    pass
            if timescale:
                result["duration"] = duration / timescale
    try:
        result["apple_date"] = _apple_creationdate(moov)
    except (IndexError, ValueError):
        pass
    return result


def get_video_datetime(path):
    if path.lower().endswith(BMFF_EXTS):
        # Gyors út, ffprobe nélkül is működik (Windowson ritkán van ffmpeg telepítve)
        meta = read_bmff_metadata(path)
        for value in (meta.get("apple_date"), meta.get("creation_time")):
            dt = parse_iso_datetime(value)
            if dt:
                return dt
    tags = probe_video(path).get("tags", {})
    # Az iPhone helyi időt + eltolást ír ide, ez megbízhatóbb a UTC creation_time-nál
    for key in ("com.apple.quicktime.creationdate", "creation_time", "date"):
        dt = parse_iso_datetime(tags.get(key))
        if dt:
            return dt
    return None


def get_file_datetime(path):
    """Fájlrendszer-dátum. Linuxon a ctime NEM létrehozási idő, ezért a
    születési időt (ha van) és a módosítási időt vesszük, a korábbit."""
    st = os.stat(path)
    candidates = [st.st_mtime]
    birth = getattr(st, "st_birthtime", None)
    if birth:
        candidates.append(birth)
    elif IS_WINDOWS:
        candidates.append(st.st_ctime)  # régebbi Pythonon Windowson ez a létrehozás
    return datetime.fromtimestamp(min(candidates))


def get_media_datetime(path):
    """(datetime, forrás) ahol forrás: 'exif' | 'video' | 'file'. Mindig ad dátumot."""
    if is_video(path):
        dt = get_video_datetime(path)
        if dt:
            return dt, "video"
    else:
        dt = get_exif_datetime(path)
        if dt:
            return dt, "exif"
    return get_file_datetime(path), "file"


# ---------------------------------------------------------------------------
# Névsablon és átnevezési terv (GUI-független)
# ---------------------------------------------------------------------------
PATTERN_FIELDS = {"date", "day", "time", "suffix", "counter", "seq", "original"}
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_COUNTER_MARK = "\x00CNT\x00"


def sanitize_component(text):
    """Fájlnévben tiltott karakterek cseréje (Windows-szabályok szerint)."""
    return _INVALID_CHARS.sub("-", text).strip().rstrip(".")


def validate_pattern(pattern):
    """None, ha jó; különben hibaüzenet."""
    if not pattern or not pattern.strip():
        return "üres / empty"
    try:
        parsed = [(f, spec, conv) for _, f, spec, conv in string.Formatter().parse(pattern) if f is not None]
    except ValueError as e:
        return str(e)
    fields = {f for f, _, _ in parsed}
    unknown = fields - PATTERN_FIELDS
    if unknown:
        return "ismeretlen mező / unknown field: " + ", ".join("{%s}" % f for f in sorted(unknown))
    if "" in fields:
        return "üres {} mező / empty {} field"
    # Minden mező kész szöveg, ezért a {seq:05d}, {date:%Y} vagy {date!r} alak átnevezéskor elszállna
    bad = [f for f, spec, conv in parsed if spec or conv]
    if bad:
        return "formázás nem használható / format spec not allowed: " + ", ".join("{%s}" % f for f in bad)
    if _INVALID_CHARS.search(re.sub(r"\{[^}]*\}", "", pattern)):
        return 'tiltott karakter / invalid character: < > : " / \\ | ? *'
    return None


def render_name(pattern, dt, suffix, counter=0, seq=1, original="", ext=""):
    values = {
        "date": dt.strftime("%Y-%m-%d_%H-%M-%S"),
        "day": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H-%M-%S"),
        "suffix": sanitize_component(suffix),
        "seq": f"{seq:03d}",
        "original": sanitize_component(original),
        "counter": _COUNTER_MARK,
    }
    name = pattern.format(**values)
    if counter:
        name = name.replace(_COUNTER_MARK, str(counter))
    else:
        # A 0-s számlálót a előtte álló elválasztóval együtt elhagyjuk: a_b_{counter} -> a_b
        name = re.sub(r"[_\-. ]?" + re.escape(_COUNTER_MARK), "", name)
    if counter and "{counter}" not in pattern:
        name = f"{name}_{counter}"
    name = sanitize_component(name).strip(" _-") or "media"
    return name + ext


def _key(path):
    # Mindig kis/nagybetű-függetlenül hasonlítunk (a.jpg és a.JPG Windowson/exFAT-on ugyanaz)
    return os.path.normcase(os.path.abspath(path)).casefold()


def _is_free_for(new_path, path, exists=os.path.exists):
    """Igaz, ha a new_path szabad, vagy maga a forrásfájl (pl. csak kis/nagybetű változik)."""
    if not exists(new_path):
        return True
    try:
        return os.path.samefile(new_path, path)
    except OSError:
        return False


def plan_renames(items, suffix, pattern, target_dir=None, exists=os.path.exists):
    """items: [(útvonal, datetime)] -> [(régi, új)].
    A tervezett nevek egymással és a lemezen lévő fájlokkal sem ütközhetnek."""
    items = sorted(items, key=lambda it: (it[1], it[0]))
    reserved = set()
    plan = []
    for seq, (path, dt) in enumerate(items, 1):
        folder = target_dir or os.path.dirname(path)
        stem, ext = os.path.splitext(os.path.basename(path))
        counter = 0
        while True:
            new_path = os.path.join(folder, render_name(pattern, dt, suffix, counter, seq, stem, ext))
            k = _key(new_path)
            if k not in reserved and _is_free_for(new_path, path, exists):
                break
            counter += 1
        reserved.add(k)
        plan.append((path, new_path))
    return plan


def execute_plan(plan, progress=None):
    """Végrehajtja a tervet. Vissza: (kész [(régi, új)], változatlan db, hibák)."""
    done, unchanged, errors = [], 0, []
    for i, (old, new) in enumerate(plan, 1):
        if progress:
            progress(i, len(plan))
        try:
            if old == new:
                unchanged += 1
                continue
            # POSIX-on az os.rename csendben felülírna, ezért közvetlenül előtte is ellenőrzünk
            if not _is_free_for(new, old):
                raise FileExistsError(new)
            if os.path.dirname(_key(old)) == os.path.dirname(_key(new)):
                os.rename(old, new)
            else:
                shutil.move(old, new)
            done.append((old, new))
        except Exception as e:
            errors.append(f"{os.path.basename(old)}: {e}")
    return done, unchanged, errors


def scan_media(folder, recursive=True):
    files = []
    if recursive:
        for root, dirs, names in os.walk(folder):
            dirs.sort()
            files.extend(os.path.join(root, n) for n in sorted(names) if is_media(n))
    else:
        files = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                 if is_media(n) and os.path.isfile(os.path.join(folder, n))]
    return files


# ---------------------------------------------------------------------------
# Rendezés napok szerint: base/ÉÉÉÉ-HH-NN/eredeti_név (GUI-független)
# ---------------------------------------------------------------------------
def day_folder(base_folder, dt):
    return os.path.join(base_folder, dt.strftime("%Y-%m-%d"))


def plan_day_sort(items, base_folder, exists=os.path.exists):
    """items: [(útvonal, datetime)] -> (terv [(régi, új)], már a helyén lévők száma).
    A fájlnév marad; ütközéskor _1, _2... kerül a név végére. A már a helyes
    napi mappában lévő fájlok kimaradnak a tervből."""
    reserved = set()
    plan, in_place = [], 0
    for path, dt in sorted(items, key=lambda it: (it[1], it[0])):
        folder = day_folder(base_folder, dt)
        if _key(os.path.dirname(path)) == _key(folder):
            in_place += 1
            reserved.add(_key(path))
            continue
        stem, ext = os.path.splitext(os.path.basename(path))
        counter = 0
        while True:
            name = f"{stem}_{counter}{ext}" if counter else stem + ext
            new_path = os.path.join(folder, name)
            k = _key(new_path)
            if k not in reserved and not exists(new_path):
                break
            counter += 1
        reserved.add(k)
        plan.append((path, new_path))
    return plan, in_place


def execute_day_sort(plan, progress=None):
    """Létrehozza a hiányzó napi mappákat, majd áthelyez (felülírás nélkül).
    Vissza: (kész [(régi, új)], hibák, létrehozott mappák)."""
    created, errors = [], []
    for folder in sorted({os.path.dirname(new) for _, new in plan}):
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder)
                created.append(folder)
            except OSError as e:
                errors.append(f"{os.path.basename(folder)}: {e}")
    done, _, move_errors = execute_plan(plan, progress)
    return done, errors + move_errors, created


def remove_empty_folders(folders):
    """A visszavonás után üresen maradt (általunk létrehozott) mappák törlése."""
    for folder in sorted(folders, key=len, reverse=True):
        try:
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Bélyegképek (háttérszálban csak PIL kép készül, PhotoImage a fő szálon)
# ---------------------------------------------------------------------------
class ThumbnailGenerator:
    _icon = None
    _icon_lock = threading.Lock()

    @staticmethod
    def generate(path, size=THUMB_SIZE):
        try:
            if is_video(path):
                return ThumbnailGenerator._video(path, size)
            return ThumbnailGenerator._image(path, size)
        except Exception as e:
            print(f"Bélyegkép hiba ({path}): {e}")
            return Image.new('RGB', size, color='gray')

    @staticmethod
    def _raw_preview(path):
        """A RAW fájlba ágyazott JPEG előnézet (rawpy), vagy az EXIF kis bélyegképe (exifread)."""
        if rawpy is not None:
            try:
                with rawpy.imread(path) as raw:
                    thumb, flip = raw.extract_thumb(), raw.sizes.flip
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    img = Image.open(io.BytesIO(thumb.data))
                else:
                    img = Image.fromarray(thumb.data)
                # Az előnézetben gyakran nincs tájolás; ilyenkor a RAW saját forgatása (LibRaw flip) érvényes
                transpose = {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90,
                             6: Image.Transpose.ROTATE_270}.get(flip)
                if transpose is not None and not img.getexif().get(0x0112):
                    img = img.transpose(transpose)
                return img
            except Exception as e:
                print(f"rawpy hiba ({path}): {e}")
        if exifread is not None:
            try:
                with open(path, "rb") as f:
                    data = exifread.process_file(f, details=True).get("JPEGThumbnail")
                if data:
                    return Image.open(io.BytesIO(data))
            except Exception as e:
                print(f"RAW előnézet hiba ({path}): {e}")
        return None

    @staticmethod
    def _image(path, size):
        if is_raw(path):
            img = ThumbnailGenerator._raw_preview(path)
            if img is not None:
                img = ImageOps.exif_transpose(img)
                img.thumbnail(size)
                return img.convert("RGB")
        with Image.open(path) as img:
            img.draft("RGB", (size[0] * 2, size[1] * 2))  # gyors JPEG-dekódolás
            img = ImageOps.exif_transpose(img)  # álló fotók helyes forgatása
            img.thumbnail(size)
            return img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img.copy()

    @staticmethod
    def _video_icon():
        with ThumbnailGenerator._icon_lock:
            if ThumbnailGenerator._icon is None:
                try:
                    icon = Image.open(resource_path("media.png")).convert("RGBA")
                    icon.thumbnail((32, 32))
                    ThumbnailGenerator._icon = icon
                except Exception as e:
                    print(f"Ikon hiba: {e}")
                    ThumbnailGenerator._icon = False
            return ThumbnailGenerator._icon

    @staticmethod
    def _grab_frame(path, seconds):
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{seconds:.2f}", "-i", path,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
            capture_output=True, timeout=60, creationflags=_NO_WINDOW)
        return result.stdout

    @staticmethod
    def _video(path, size):
        if not shutil.which("ffmpeg"):
            return Image.new('RGB', size, color='gray')
        duration = None
        if path.lower().endswith(BMFF_EXTS):
            duration = read_bmff_metadata(path).get("duration")
        if duration is None:
            duration = probe_video(path).get("duration")
        # 5 mp-nél rövidebb videónál a régi fix 5 mp-es pozíció üres képet adott
        pos = min(5.0, duration * 0.1) if duration else 0.0
        out = ThumbnailGenerator._grab_frame(path, pos)
        if not out and pos > 0:
            out = ThumbnailGenerator._grab_frame(path, 0)
        if not out:
            return Image.new('RGB', size, color='gray')
        img = Image.open(io.BytesIO(out))
        img.thumbnail(size)
        img = img.convert("RGBA")
        icon = ThumbnailGenerator._video_icon()
        if icon:
            img.paste(icon, (0, 0), icon)
        return img.convert("RGB")


class AsyncThumbnailLoader:
    """Munkaszálak, amelyek PIL képet adnak vissza egy callback-en keresztül.
    A callback-et a hívó (GUI) köteles a fő szálra továbbítani."""

    def __init__(self, max_workers=4):
        self.queue = queue.Queue()
        self.max_workers = max_workers
        self.stop_flag = threading.Event()
        self.generation = 0

    def add_task(self, file_path, callback):
        self.queue.put((self.generation, file_path, callback))

    def clear(self):
        """Új mappa betöltésekor a régi, még fel nem dolgozott feladatok eldobása."""
        self.generation += 1
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass

    def start(self):
        for _ in range(self.max_workers):
            threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while not self.stop_flag.is_set():
            try:
                gen, file_path, callback = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if gen != self.generation:
                continue
            img = ThumbnailGenerator.generate(file_path)
            if gen == self.generation and not self.stop_flag.is_set():
                callback(img)

    def stop(self):
        # Nem várunk a szálakra: egy lassú ffmpeg ne akassza meg a kilépést (daemon szálak)
        self.stop_flag.set()


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class ScrollableCanvas(tk.Frame):
    CELL_WIDTH = 170

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner_frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner_frame, anchor="nw", tags="inner_frame")
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.inner_frame.bind("<Configure>", self.on_inner_configure)

        self.check_vars = []
        self.thumb_labels = []
        self._cols = None
        self.bind_mousewheel(self.canvas)

    def on_canvas_configure(self, event):
        self.canvas.itemconfig("inner_frame", width=event.width)
        self.update_layout()

    def on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def update_layout(self, force=False):
        cols = max(1, self.canvas.winfo_width() // self.CELL_WIDTH)
        if cols == self._cols and not force:
            return
        self._cols = cols
        for idx, widget in enumerate(self.inner_frame.winfo_children()):
            widget.grid(row=idx // cols, column=idx % cols, padx=5, pady=5)

    def bind_mousewheel(self, widget):
        if IS_WINDOWS or IS_MAC:
            widget.bind_all("<MouseWheel>", self._on_mousewheel)
        else:
            widget.bind_all("<Button-4>", self._on_mousewheel)
            widget.bind_all("<Button-5>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        # Csak a főablakban görgessen (ne a párbeszédablakok vagy a lejátszó fölött)
        try:
            if event.widget.winfo_toplevel() is not self.winfo_toplevel():
                return
        except Exception:
            return
        if IS_WINDOWS:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif IS_MAC:
            self.canvas.yview_scroll(int(-1 * event.delta), "units")
        elif event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")


def _config_dir():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "MediaRenamerPro")


class SettingsManager:
    def __init__(self, config_file=None):
        self.config = configparser.ConfigParser(interpolation=None)
        self.config_file = config_file or os.path.join(_config_dir(), 'settings.ini')
        self.load_settings()

    def load_settings(self):
        # Régi verzió az aktuális mappába írta a settings.ini-t: azt is beolvassuk
        legacy = os.path.abspath('settings.ini')
        self.config.read([legacy, self.config_file], encoding="utf-8")
        for section, defaults in (
                ('UI', {'theme': DEFAULT_APPEARANCE, 'language': 'hu', 'recursive': 'yes', 'last_folder': ''}),
                ('Naming', {'pattern': DEFAULT_PATTERN, 'recent_suffixes': '[]'})):
            if not self.config.has_section(section):
                self.config.add_section(section)
            for key, value in defaults.items():
                if not self.config.has_option(section, key):
                    self.config.set(section, key, value)
        if validate_pattern(self.pattern):
            self.config['Naming']['pattern'] = DEFAULT_PATTERN

    def save_settings(self):
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding="utf-8") as f:
                self.config.write(f)
        except OSError as e:
            print(f"Beállítások mentési hiba: {e}")

    @property
    def pattern(self):
        return self.config['Naming']['pattern']

    @property
    def appearance(self):
        return normalize_appearance(self.config['UI']['theme'], sv_ttk is not None)

    @appearance.setter
    def appearance(self, name):
        self.config['UI']['theme'] = normalize_appearance(name)

    @property
    def language(self):
        lang = self.config['UI']['language']
        return lang if lang in TEXTS else 'hu'

    @property
    def recent_suffixes(self):
        try:
            value = json.loads(self.config['Naming']['recent_suffixes'])
            return [s for s in value if isinstance(s, str)]
        except (ValueError, TypeError):
            return []

    @recent_suffixes.setter
    def recent_suffixes(self, values):
        self.config['Naming']['recent_suffixes'] = json.dumps(values[:15], ensure_ascii=False)


class ImageRenamerGUI(_BaseTk):
    def __init__(self):
        super().__init__()
        self.settings = SettingsManager()
        self.lang = self.settings.language
        # A gép saját megjelenése, mielőtt bármit átszíneznénk (a "Rendszer" visszaállításához)
        self.style = ttk.Style(self)
        self._native_ttk_theme = self.style.theme_use()
        self._system_palette, self._system_widget_options = self._capture_system_look()
        self.appearance = DEFAULT_APPEARANCE
        self.colors = SYSTEM_COLORS
        self.appearance_var = tk.StringVar(value=self.settings.appearance)
        self.title(APP_NAME)
        self.geometry("1000x700")
        self.minsize(800, 600)

        # Háttérszálak -> fő szál üzenetsor (Tk widgetet csak a fő szál érinthet)
        self._ui_queue = queue.Queue()
        self.after(50, self._process_ui_queue)

        # VLC inicializálás (opcionális; macOS-en a Tk ablakba ágyazás nem működik)
        self.vlc_instance = None
        if vlc is not None and not IS_MAC:
            try:
                self.vlc_instance = vlc.Instance(['--quiet'] + ([] if IS_WINDOWS else ['--no-xlib']))
            except Exception as e:
                print(f"VLC hiba: {e}")
        self.vlc_player = None
        self.video_window = None

        self.scrollable_canvas = ScrollableCanvas(self)
        self.btn_frame = tk.Frame(self)
        self.status_bar = tk.Label(self, text=self.t("ready"), bd=1, relief=tk.SUNKEN, anchor=tk.W)

        self.scrollable_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.icons = {key: self.load_icon(name) for key, name in {
            "folder": "folder.png", "rename": "rename.png", "refresh": "refresh.png",
            "unmark": "unmark.png", "markall": "MarkAll.png", "delete": "delete.png",
            "exit": "exit.png"}.items()}

        self.recursive_var = tk.BooleanVar(value=self.settings.config.getboolean('UI', 'recursive'))
        self.setup_menu()
        # Csak a főablakban: a téma beírása közben a Ctrl+Z ne az utolsó átnevezést vonja vissza
        for seq in ("<Control-z>", "<Control-Z>"):
            self.bind_all(seq, self._on_undo_key)

        self.exit_button = tk.Button(self.btn_frame, text=self.t("btn_exit"), image=self.icons["exit"],
                                     compound="left", command=self.on_close)
        self.exit_button.pack(side=tk.RIGHT, padx=2)
        self.delete_button = tk.Button(self.btn_frame, text=self.t("btn_delete"), image=self.icons["delete"],
                                       compound="left", command=self.delete_selected)
        self.delete_button.pack(side=tk.RIGHT, padx=2)
        # A jobb oldali gombok kerülnek be először, így keskeny ablakban sem tűnik el a Törlés
        self.action_buttons = [self.delete_button]
        for text, cmd, icon_key in [
            ("btn_folder", self.select_folder, "folder"),
            ("btn_rename", self.rename_selected, "rename"),
            ("btn_refresh", self.load_media, "refresh"),
            ("btn_markall", self.mark_all, "markall"),
            ("btn_unmark", self.unmark_all, "unmark"),
        ]:
            btn = tk.Button(self.btn_frame, text=self.t(text), image=self.icons[icon_key],
                            compound="left", command=cmd)
            btn.pack(side=tk.LEFT, padx=2)
            self.action_buttons.append(btn)

        self.files = []
        self.prev_suffixes = self.settings.recent_suffixes
        self.last_rename = []  # [(régi, új)] a visszavonáshoz
        self.last_created_folders = []  # a visszavonáskor törlendő, általunk létrehozott mappák
        self.busy = False
        self.running = True
        self.folder = ""
        self.async_loader = AsyncThumbnailLoader()
        self.async_loader.start()

        self.daysort_button = tk.Button(self.btn_frame, text=self.t("btn_daysort"), image=self.icons["folder"],
                                        compound="left", padx=4, command=self.sort_by_day)
        self.daysort_button.pack(side=tk.LEFT, padx=2)
        self.action_buttons.append(self.daysort_button)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if HAS_DND:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind('<<Drop>>', self._on_drop)
            except Exception as e:
                print(f"Fogd és vidd hiba: {e}")

        self.bind_class("Toplevel", "<Map>", self._on_toplevel_map, add="+")
        self.apply_appearance(self.settings.appearance)

        last = self.settings.config['UI'].get('last_folder', '')
        if last and os.path.isdir(last):
            self.folder = last
            self.load_media()

    # --- segédek -----------------------------------------------------------
    def t(self, key, **kwargs):
        text = TEXTS[self.lang].get(key) or TEXTS["hu"].get(key, key)
        return text.format(**kwargs) if kwargs else text

    def _on_undo_key(self, event):
        try:
            if event.widget.winfo_toplevel() is not self or isinstance(event.widget, (tk.Entry, ttk.Entry)):
                return
        except (AttributeError, KeyError, tk.TclError):
            return
        self.undo_last()

    def call_in_ui(self, func, *args):
        """Szálbiztos: bármely szálból hívható, a func a fő szálon fut le."""
        self._ui_queue.put((func, args))

    def _process_ui_queue(self):
        try:
            for _ in range(200):  # egy körben korlátozott mennyiség, hogy a GUI reagáljon
                func, args = self._ui_queue.get_nowait()
                try:
                    func(*args)
                except Exception as e:
                    print(f"GUI frissítési hiba: {e}")
        except queue.Empty:
            pass
        if self.running:
            self.after(50, self._process_ui_queue)

    def set_status(self, text):
        self.status_bar.config(text=text)

    def set_busy(self, busy):
        self.busy = busy
        for btn in self.action_buttons:
            btn.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.config(cursor="watch" if busy else "")

    def run_in_background(self, work, done=None):
        """work() háttérszálban; done(eredmény) a fő szálon. Közben a gombok tiltva."""
        self.set_busy(True)

        def runner():
            try:
                result, error = work(), None
            except Exception as e:
                result, error = None, e
            self.call_in_ui(self._finish_background, done, result, error)

        threading.Thread(target=runner, daemon=True).start()

    def _finish_background(self, done, result, error):
        self.set_busy(False)
        if error:
            self.show_error(str(error))
        elif done:
            done(result)

    def load_icon(self, path, default_size=(32, 32)):
        try:
            return tk.PhotoImage(file=resource_path(path))
        except Exception as e:
            print(f"Ikonhiba ({path}): {e}")
            return ImageTk.PhotoImage(Image.new('RGB', default_size, color='gray'))

    def setup_menu(self):
        menu = tk.Menu(self)
        config_menu = tk.Menu(menu, tearoff=0)
        config_menu.add_command(label=self.t("menu_templates"), image=self.icons["rename"],
                                compound="left", command=self.edit_templates)
        config_menu.add_command(label=self.t("menu_language"), image=self.icons["folder"],
                                compound="left", command=self.set_language)
        appearance_menu = tk.Menu(config_menu, tearoff=0)
        for name in APPEARANCES:
            available = sv_ttk is not None or name not in SV_APPEARANCES
            label = self.t("appearance_" + name) + ("" if available else self.t("appearance_needs_sv"))
            appearance_menu.add_radiobutton(label=label, value=name, variable=self.appearance_var,
                                            command=self._on_appearance_select,
                                            state=tk.NORMAL if available else tk.DISABLED)
        config_menu.add_cascade(label=self.t("menu_appearance"), menu=appearance_menu)
        config_menu.add_separator()
        config_menu.add_checkbutton(label=self.t("chk_recursive"), variable=self.recursive_var,
                                    command=self._on_recursive_toggle)
        menu.add_cascade(label=self.t("menu_settings"), menu=config_menu)
        edit_menu = tk.Menu(menu, tearoff=0)
        edit_menu.add_command(label=self.t("btn_undo"), accelerator="Ctrl+Z", command=self.undo_last)
        edit_menu.add_command(label=self.t("btn_daysort"), command=self.sort_by_day)
        menu.add_cascade(label=self.t("menu_edit"), menu=edit_menu)
        self.config(menu=menu)

    # --- beállítások -------------------------------------------------------
    def edit_templates(self):
        template = simpledialog.askstring(self.t("tpl_title"), self.t("tpl_prompt"),
                                          initialvalue=self.settings.pattern, parent=self)
        if not template:
            return
        error = validate_pattern(template)
        if error:
            self.show_error(self.t("tpl_invalid", err=error))
            return
        self.settings.config['Naming']['pattern'] = template
        self.settings.save_settings()
        example = render_name(template, datetime(2024, 5, 1, 14, 30, 0), "Balaton", 0, 1, "IMG_1234", ".jpg")
        self.show_info(self.t("info"), self.t("tpl_saved", example=example))

    def set_language(self):
        lang = simpledialog.askstring(self.t("lang_title"), self.t("lang_prompt"),
                                      initialvalue=self.lang, parent=self)
        if lang and lang.strip().lower() in TEXTS:
            self.settings.config['UI']['language'] = lang.strip().lower()
            self.settings.save_settings()
            messagebox.showinfo(self.t("info"), self.t("restart"))

    def _on_appearance_select(self):
        self.apply_appearance(self.appearance_var.get())
        self.settings.appearance = self.appearance
        self.settings.save_settings()

    # --- megjelenés --------------------------------------------------------
    # A klasszikus Tk widgetek extra beállításai megjelenésenként (a színeken túl)
    _WIDGET_OPTIONS = {
        "Button": ("background", "activebackground", "foreground", "activeforeground", "relief",
                   "overrelief", "borderwidth", "highlightthickness", "highlightbackground",
                   "highlightcolor"),
        "Checkbutton": ("selectcolor", "activebackground", "highlightthickness"),
        "Menu": ("selectcolor", "activebackground", "activeforeground"),
    }

    def _capture_system_look(self):
        """Az alapértelmezett Tk színek és widgetbeállítások, mielőtt bármit átírnánk."""
        b, e, sb = tk.Button(self), tk.Entry(self), tk.Scrollbar(self)
        palette = {"background": b.cget("background"), "foreground": b.cget("foreground"),
                   "activeBackground": b.cget("activebackground"),
                   "activeForeground": b.cget("activeforeground"),
                   "highlightBackground": b.cget("highlightbackground"),
                   "highlightColor": b.cget("highlightcolor"),
                   "disabledForeground": b.cget("disabledforeground"),
                   "selectBackground": e.cget("selectbackground"),
                   "selectForeground": e.cget("selectforeground"),
                   "insertBackground": e.cget("insertbackground"),
                   "troughColor": sb.cget("troughcolor")}
        protos = {"Button": b, "Checkbutton": tk.Checkbutton(self), "Menu": tk.Menu(self, tearoff=0)}
        options = {cls: {opt: str(protos[cls].cget(opt)) for opt in opts}
                   for cls, opts in self._WIDGET_OPTIONS.items()}
        for w in (e, sb, *protos.values()):
            w.destroy()
        return palette, options

    @staticmethod
    def _tk_palette(c):
        return {"background": c["bg"], "foreground": c["fg"], "activeBackground": c["button_active"],
                "activeForeground": c["fg"], "highlightBackground": c["bg"],
                "highlightColor": c["select_bg"], "disabledForeground": c["disabled"],
                "selectBackground": c["select_bg"], "selectForeground": c["select_fg"],
                "insertBackground": c["fg"], "troughColor": c["bg"]}

    @staticmethod
    def _widget_options(c):
        return {
            # Lapos gombok vékony kerettel; a keretet a highlight rajzolja, ez minden rendszeren működik
            "Button": {"background": c["button"], "activebackground": c["button_active"],
                       "foreground": c["fg"], "activeforeground": c["fg"], "relief": "flat",
                       "overrelief": "flat", "borderwidth": "0", "highlightthickness": "1",
                       "highlightbackground": c["border"], "highlightcolor": c["select_bg"]},
            "Checkbutton": {"selectcolor": c["field"], "activebackground": c["bg"],
                            "highlightthickness": "0"},
            "Menu": {"selectcolor": c["fg"], "activebackground": c["select_bg"],
                     "activeforeground": c["select_fg"]},
        }

    def _style_flat_ttk(self, c):
        """A beépített "clam" ttk téma átszínezése (Világos/Sötét)."""
        st = self.style
        st.theme_use("clam")
        st.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                     bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"],
                     troughcolor=c["bg"], selectbackground=c["select_bg"],
                     selectforeground=c["select_fg"], insertcolor=c["fg"], focuscolor=c["select_bg"],
                     arrowcolor=c["fg"])
        st.map(".", foreground=[("disabled", c["disabled"])], background=[("disabled", c["bg"])])
        st.configure("TButton", background=c["button"], lightcolor=c["button"], darkcolor=c["button"],
                     bordercolor=c["border"], padding=(10, 4))
        st.map("TButton",
               background=[("pressed", c["select_bg"]), ("active", c["button_active"])],
               foreground=[("disabled", c["disabled"]), ("pressed", c["select_fg"])],
               lightcolor=[("pressed", c["select_bg"]), ("active", c["button_active"])],
               darkcolor=[("pressed", c["select_bg"]), ("active", c["button_active"])],
               bordercolor=[("focus", c["select_bg"])])
        st.configure("TCheckbutton", indicatorbackground=c["field"], indicatorforeground=c["fg"])
        st.map("TCheckbutton", background=[("active", c["bg"])],
               indicatorbackground=[("pressed", c["button_active"]), ("selected", c["select_bg"])],
               indicatorforeground=[("selected", c["select_fg"])])
        st.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"], insertcolor=c["fg"],
                     lightcolor=c["field"], darkcolor=c["field"])
        st.map("TEntry", bordercolor=[("focus", c["select_bg"])], lightcolor=[("focus", c["select_bg"])])
        st.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["fg"])
        st.map("Treeview", background=[("selected", c["select_bg"])],
               foreground=[("selected", c["select_fg"])])
        st.configure("Treeview.Heading", background=c["button"], foreground=c["fg"],
                     lightcolor=c["button"], darkcolor=c["button"], bordercolor=c["border"])
        st.map("Treeview.Heading", background=[("active", c["button_active"])])
        st.configure("TScrollbar", background=c["button"], troughcolor=c["bg"], bordercolor=c["border"],
                     lightcolor=c["button"], darkcolor=c["button"], arrowcolor=c["fg"])
        st.map("TScrollbar", background=[("active", c["button_active"]), ("pressed", c["select_bg"])])

    def apply_appearance(self, name):
        """Megjelenés váltása futás közben, újraindítás nélkül."""
        name = normalize_appearance(name, sv_ttk is not None)
        if name in SV_APPEARANCES:
            sv_ttk.set_theme("dark" if name.endswith("dark") else "light", root=self)
        elif name == "system":
            self.style.theme_use(self._native_ttk_theme)
        else:
            self._style_flat_ttk(PALETTES[name])
        # Az sv-ttk a <<ThemeChanged>> eseményre maga is átszínez: fusson le előbb,
        # hogy a lenti beállítások legyenek a végsők
        self.update_idletasks()
        self.update()

        colors = appearance_colors(name)
        if name == "system":
            palette, options = self._system_palette, self._system_widget_options
        else:
            palette, options = self._tk_palette(colors), self._widget_options(colors)
        args = []
        for key, value in palette.items():
            args += [key, value]
        self.tk.call("tk_setPalette", *args)
        self._apply_widget_options(options)

        self.scrollable_canvas.canvas.configure(bg=colors["canvas"])
        # "Rendszer" módban marad a régi kinézet (szürke rács a fehér vásznon)
        inner_bg = palette["background"] if name == "system" else colors["canvas"]
        self.scrollable_canvas.inner_frame.configure(bg=inner_bg)
        for lbl in self.scrollable_canvas.thumb_labels:
            if lbl.winfo_exists():
                lbl.configure(bg=colors["thumb"])
        self.appearance, self.colors = name, colors
        self.appearance_var.set(name)
        for w in self._walk(self):
            if isinstance(w, (tk.Tk, tk.Toplevel)):
                self._set_titlebar_dark(w)

    @staticmethod
    def _walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from ImageRenamerGUI._walk(child)

    def _apply_widget_options(self, options):
        """A meglévő widgetekre is, és az option adatbázisba is (az ezután nyíló ablakoknak)."""
        for w in self._walk(self):
            values = options.get(w.winfo_class())
            if values:
                try:
                    w.configure(**values)
                except tk.TclError:
                    pass
        for cls, values in options.items():
            for opt, value in values.items():
                db_name = self._db_names.get(opt, opt)
                # A tk_setPalette a meglévő osztályokra 60-as prioritással ír, ez legyen erősebb
                self.option_add(f"*{cls}.{db_name}", value, 70)

    _db_names = {"activebackground": "activeBackground", "activeforeground": "activeForeground",
                 "overrelief": "overRelief", "borderwidth": "borderWidth",
                 "highlightthickness": "highlightThickness", "highlightbackground": "highlightBackground",
                 "highlightcolor": "highlightColor", "selectcolor": "selectColor"}

    @property
    def is_dark(self):
        return self.appearance.endswith("dark")

    def _on_toplevel_map(self, event):
        if isinstance(event.widget, tk.Toplevel):
            self._set_titlebar_dark(event.widget)

    def _set_titlebar_dark(self, window):
        """Windows 10/11: sötét címsor a sötét megjelenésekhez (máshol nem csinál semmit)."""
        if not IS_WINDOWS:
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1 if self.is_dark else 0)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE; a Windows 10 régebbi kiadásain 19
            for attribute in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            pass

    def _on_recursive_toggle(self):
        if self.busy:
            # Most nem tölthető újra a lista: ne mutasson mást a pipa, mint amit a lista
            self.recursive_var.set(not self.recursive_var.get())
            self.show_info(self.t("info"), self.t("busy"))
            return
        self.settings.config['UI']['recursive'] = 'yes' if self.recursive_var.get() else 'no'
        self.settings.save_settings()
        self.load_media()

    # --- betöltés ----------------------------------------------------------
    def _on_drop(self, event):
        paths = self.tk.splitlist(event.data)
        if not paths:
            return
        target = paths[0] if os.path.isdir(paths[0]) else os.path.dirname(paths[0])
        if os.path.isdir(target):
            self._open_folder(target)

    def select_folder(self):
        folder = filedialog.askdirectory(title=self.t("choose_folder"), initialdir=self.folder or None)
        if folder:
            self._open_folder(folder)

    def _open_folder(self, folder):
        self.folder = os.path.normpath(folder)
        self.settings.config['UI']['last_folder'] = self.folder
        self.settings.save_settings()
        self.load_media()

    def load_media(self):
        """A mappa beolvasása háttérszálban (a Frissítés gomb sem fagyasztja le a GUI-t)."""
        if not self.folder:
            self.show_info(self.t("info"), self.t("no_folder"))
            return
        if self.busy:
            return
        self.set_status(self.t("loading"))
        folder, recursive = self.folder, self.recursive_var.get()

        def work():
            try:
                return scan_media(folder, recursive)
            except OSError as e:
                raise RuntimeError(self.t("load_error", err=e))

        self.run_in_background(work, self.update_gui)

    def clear_gui(self):
        self.async_loader.clear()
        for widget in self.scrollable_canvas.inner_frame.winfo_children():
            widget.destroy()
        self.scrollable_canvas.check_vars.clear()
        self.scrollable_canvas.thumb_labels.clear()
        self.scrollable_canvas.canvas.yview_moveto(0)

    def update_gui(self, files):
        self.clear_gui()
        self.files = files
        inner_frame = self.scrollable_canvas.inner_frame

        for path in files:
            frame = tk.Frame(inner_frame, width=160, height=180)
            frame.grid_propagate(False)

            lbl = tk.Label(frame, bg=self.colors["thumb"])
            lbl.place(x=0, y=0, width=150, height=150)
            self.scrollable_canvas.thumb_labels.append(lbl)
            self.async_loader.add_task(path, partial(self.call_in_ui, self._set_thumbnail, lbl))

            var = tk.BooleanVar()
            tk.Checkbutton(frame, variable=var).place(x=5, y=125)
            self.scrollable_canvas.check_vars.append(var)

            name = os.path.relpath(path, self.folder) if self.recursive_var.get() else os.path.basename(path)
            tk.Label(frame, text=name, wraplength=140).place(x=5, y=150)

            link_lbl = tk.Label(frame, text="📁", cursor="hand2")
            link_lbl.place(x=120, y=125)
            link_lbl.bind("<Button-1>", lambda e, p=path: self.open_file_location(p))

            if is_video(path):
                lbl.bind("<Double-Button-1>", lambda e, p=path: self.open_video_player(p))
            else:
                lbl.bind("<Double-Button-1>", lambda e, p=path: self.open_file(p))

        self.set_status(self.t("loaded", n=len(files)))
        self.scrollable_canvas.update_layout(force=True)

    def _set_thumbnail(self, label, pil_image):
        """Fő szálon fut (call_in_ui-n keresztül)."""
        if not label.winfo_exists():
            return
        photo = ImageTk.PhotoImage(pil_image)
        label.configure(image=photo)
        label.image = photo

    # --- megnyitás / lejátszás ---------------------------------------------
    def open_video_player(self, path):
        if self.vlc_instance is None:
            self.open_file(path)
            return
        try:
            self.close_video_player()

            self.video_window = tk.Toplevel(self)
            self.video_window.title(self.t("player_title", name=os.path.basename(path)))
            self.video_window.geometry("800x600")
            self.video_window.protocol("WM_DELETE_WINDOW", self.close_video_player)

            # Külön keretbe rajzol a VLC, így nem takarja el a vezérlőgombokat
            control_frame = tk.Frame(self.video_window)
            control_frame.pack(side=tk.BOTTOM, fill=tk.X)
            video_frame = tk.Frame(self.video_window, bg="black")
            video_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            tk.Button(control_frame, text="⏯", command=self.toggle_pause).pack(side=tk.LEFT)
            tk.Button(control_frame, text="⏹", command=self.close_video_player).pack(side=tk.LEFT)
            self.video_window.update_idletasks()

            self.vlc_player = self.vlc_instance.media_player_new()
            self.vlc_player.set_media(self.vlc_instance.media_new(path))
            if IS_WINDOWS:
                self.vlc_player.set_hwnd(video_frame.winfo_id())
            else:
                self.vlc_player.set_xwindow(video_frame.winfo_id())
            self.vlc_player.play()
        except Exception as e:
            self.show_error(self.t("video_error", err=e))

    def toggle_pause(self):
        if self.vlc_player:
            self.vlc_player.pause()  # libvlc: pause() váltogat lejátszás/szünet között

    def close_video_player(self):
        if self.vlc_player:
            self.vlc_player.stop()
            self.vlc_player.release()
            self.vlc_player = None
        if self.video_window and self.video_window.winfo_exists():
            self.video_window.destroy()
        self.video_window = None

    def open_file(self, path):
        try:
            if IS_WINDOWS:
                os.startfile(os.path.normpath(path))
            elif IS_MAC:
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.show_error(self.t("open_error", err=e))

    def open_file_location(self, path):
        try:
            abs_path = os.path.normpath(os.path.abspath(path))
            if IS_WINDOWS:
                # Az explorer csak visszaperjeles, egy argumentumba írt /select,"..." formát érti
                subprocess.Popen(f'explorer /select,"{abs_path}"')
            elif IS_MAC:
                subprocess.Popen(["open", "-R", abs_path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(abs_path)])
        except Exception as e:
            self.show_error(self.t("open_error", err=e))

    # --- átnevezés ---------------------------------------------------------
    def selected_paths(self):
        return [self.files[i] for i, var in enumerate(self.scrollable_canvas.check_vars) if var.get()]

    def rename_selected(self):
        """Átnevezés logika mozgatási opcióval"""
        if self.busy:
            self.show_info(self.t("info"), self.t("busy"))
            return
        selected = self.selected_paths()
        if not selected:
            messagebox.showinfo(self.t("none_selected_title"), self.t("none_selected"))
            return

        suffix, move_files = self.get_suffix()
        if not suffix:
            return
        pattern, base_folder = self.settings.pattern, self.folder
        self.close_video_player()  # Windowson a lejátszott fájl nem nevezhető át

        def work():
            items, file_dated = [], 0
            for i, path in enumerate(selected, 1):
                self.call_in_ui(self.set_status, self.t("reading_dates", i=i, n=len(selected)))
                dt, source = get_media_datetime(path)
                file_dated += source == "file"
                items.append((path, dt))

            target_folder = None
            if move_files:
                # A legkorábbi felvétel napja adja a mappa nevét (nem a kijelölés első eleme)
                first_day = min(dt for _, dt in items).strftime("%Y-%m-%d")
                target_folder = os.path.join(base_folder, f"{first_day}_{sanitize_component(suffix)}")
                created = not os.path.isdir(target_folder)
                os.makedirs(target_folder, exist_ok=True)
            else:
                created = False

            plan = plan_renames(items, suffix, pattern, target_folder)
            done, unchanged, errors = execute_plan(
                plan, lambda i, n: self.call_in_ui(self.set_status, self.t("renaming", i=i, n=n)))
            if created and not done:
                remove_empty_folders([target_folder])  # semmi sem került bele: ne maradjon üres mappa
            return {"done": done, "unchanged": unchanged, "errors": errors, "file_dated": file_dated,
                    "target": target_folder, "created": target_folder if created else None}

        self.run_in_background(work, self._rename_finished)

    def _rename_finished(self, r):
        if r["done"]:
            self.last_rename = r["done"]
            self.last_created_folders = [r["created"]] if r["created"] else []
        lines = [self.t("renamed", n=len(r["done"]))
                 + (self.t("moved_to", folder=r["target"]) if r["target"] else "")]
        if r["unchanged"]:
            lines.append(self.t("unchanged", n=r["unchanged"]))
        if r["file_dated"]:
            lines.append(self.t("file_dates", n=r["file_dated"]))
        if r["errors"]:
            lines.append(self.t("rename_errors", n=len(r["errors"])) + "\n".join(r["errors"][:20]))
            messagebox.showerror(self.t("error"), "\n\n".join(lines))
        else:
            messagebox.showinfo(self.t("success"), "\n\n".join(lines))
        self.load_media()

    def undo_last(self):
        if self.busy:
            return
        if not self.last_rename:
            self.show_info(self.t("info"), self.t("undo_none"))
            return
        if not messagebox.askyesno(self.t("btn_undo"), self.t("undo_confirm", n=len(self.last_rename))):
            return
        reverse_plan = [(new, old) for old, new in reversed(self.last_rename)]
        created = self.last_created_folders
        self.close_video_player()

        def work():
            done, _, errors = execute_plan(reverse_plan)
            remove_empty_folders(created)
            return done, errors

        def finished(result):
            done, errors = result
            self.last_rename, self.last_created_folders = [], []
            msg = self.t("undo_done", n=len(done))
            if errors:
                self.show_error(msg + "\n\n" + self.t("rename_errors", n=len(errors)) + "\n".join(errors[:20]))
            else:
                self.show_info(self.t("success"), msg)
            self.load_media()

        self.run_in_background(work, finished)

    # --- rendezés napok szerint --------------------------------------------
    def sort_by_day(self):
        """A kijelölt (vagy ha nincs kijelölés, az összes) fájl áthelyezése ÉÉÉÉ-HH-NN mappákba
        a betöltött mappán belül. Előnézet után fut, és visszavonható."""
        if self.busy:
            self.show_info(self.t("info"), self.t("busy"))
            return
        if not self.folder:
            self.show_info(self.t("info"), self.t("no_folder"))
            return
        selected = self.selected_paths()
        if not selected:
            if not self.files:
                messagebox.showinfo(self.t("none_selected_title"), self.t("none_selected"))
                return
            if not messagebox.askyesno(self.t("btn_daysort"), self.t("daysort_all", n=len(self.files))):
                return
            selected = list(self.files)
        base_folder = self.folder

        def work():
            items = []
            for i, path in enumerate(selected, 1):
                self.call_in_ui(self.set_status, self.t("reading_dates", i=i, n=len(selected)))
                dt, source = get_media_datetime(path)
                items.append((path, dt, source))
            return items

        # Az előnézet saját eseményhurkot futtat, ezért ne a UI-sor feldolgozásán belül nyíljon meg
        self.run_in_background(work, lambda items: self.after(0, self._daysort_preview, base_folder, items))

    def _daysort_preview(self, base_folder, items):
        self.set_status(self.t("ready"))
        file_dated = {path for path, _, source in items if source == "file"}
        dates = {path: dt for path, dt, _ in items}
        include_var = tk.BooleanVar(value=True)
        result = {"ok": False}

        win = tk.Toplevel(self)
        win.title(self.t("daysort_title"))
        win.transient(self)
        win.geometry("760x480")
        summary = tk.Label(win, justify=tk.LEFT, anchor="w", wraplength=720)
        summary.pack(fill=tk.X, padx=10, pady=(10, 4))
        if file_dated:
            tk.Label(win, text=self.t("daysort_file_dates", n=len(file_dated)), justify=tk.LEFT,
                     anchor="w", wraplength=720, fg=self.colors["warn"]).pack(fill=tk.X, padx=10)
            ttk.Checkbutton(win, text=self.t("daysort_include_file"), variable=include_var,
                            command=lambda: refresh()).pack(anchor="w", padx=10, pady=4)

        tree_frame = tk.Frame(win)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        tree = ttk.Treeview(tree_frame, columns=("file", "new"), show="tree headings")
        tree.heading("#0", text=self.t("daysort_col_day"))
        tree.heading("file", text=self.t("daysort_col_file"))
        tree.heading("new", text=self.t("daysort_col_new"))
        tree.column("#0", width=150, stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        bottom = tk.Frame(win)
        bottom.pack(pady=10)
        ok_btn = ttk.Button(bottom, text=self.t("ok"))
        ok_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text=self.t("cancel"), command=win.destroy).pack(side=tk.LEFT, padx=4)

        state = {}

        def refresh():
            chosen = [(p, dt) for p, dt in dates.items() if include_var.get() or p not in file_dated]
            plan, in_place = plan_day_sort(chosen, base_folder)
            state["plan"] = plan
            tree.delete(*tree.get_children())
            days = {}
            for old, new in plan:
                folder = os.path.dirname(new)
                if folder not in days:
                    label = os.path.basename(folder) + ("" if os.path.isdir(folder) else " (+)")
                    days[folder] = tree.insert("", tk.END, text=label, open=len(plan) <= 200)
                mark = " *" if old in file_dated else ""
                tree.insert(days[folder], tk.END, values=(os.path.relpath(old, base_folder) + mark,
                                                          os.path.basename(new)))
            new_folders = sum(1 for f in days if not os.path.isdir(f))
            summary.config(text=self.t("daysort_summary", n=len(plan), d=len(days), folder=base_folder,
                                       new=new_folders, in_place=in_place))
            ok_btn.state(["!disabled"] if plan else ["disabled"])

        def accept():
            if state.get("plan"):
                result["ok"] = True
                win.destroy()

        ok_btn.config(command=accept)
        win.bind("<Return>", lambda e: accept())
        win.bind("<Escape>", lambda e: win.destroy())
        refresh()
        win.focus_set()
        if not state["plan"]:
            win.destroy()
            self.show_info(self.t("info"), self.t("daysort_nothing"))
            return
        win.grab_set()
        self.wait_window(win)
        if result["ok"]:
            self._daysort_run(state["plan"])

    def _daysort_run(self, plan):
        self.close_video_player()  # Windowson a lejátszott fájl nem mozgatható

        def work():
            return execute_day_sort(
                plan, lambda i, n: self.call_in_ui(self.set_status, self.t("daysort_moving", i=i, n=n)))

        def finished(result):
            done, errors, created = result
            if done:
                self.last_rename = done
                self.last_created_folders = created
            else:
                remove_empty_folders(created)
            days = len({os.path.dirname(new) for _, new in done})
            msg = self.t("daysort_done", n=len(done), d=days)
            if done:
                msg += "\n\n" + self.t("daysort_undo_hint")
            if errors:
                self.show_error(msg + "\n\n" + self.t("daysort_errors", n=len(errors)) + "\n".join(errors[:20]))
            else:
                self.show_info(self.t("success"), msg)
            self.load_media()

        self.run_in_background(work, finished)

    def get_suffix(self):
        """Téma választó ablak pipálható mozgatási opcióval"""
        result = {"suffix": None, "move": False}
        win = tk.Toplevel(self)
        win.title(self.t("suffix_title"))
        win.transient(self)

        tk.Label(win, text=self.t("suffix_prompt")).pack(pady=5, padx=10)
        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=5)

        move_var = tk.BooleanVar(value=False)

        def choose(value):
            value = value.strip()
            if value:
                result["suffix"] = value
                result["move"] = move_var.get()
                win.destroy()

        for s in self.prev_suffixes:
            ttk.Button(btn_frame, text=s, width=25, command=partial(choose, s)).pack(pady=2)

        suffix_var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=suffix_var, width=30)
        entry.pack(pady=5, padx=10)
        entry.focus_set()

        ttk.Checkbutton(win, text=self.t("move_check"), variable=move_var).pack(pady=5)

        bottom = tk.Frame(win)
        bottom.pack(pady=10)
        ttk.Button(bottom, text=self.t("ok"), command=lambda: choose(suffix_var.get())).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text=self.t("cancel"), command=win.destroy).pack(side=tk.LEFT, padx=4)
        win.bind("<Return>", lambda e: choose(suffix_var.get()))
        win.bind("<Escape>", lambda e: win.destroy())

        win.grab_set()
        self.wait_window(win)

        if result["suffix"]:
            # A legutóbb használt téma kerül előre, és a program újraindítása után is megmarad
            self.prev_suffixes = [result["suffix"]] + [s for s in self.prev_suffixes if s != result["suffix"]]
            self.settings.recent_suffixes = self.prev_suffixes
            self.settings.save_settings()
        return result["suffix"], result["move"]

    def unmark_all(self):
        for var in self.scrollable_canvas.check_vars:
            var.set(False)

    def mark_all(self):
        for var in self.scrollable_canvas.check_vars:
            var.set(True)

    # --- törlés ------------------------------------------------------------
    def delete_selected(self):
        if self.busy:
            return
        selected = self.selected_paths()
        if not selected:
            self.show_info(self.t("none_selected_title"), self.t("delete_none"))
            return

        question = "delete_confirm_trash" if send2trash else "delete_confirm_perm"
        if not messagebox.askyesno(self.t("delete_confirm_title"), self.t(question, n=len(selected)),
                                   icon=messagebox.WARNING):
            return
        self.close_video_player()

        def work():
            errors = []
            for path in selected:
                try:
                    if send2trash:
                        send2trash(os.path.normpath(path))
                    else:
                        os.remove(path)
                except Exception as e:
                    errors.append(f"{os.path.basename(path)}: {e}")
            return errors

        def finished(errors):
            if errors:
                self.show_error(self.t("delete_errors", n=len(errors)) + "\n".join(errors[:20]))
            else:
                self.show_info(self.t("success"), self.t("deleted", n=len(selected)))
            self.load_media()

        self.run_in_background(work, finished)

    # --- kilépés, üzenetek -------------------------------------------------
    def on_close(self):
        # Kilépéskor a háttérszál félbeszakad; másik meghajtóra mozgatásnál félkész másolat maradhat
        if self.busy and not messagebox.askyesno(self.t("btn_exit"), self.t("busy_exit"),
                                                 icon=messagebox.WARNING):
            return
        self.running = False
        self.async_loader.stop()
        try:
            self.close_video_player()
        except Exception:
            pass
        self.destroy()

    def show_error(self, message):
        messagebox.showerror(self.t("error"), message)

    def show_info(self, title, message):
        messagebox.showinfo(title, message)


if __name__ == "__main__":
    app = ImageRenamerGUI()
    app.mainloop()
