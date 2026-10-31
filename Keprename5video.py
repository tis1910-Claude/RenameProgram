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
import gzip
import hashlib
import math
import io
import time
from collections import OrderedDict
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
                       "{counter} = ütközésszámláló (csak ha kell, egyébként elhagyva)\n"
                       "{place} = település a GPS alapján (pl. Siófok; ha nincs GPS, elhagyva)"),
        "menu_place": "Helyszín a névben (GPS alapján)",
        "place_on": ("A fájlnévbe a felvétel helyéhez legközelebbi település neve is bekerül, ha a fájlban "
                     "van GPS-koordináta (internet nélkül). Példa:\n{example}"),
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
        "move_check": "Új mappa létrehozása (dátum + téma), és a fájlok áthelyezése oda",
        "move_folder": "A fájlok ide kerülnek: {path}",
        "move_base_label": "Az új mappa helye:",
        "move_base_current": "a jelenlegi mappa",
        "move_base_browse": "Tallózás...",
        "move_base_reset": "Jelenlegi mappa",
        "move_base_title": "Hová kerüljön az új mappa?",
        "move_date_placeholder": "ÉÉÉÉ-HH-NN",
        "move_topic_placeholder": "téma",
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
        "undo_confirm": ("Visszavonod ezt a lépést?\n\n{what}, {time}, {n} fájl\n\n"
                         "Utána még {left} korábbi lépés vonható vissza."),
        "undo_menu": "Visszavonás: {what} ({n} fájl, {time})",
        "history_rename": "Átnevezés",
        "history_daysort": "Rendezés napok szerint",
        "menu_duplicates": "Duplikátumok keresése",
        "dup_title": "Duplikátumok",
        "dup_progress": "Duplikátumok keresése... {i}/{n}",
        "dup_none": "Nincs azonos tartalmú fájl.",
        "dup_summary": ("{g} csoportban {n} fölösleges másolat ({mb:.1f} MB). Csoportonként a legfelső mappában "
                        "lévő fájl a megtartandó. A „Másolatok kijelölése” csak kijelöl, a törlés a Törlés gombbal történik."),
        "dup_col_file": "Fájl",
        "dup_group": "{i}. csoport ({n} fájl)",
        "dup_keep": "megtartandó",
        "dup_copy": "másolat",
        "dup_select": "Másolatok kijelölése",
        "dup_selected": "{n} másolat kijelölve. Ellenőrizd, majd a Törlés gombbal a lomtárba teheted őket.",
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
        "filter_kind": "Típus:",
        "filter_all": "Mind",
        "filter_images": "Képek",
        "filter_videos": "Videók",
        "filter_raw": "RAW",
        "filter_search": "Keresés:",
        "filter_from": "Dátum:",
        "filter_to": "–",
        "filter_file_dated": "Csak metaadat nélkül",
        "count_selected": "{sel} kijelölve / {shown} látható",
        "count_filtered": " (összesen {total})",
        "shift_label": "Időeltolás:",
        "shift_hint": "pl. +1 (óra), -0:30, +1d 2:00 — ha a fényképező órája rosszul járt; a fájlt nem módosítja",
        "shift_invalid": "Érvénytelen eltolás. Példák: +1, -0:30, +1d 2:00",
        "rename_preview_title": "Átnevezés - előnézet",
        "rename_preview_summary": "{n} fájl kap új nevet, {unchanged} neve már megfelelő.",
        "col_old": "Jelenlegi név",
        "col_date": "Felvétel ideje",
        "unchanged_mark": "(változatlan)",
        "from_name": " (névből)",
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
        "daysort_undo_hint": "Visszavonás: Szerkesztés → Visszavonás (Ctrl+Z), a program újraindítása után is.",
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
                       "{counter} = collision counter (only when needed, otherwise omitted)\n"
                       "{place} = town from GPS (e.g. Siófok; omitted when there is no GPS)"),
        "menu_place": "Place in the name (from GPS)",
        "place_on": ("The name of the town nearest to where the photo was taken is added to the file name "
                     "when the file has GPS coordinates (works offline). Example:\n{example}"),
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
        "move_check": "Create a new folder (date + topic) and move the files there",
        "move_folder": "Files will go to: {path}",
        "move_base_label": "New folder location:",
        "move_base_current": "the current folder",
        "move_base_browse": "Browse...",
        "move_base_reset": "Current folder",
        "move_base_title": "Where should the new folder go?",
        "move_date_placeholder": "YYYY-MM-DD",
        "move_topic_placeholder": "topic",
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
        "undo_confirm": ("Undo this step?\n\n{what}, {time}, {n} files\n\n"
                         "{left} earlier steps can still be undone after this."),
        "undo_menu": "Undo: {what} ({n} files, {time})",
        "history_rename": "Rename",
        "history_daysort": "Sort by day",
        "menu_duplicates": "Find duplicates",
        "dup_title": "Duplicates",
        "dup_progress": "Finding duplicates... {i}/{n}",
        "dup_none": "No files with identical content.",
        "dup_summary": ("{n} redundant copies in {g} groups ({mb:.1f} MB). In each group the file in the topmost "
                        "folder is kept. \"Select copies\" only selects them; delete them with the Delete button."),
        "dup_col_file": "File",
        "dup_group": "Group {i} ({n} files)",
        "dup_keep": "keep",
        "dup_copy": "copy",
        "dup_select": "Select copies",
        "dup_selected": "{n} copies selected. Check them, then move them to the recycle bin with Delete.",
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
        "filter_kind": "Type:",
        "filter_all": "All",
        "filter_images": "Images",
        "filter_videos": "Videos",
        "filter_raw": "RAW",
        "filter_search": "Search:",
        "filter_from": "Date:",
        "filter_to": "–",
        "filter_file_dated": "No metadata only",
        "count_selected": "{sel} selected / {shown} shown",
        "count_filtered": " (total {total})",
        "shift_label": "Time shift:",
        "shift_hint": "e.g. +1 (hour), -0:30, +1d 2:00 — if the camera clock was wrong; files are not modified",
        "shift_invalid": "Invalid shift. Examples: +1, -0:30, +1d 2:00",
        "rename_preview_title": "Rename - preview",
        "rename_preview_summary": "{n} files get a new name, {unchanged} already have the right name.",
        "col_old": "Current name",
        "col_date": "Capture time",
        "unchanged_mark": "(unchanged)",
        "from_name": " (from name)",
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
        "daysort_undo_hint": "Undo: Edit → Undo (Ctrl+Z), even after restarting the program.",
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


def _blend(rgb_a, rgb_b, ratio):
    """Két (r, g, b) szín keveréke #rrggbb alakban (ratio = az első aránya, 0-255 komponensek)."""
    return "#" + "".join(f"{round(x * ratio + y * (1 - ratio)):02x}" for x, y in zip(rgb_a, rgb_b))


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
    """com.apple.quicktime.creationdate (helyi idő + eltolás), vagy None."""
    return _apple_keys(moov).get("com.apple.quicktime.creationdate")


def _apple_keys(moov):
    """moov/meta (vagy moov/udta/meta) keys+ilst szöveges értékei: {kulcs: érték}."""
    result = {}
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
            if not 1 <= index <= len(keys):
                continue
            for sub, ds, de in _iter_boxes(moov, s, e):
                if sub == b"data" and int.from_bytes(moov[ds:ds + 4], "big") == 1:  # 1 = UTF-8 szöveg
                    result.setdefault(keys[index - 1], moov[ds + 8:de].decode("utf-8", "replace").strip("\x00 "))
    return result


def read_bmff_metadata(path):
    """MP4/MOV/3GP fejléc: {'creation_time': ISO szöveg (UTC) | None,
    'apple_date': ISO szöveg eltolással | None, 'duration': mp | None}. Hiba esetén üres dict."""
    try:
        moov = _read_moov(path)
    except OSError:
        return {}
    if not moov:
        return {}
    result = {"creation_time": None, "apple_date": None, "apple_location": None, "duration": None}
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
        apple = _apple_keys(moov)
        result["apple_date"] = apple.get("com.apple.quicktime.creationdate")
        result["apple_location"] = apple.get("com.apple.quicktime.location.ISO6709")
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


# Dátum a fájlnévből, ha nincs beágyazott dátum (WhatsApp, Messenger, képernyőképek, Android).
# (minta, időzóna): "local" = a név helyi időt tartalmaz, "utc" = UTC-t (Pixel), "epoch_ms" = Unix-idő ms-ban.
_D = r"(?P<y>(?:19|20)\d\d)"
_FILENAME_PATTERNS = [
    # Facebook/Messenger letöltés: FB_IMG_1691843415123.jpg (Unix-idő ezredmásodpercben)
    (re.compile(r"^FB_IMG_(?P<ms>\d{13})"), "epoch_ms"),
    # Google Pixel: PXL_20230812_143015123.jpg (UTC)
    (re.compile(r"^PXL_" + _D + r"(?P<m>\d\d)(?P<d>\d\d)_(?P<H>\d\d)(?P<M>\d\d)(?P<S>\d\d)"), "utc"),
    # WhatsApp: IMG-20230812-WA0001.jpg, VID-20230812-WA0003.mp4 (csak nap)
    (re.compile(r"^(?:IMG|VID|AUD|PTT|STK|DOC)-" + _D + r"(?P<m>\d\d)(?P<d>\d\d)-WA\d+"), "local"),
    # Elválasztott dátum + idő: 2023-08-12 14.30.15, 2023-08-12_14-30-15, Screenshot 2023-08-12 at 14.30.15,
    # Képernyőkép 2023-08-12 143015, signal-2023-08-12-143015, Screenshot_2023-08-12-14-30-15-123_...
    (re.compile(r"(?<!\d)" + _D + r"[-_.](?P<m>\d\d)[-_.](?P<d>\d\d)(?:[ _T-]+(?:at[ _])?(?P<H>\d\d)[-_.:h]?"
                r"(?P<M>\d\d)[-_.:m]?(?P<S>\d\d))?(?!\d)"), "local"),
    # Tömör dátum + idő: IMG_20230812_143015.jpg, 20230812_143015.jpg, Screenshot_20230812-143015.png
    (re.compile(r"(?<!\d)" + _D + r"(?P<m>\d\d)(?P<d>\d\d)[_-](?P<H>\d\d)(?P<M>\d\d)(?P<S>\d\d)(?!\d)"), "local"),
]


def get_filename_datetime(path, now=None):
    """A fájlnévben lévő felvételi dátum, vagy None. Csak ismert, egyértelmű alakokat fogad el."""
    name = os.path.splitext(os.path.basename(path))[0]
    latest = (now or datetime.now()) + timedelta(days=1)
    for pattern, kind in _FILENAME_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        g = match.groupdict()
        try:
            if kind == "epoch_ms":
                dt = datetime.fromtimestamp(int(g["ms"]) / 1000)
            else:
                dt = datetime(int(g["y"]), int(g["m"]), int(g["d"]),
                              int(g.get("H") or 0), int(g.get("M") or 0), int(g.get("S") or 0))
                if kind == "utc":
                    dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            continue  # pl. 2023-13-45: nem dátum, a többi mintát még megpróbáljuk
        if datetime(1990, 1, 1) <= dt <= latest:
            return dt
    return None


def get_media_datetime(path):
    """(datetime, forrás) ahol forrás: 'exif' | 'video' | 'filename' | 'file'. Mindig ad dátumot."""
    if is_video(path):
        dt = get_video_datetime(path)
        if dt:
            return dt, "video"
    else:
        dt = get_exif_datetime(path)
        if dt:
            return dt, "exif"
    dt = get_filename_datetime(path)
    if dt:
        return dt, "filename"
    return get_file_datetime(path), "file"


# ---------------------------------------------------------------------------
# Névsablon és átnevezési terv (GUI-független)
# ---------------------------------------------------------------------------
PATTERN_FIELDS = {"date", "day", "time", "suffix", "counter", "seq", "original", "place"}
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_COUNTER_MARK = "\x00CNT\x00"
_EMPTY_MARK = "\x00EMPTY\x00"


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


def pattern_with_place(pattern):
    """A sablon kiegészítése a {place} mezővel (a téma után), ha még nincs benne."""
    if "{place}" in pattern:
        return pattern
    if "{suffix}" in pattern:
        return pattern.replace("{suffix}", "{suffix}_{place}", 1)
    return pattern.replace("{counter}", "{place}_{counter}", 1) if "{counter}" in pattern else pattern + "_{place}"


def render_name(pattern, dt, suffix, counter=0, seq=1, original="", ext="", place=""):
    place = sanitize_component(place or "")
    values = {
        "place": place or _EMPTY_MARK,
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
    # Ismeretlen helyszín: a mező az előtte álló elválasztóval együtt kimarad
    name = re.sub(r"[_\-. ]?" + re.escape(_EMPTY_MARK), "", name)
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


# --- Live Photo párok: IMG_1234.HEIC + IMG_1234.MOV ugyanabban a mappában -----
LIVE_PHOTO_EXTS = (".heic", ".heif", ".jpg", ".jpeg")
LIVE_VIDEO_EXTS = (".mov", ".mp4")


def find_live_pairs(paths):
    """{fotó: [videó]} az azonos mappában, azonos nevű (kis/nagybetű mindegy) fotó + videó párokra."""
    photos, videos = {}, {}
    for p in paths:
        stem, ext = os.path.splitext(p)
        key = _key(stem)
        if ext.lower() in LIVE_PHOTO_EXTS:
            photos.setdefault(key, p)
        elif ext.lower() in LIVE_VIDEO_EXTS:
            videos.setdefault(key, []).append(p)
    return {photo: sorted(videos[key]) for key, photo in photos.items() if key in videos}


def with_live_partners(selected, all_paths):
    """A kijelölés kiegészítve a párok hiányzó tagjával. Vissza: (útvonalak, {fotó: [videó]})."""
    pairs = find_live_pairs(all_paths)
    partner_of = {v: photo for photo, vids in pairs.items() for v in vids}
    chosen = set(selected)
    used = {}
    for p in selected:
        photo = p if p in pairs else partner_of.get(p)
        if photo:
            used[photo] = pairs[photo]
            chosen.add(photo)
            chosen.update(pairs[photo])
    ordered = [p for p in all_paths if p in chosen] + [p for p in selected if p not in set(all_paths)]
    return ordered, used


def _split_partners(items, partners):
    """A párok videói kikerülnek az önálló elemek közül; a fotóval együtt kapnak nevet és dátumot."""
    partners = partners or {}
    followers = {v for vids in partners.values() for v in vids}
    return [it for it in items if it[0] not in followers], partners


def plan_renames(items, suffix, pattern, target_dir=None, exists=os.path.exists, partners=None, places=None):
    """items: [(útvonal, datetime)] -> [(régi, új)].
    A tervezett nevek egymással és a lemezen lévő fájlokkal sem ütközhetnek.
    partners: {fotó: [videó]} (Live Photo): a videó a fotóval azonos nevet kap, csak a kiterjesztés más."""
    items, partners = _split_partners(items, partners)
    items = sorted(items, key=lambda it: (it[1], it[0]))
    reserved = set()
    plan = []
    for seq, (path, dt) in enumerate(items, 1):
        folder = target_dir or os.path.dirname(path)
        stem, ext = os.path.splitext(os.path.basename(path))
        group = [path] + partners.get(path, [])
        counter = 0
        while True:
            base = render_name(pattern, dt, suffix, counter, seq, stem, "", (places or {}).get(path, ""))
            news = [os.path.join(folder, base + os.path.splitext(p)[1]) for p in group]
            if all(_key(n) not in reserved and _is_free_for(n, p, exists) for n, p in zip(news, group)):
                break
            counter += 1
        for p, n in zip(group, news):
            reserved.add(_key(n))
            plan.append((p, n))
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


_SHIFT_RE = re.compile(r"^\s*([+-])?\s*(?:(\d+)\s*[dn]\s*)?(?:(\d+)(?::(\d{1,2}))?)?\s*$", re.IGNORECASE)


def parse_shift(text):
    """Időeltolás: '+1', '-0:30', '+1d 2:00' (d/n = nap), üres = 0. Hibás alakra ValueError."""
    match = _SHIFT_RE.match(text or "")
    if not match:
        raise ValueError(text)
    sign, days, hours, minutes = match.groups()
    if minutes and int(minutes) >= 60:
        raise ValueError(text)
    delta = timedelta(days=int(days or 0), hours=int(hours or 0), minutes=int(minutes or 0))
    return -delta if sign == "-" else delta


def move_target_folder(base_folder, items, suffix):
    """A közös célmappa: a legkorábbi felvétel napja + téma (nem a kijelölés első eleme)."""
    first_day = min(dt for _, dt in items).strftime("%Y-%m-%d")
    return os.path.join(base_folder, f"{first_day}_{sanitize_component(suffix)}")


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


class DateCache:
    """Szálbiztos gyorsítótár a get_media_datetime eredményeihez. A kulcs az útvonal,
    módosítási idő és méret, így átnevezés vagy módosítás után újraolvas."""

    def __init__(self, reader=None):
        self._reader = reader or get_media_datetime
        self._data = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(path):
        st = os.stat(path)
        return path, st.st_mtime_ns, st.st_size

    def peek(self, path):
        """(datetime, forrás) ha már ismert, különben None. Nem olvas fájlt (a GUI szálon is hívható)."""
        with self._lock:
            return self._data.get(path, (None, None))[1]

    def get(self, path):
        key = self._key(path)
        with self._lock:
            hit = self._data.get(path)
        if hit and hit[0] == key:
            return hit[1]
        value = self._reader(path)
        with self._lock:
            self._data[path] = (key, value)
        return value


# ---------------------------------------------------------------------------
# Szűrés (GUI-független)
# ---------------------------------------------------------------------------
FILTER_KINDS = ("all", "images", "videos", "raw")


def parse_day(text):
    """'2024-05-01' vagy '2024.05.01' -> date, üres -> None, hibás -> ValueError."""
    text = (text or "").strip().replace(".", "-").rstrip("-")
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def filter_paths(paths, kind="all", text="", day_from=None, day_to=None, only_file_dated=False,
                 date_of=lambda p: None):
    """A szűrőknek megfelelő útvonalak, eredeti sorrendben. date_of(p) -> (datetime, forrás) vagy
    None, ha a dátum még nem ismert: ilyenkor a dátumos szűrők nem rejtik el a fájlt."""
    needle = text.strip().casefold()
    result = []
    for p in paths:
        if kind == "images" and is_video(p) or kind == "videos" and not is_video(p) \
                or kind == "raw" and not is_raw(p):
            continue
        if needle and needle not in os.path.basename(p).casefold():
            continue
        if day_from or day_to or only_file_dated:
            known = date_of(p)
            if known:
                dt, source = known
                if day_from and dt.date() < day_from or day_to and dt.date() > day_to:
                    continue
                if only_file_dated and source != "file":
                    continue
        result.append(p)
    return result


# ---------------------------------------------------------------------------
# Rendezés napok szerint: base/ÉÉÉÉ-HH-NN/eredeti_név (GUI-független)
# ---------------------------------------------------------------------------
def day_folder(base_folder, dt):
    return os.path.join(base_folder, dt.strftime("%Y-%m-%d"))


def plan_day_sort(items, base_folder, exists=os.path.exists, partners=None):
    """items: [(útvonal, datetime)] -> (terv [(régi, új)], már a helyén lévők száma).
    A fájlnév marad; ütközéskor _1, _2... kerül a név végére. A már a helyes
    napi mappában lévő fájlok kimaradnak a tervből. partners: {fotó: [videó]} (Live Photo):
    a videó a fotó napjába kerül, és ütközéskor ugyanazt a végződést kapja."""
    items, partners = _split_partners(items, partners)
    reserved = set()
    plan, in_place = [], 0
    for path, dt in sorted(items, key=lambda it: (it[1], it[0])):
        folder = day_folder(base_folder, dt)
        group = [path] + partners.get(path, [])
        if _key(os.path.dirname(path)) == _key(folder):
            in_place += len(group)
            reserved.update(_key(p) for p in group)
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        counter = 0
        while True:
            base = f"{stem}_{counter}" if counter else stem
            news = [os.path.join(folder, base + os.path.splitext(p)[1]) for p in group]
            if all(_key(n) not in reserved and not exists(n) for n in news):
                break
            counter += 1
        for p, n in zip(group, news):
            reserved.add(_key(n))
            plan.append((p, n))
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
# Helyszín a GPS-koordinátából, internet nélkül (GUI-független)
# ---------------------------------------------------------------------------
# A places.tsv.gz a GeoNames (https://www.geonames.org) legalább 1000 lakosú településeit
# tartalmazza (CC BY 4.0): név, szélesség, hosszúság, országkód.
PLACES_FILE = "places.tsv.gz"
_ISO6709 = re.compile(r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def _gps_to_degrees(value, ref):
    d, m_, s_ = (float(x) for x in value)
    deg = d + m_ / 60 + s_ / 3600
    return -deg if str(ref).strip().upper() in ("S", "W") else deg


def get_gps(path):
    """(szélesség, hosszúság) fokban, vagy None. Fotó: EXIF GPS; videó: iPhone ISO 6709 kulcs vagy ffprobe."""
    if is_video(path):
        text = None
        if path.lower().endswith(BMFF_EXTS):
            text = read_bmff_metadata(path).get("apple_location")
        if not text:
            tags = probe_video(path).get("tags", {})
            text = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
        match = _ISO6709.match(text or "")
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            if (lat, lon) != (0.0, 0.0):
                return lat, lon
        return None
    try:
        if is_raw(path) and exifread is not None:
            with open(path, "rb") as f:
                tags = exifread.process_file(f, details=False)
            lat, lon = tags.get("GPS GPSLatitude"), tags.get("GPS GPSLongitude")
            if lat and lon:
                to_float = lambda v: [float(x.num) / float(x.den or 1) for x in v.values]
                return (_gps_to_degrees(to_float(lat), tags.get("GPS GPSLatitudeRef", "N")),
                        _gps_to_degrees(to_float(lon), tags.get("GPS GPSLongitudeRef", "E")))
        with Image.open(path) as img:
            gps = img.getexif().get_ifd(0x8825)
        if 2 in gps and 4 in gps:
            lat = _gps_to_degrees(gps[2], gps.get(1, "N"))
            lon = _gps_to_degrees(gps[4], gps.get(3, "E"))
            if (lat, lon) != (0.0, 0.0):
                return lat, lon
    except Exception as e:
        print(f"GPS hiba ({path}): {e}")
    return None


class PlaceIndex:
    """Legközelebbi település a koordinátához, 1 fokos rácsba rendezve (első használatkor töltődik be)."""
    MAX_KM = 25  # ennél messzebb (pl. tengeren) nincs név

    def __init__(self, path=None):
        self.path = path or resource_path(PLACES_FILE)
        self._cells = None
        self._lock = threading.Lock()

    def available(self):
        return os.path.exists(self.path)

    def _load(self):
        with self._lock:
            if self._cells is None:
                cells = {}
                with gzip.open(self.path, "rt", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("#"):
                            continue
                        name, lat, lon, _ = line.rstrip("\n").split("\t")
                        lat, lon = float(lat), float(lon)
                        cells.setdefault((math.floor(lat), math.floor(lon)), []).append((lat, lon, name))
                self._cells = cells
        return self._cells

    def nearest(self, lat, lon):
        try:
            cells = self._load()
        except (OSError, ValueError) as e:
            print(f"Helyszín-adatbázis hiba: {e}")
            return ""
        best, best_d = "", self.MAX_KM ** 2
        cos_lat = math.cos(math.radians(lat))
        cy, cx = math.floor(lat), math.floor(lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for plat, plon, name in cells.get((cy + dy, (cx + dx + 180) % 360 - 180), ()):
                    d = ((plat - lat) * 111.2) ** 2 + ((plon - lon) * 111.2 * cos_lat) ** 2
                    if d < best_d:
                        best, best_d = name, d
        return best


_place_index = PlaceIndex()


def get_place(path, index=None):
    """A felvétel helyéhez legközelebbi település neve, vagy "" (nincs GPS / nincs adatbázis)."""
    gps = get_gps(path)
    return (index or _place_index).nearest(*gps) if gps else ""


# ---------------------------------------------------------------------------
# Visszavonási előzmények és duplikátumok (GUI-független)
# ---------------------------------------------------------------------------
class UndoHistory:
    """Több lépésben visszavonható átnevezések/áthelyezések, fájlba mentve, így a program
    újraindítása után is visszavonhatók. Mindig a legutóbbi lépés vonható vissza (LIFO)."""
    MAX_STEPS = 20

    def __init__(self, path):
        self.path = path
        self.steps = []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.steps = [s for s in data.get("steps", []) if isinstance(s, dict) and s.get("moves")]
        except (OSError, ValueError, AttributeError):
            self.steps = []

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "steps": self.steps}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"Előzmények mentési hiba: {e}")

    def push(self, kind, moves, created=(), when=None):
        if not moves:
            return
        self.steps.append({"kind": kind, "time": (when or datetime.now()).strftime("%Y-%m-%d %H:%M"),
                           "moves": [list(m) for m in moves], "created": list(created)})
        del self.steps[:-self.MAX_STEPS]
        self.save()

    def last(self):
        return self.steps[-1] if self.steps else None

    def pop(self):
        step = self.steps.pop() if self.steps else None
        self.save()
        return step

    def __len__(self):
        return len(self.steps)


def _file_digest(path, limit=None, chunk=1024 * 1024):
    h = hashlib.sha1()
    read = 0
    with open(path, "rb") as f:
        while limit is None or read < limit:
            block = f.read(chunk if limit is None else min(chunk, limit - read))
            if not block:
                break
            h.update(block)
            read += len(block)
    return h.hexdigest()


def find_duplicates(paths, progress=None):
    """Azonos tartalmú fájlok csoportjai: méret -> első 64 kB -> teljes SHA-1 szerint szűkítve,
    így a legtöbb fájlt nem kell végigolvasni. Minden csoport első eleme a „megtartandó”:
    a legrövidebb útvonalú (a legfelső mappában lévő), azon belül ábécé szerint az első."""
    by_size = {}
    for p in paths:
        try:
            by_size.setdefault(os.path.getsize(p), []).append(p)
        except OSError:
            continue
    candidates = [g for size, g in by_size.items() if len(g) > 1 and size > 0]
    groups = []
    for i, group in enumerate(candidates, 1):
        for stage in (64 * 1024, None):  # előbb csak a fájl eleje, aztán a teljes tartalom
            buckets = {}
            for p in group:
                try:
                    buckets.setdefault(_file_digest(p, stage), []).append(p)
                except OSError:
                    continue
            group = [p for b in buckets.values() if len(b) > 1 for p in b]
            if not group:
                break
        else:
            groups += [b for b in buckets.values() if len(b) > 1]
        if progress:
            progress(i, len(candidates))
    keep_first = lambda p: (p.count(os.sep), len(p), p.casefold())
    return sorted((sorted(g, key=keep_first) for g in groups), key=lambda g: keep_first(g[0]))


# ---------------------------------------------------------------------------
# Bélyegképek (háttérszálban csak PIL kép készül, PhotoImage a fő szálon)
# ---------------------------------------------------------------------------
def _cache_dir():
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "MediaRenamerPro", "thumbs")


class ThumbnailCache:
    """Lemezes bélyegkép-gyorsítótár. A kulcs az útvonal + módosítási idő + méret, így egy
    megváltozott fájl új bélyegképet kap. A mérete a prune() hívásakor korlátozódik."""
    VERSION = "1"

    def __init__(self, folder=None, max_bytes=300 * 1024 * 1024):
        self.folder = folder or _cache_dir()
        self.max_bytes = max_bytes
        self.enabled = True

    def _file(self, path, size):
        st = os.stat(path)
        raw = f"{self.VERSION}|{os.path.abspath(path)}|{st.st_mtime_ns}|{st.st_size}|{size[0]}x{size[1]}"
        digest = hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()
        return os.path.join(self.folder, digest[:2], digest + ".jpg")

    def get(self, path, size):
        if not self.enabled:
            return None
        try:
            cached = self._file(path, size)
            with Image.open(cached) as img:
                img.load()
                return img.copy()
        except (OSError, ValueError):
            return None

    def put(self, path, size, img):
        if not self.enabled:
            return
        try:
            cached = self._file(path, size)
            os.makedirs(os.path.dirname(cached), exist_ok=True)
            tmp = f"{cached}.{threading.get_ident()}.tmp"
            img.convert("RGB").save(tmp, "JPEG", quality=85)
            os.replace(tmp, cached)
        except OSError as e:
            print(f"Gyorsítótár írási hiba: {e}")

    def prune(self, keep_ratio=0.7):
        """Ha a gyorsítótár túl nagy, a legrégebben használt fájlokat törli a keret 70%-áig."""
        entries, total = [], 0
        for root, _, names in os.walk(self.folder):
            for n in names:
                p = os.path.join(root, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                entries.append((max(st.st_atime, st.st_mtime), st.st_size, p))
                total += st.st_size
        if total <= self.max_bytes:
            return 0
        removed = 0
        for _, nbytes, p in sorted(entries):
            if total <= self.max_bytes * keep_ratio:
                break
            try:
                os.remove(p)
                total -= nbytes
                removed += 1
            except OSError:
                pass
        return removed


class ThumbnailGenerator:
    _icon = None
    _icon_lock = threading.Lock()
    cache = ThumbnailCache()

    @staticmethod
    def generate(path, size=THUMB_SIZE):
        """Mindig ad képet: a gyorsítótárból, frissen készítve, vagy hiba esetén szürkét.
        A szürke tartalék nem kerül a gyorsítótárba (pl. az ffmpeg később telepíthető)."""
        img = ThumbnailGenerator.cache.get(path, size)
        if img is not None:
            return img
        try:
            img = ThumbnailGenerator._video(path, size) if is_video(path) else ThumbnailGenerator._image(path, size)
        except Exception as e:
            print(f"Bélyegkép hiba ({path}): {e}")
            return Image.new('RGB', size, color='gray')
        ThumbnailGenerator.cache.put(path, size, img)
        return img

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
            raise RuntimeError("nincs ffmpeg")
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
            raise RuntimeError("az ffmpeg nem adott képkockát")
        img = Image.open(io.BytesIO(out))
        img.thumbnail(size)
        img = img.convert("RGBA")
        icon = ThumbnailGenerator._video_icon()
        if icon:
            img.paste(icon, (0, 0), icon)
        return img.convert("RGB")


class AsyncThumbnailLoader:
    """Munkaszálak, amelyek PIL képet adnak vissza egy callback-en keresztül.
    A callback-et a hívó (GUI) köteles a fő szálra továbbítani. A sor LIFO: görgetés után
    az éppen látható képek készülnek el először, nem a már elgörgetettek."""

    def __init__(self, max_workers=4):
        self.queue = queue.LifoQueue()
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
def short_name(name, limit=40):
    """Hosszú fájlnév rövidítése a közepéből, a kiterjesztés megmarad."""
    if len(name) <= limit:
        return name
    keep = limit - 1
    return name[:keep - keep // 3] + "…" + name[-(keep // 3):]


class ThumbGrid(tk.Frame):
    """Bélyegképrács egyetlen vásznon. Csak a látható cellák rajzolódnak ki, és csak azok
    bélyegképe töltődik be, így több ezer fájlnál sem lassul be, és nem eszi a memóriát.

    Egér: kattintás = kijelölés be/ki, Shift+kattintás = tartomány, dupla kattintás = megnyitás,
    a 📁 jel = megnyitás a fájlkezelőben."""
    CELL_W, CELL_H = 170, 192
    THUMB_X, THUMB_Y = 10, 4
    MAX_PHOTOS = 400  # ennyi PhotoImage marad memóriában (kb. 36 MB)

    def __init__(self, parent, loader, call_in_ui, on_open, on_locate, on_selection_change):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0, yscrollincrement=self.CELL_H // 4)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.loader, self.call_in_ui = loader, call_in_ui
        self.on_open, self.on_locate, self.on_selection_change = on_open, on_locate, on_selection_change
        self.paths = []          # a látható (szűrt) lista, sorrendben
        self.labels = {}         # útvonal -> megjelenített név
        self.selected = set()    # kijelölt útvonalak (a szűrés nem törli)
        self.live = set()        # Live Photo fotók (van azonos nevű videójuk)
        self.anchor = None       # a Shift+kattintás tartományának kezdete
        self.photos = OrderedDict()  # útvonal -> PhotoImage (LRU)
        self.pending = set()
        self.cols = 1
        self.colors = {"canvas": "white", "thumb": "#eeeeee", "fg": "black", "select": "#2563eb",
                       "select_fill": "#dbe6fd"}
        self._redraw_job = None

        self.canvas.bind("<Configure>", lambda e: self._layout())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Shift-Button-1>", lambda e: self._on_click(e, extend=True))
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.bind_mousewheel(self.canvas)

    # --- adatok ------------------------------------------------------------
    def set_items(self, paths, labels):
        """Új mappa: a régi bélyegképek és kijelölés eldobása."""
        self.loader.clear()
        self.pending.clear()
        self.photos.clear()
        self.selected.clear()
        self.anchor = None
        self.labels = labels
        self.show(paths)
        self.canvas.yview_moveto(0)

    def show(self, paths):
        """Szűrés: csak a látható lista változik, a kijelölés és a bélyegképek megmaradnak."""
        self.paths = list(paths)
        self._layout(force=True)

    def visible_selected(self):
        return [p for p in self.paths if p in self.selected]

    def select_all(self, value=True):
        if value:
            self.selected.update(self.paths)
        else:
            self.selected.difference_update(self.paths)
        self.redraw()
        self.on_selection_change()

    def set_colors(self, **colors):
        self.colors.update(colors)
        self.canvas.configure(bg=self.colors["canvas"])
        self.redraw()

    # --- rajzolás ----------------------------------------------------------
    def _yview(self, *args):
        self.canvas.yview(*args)
        self.schedule_redraw()

    def _layout(self, force=False):
        cols = max(1, self.canvas.winfo_width() // self.CELL_W)
        if cols != self.cols or force:
            self.cols = cols
            rows = (len(self.paths) + cols - 1) // cols
            self.canvas.configure(scrollregion=(0, 0, cols * self.CELL_W, max(rows * self.CELL_H, 1)))
        self.redraw()

    def schedule_redraw(self):
        if self._redraw_job is None:
            self._redraw_job = self.after_idle(self.redraw)

    def _visible_range(self):
        top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        first = max(0, int(top // self.CELL_H)) * self.cols
        last = min(len(self.paths), (int((top + height) // self.CELL_H) + 1) * self.cols)
        return first, last

    def redraw(self):
        self._redraw_job = None
        c, col = self.canvas, self.colors
        c.delete("cell")
        first, last = self._visible_range()
        for i in range(first, last):
            path = self.paths[i]
            x0, y0 = (i % self.cols) * self.CELL_W, (i // self.cols) * self.CELL_H
            tx, ty = x0 + self.THUMB_X, y0 + self.THUMB_Y
            sel = path in self.selected
            if sel:
                c.create_rectangle(x0 + 3, y0 + 1, x0 + self.CELL_W - 3, y0 + self.CELL_H - 2,
                                   fill=col["select_fill"], outline=col["select"], width=2, tags="cell")
            photo = self.photos.get(path)
            if photo is not None:
                self.photos.move_to_end(path)
                c.create_image(tx + 75, ty + 75, image=photo, tags="cell")
            else:
                c.create_rectangle(tx, ty, tx + 150, ty + 150, fill=col["thumb"], outline="", tags="cell")
                self._request(path)
            # Jelölőnégyzet és mappa jel a kép bal és jobb alsó sarkában
            bx, by = tx + 4, ty + 128
            c.create_rectangle(bx, by, bx + 18, by + 18, fill=col["select"] if sel else "white",
                               outline=col["select"] if sel else "#6b7280", width=1, tags="cell")
            if sel:
                c.create_line(bx + 4, by + 9, bx + 8, by + 13, bx + 14, by + 5, fill="white", width=2,
                              tags="cell")
            c.create_text(tx + 140, ty + 137, text="📁", tags="cell")
            if path in self.live:
                c.create_rectangle(tx + 3, ty + 3, tx + 37, ty + 17, fill="#000000", outline="", tags="cell")
                c.create_text(tx + 20, ty + 10, text="LIVE", fill="#ffffff", font=("TkDefaultFont", 7, "bold"),
                              tags="cell")
            c.create_text(x0 + self.CELL_W // 2, ty + 154, text=short_name(self.labels.get(path, path)),
                          width=self.CELL_W - 14, anchor="n", fill=col["fg"], justify="center", tags="cell")

    # --- bélyegképek -------------------------------------------------------
    def _request(self, path):
        if path in self.pending:
            return
        self.pending.add(path)
        self.loader.add_task(path, partial(self.call_in_ui, self._thumb_ready, path))

    def _thumb_ready(self, path, pil_image):
        """Fő szálon fut (call_in_ui-n keresztül)."""
        self.pending.discard(path)
        if path not in self.labels:
            return
        self.photos[path] = ImageTk.PhotoImage(pil_image, master=self)
        while len(self.photos) > self.MAX_PHOTOS:
            self.photos.popitem(last=False)
        first, last = self._visible_range()
        if path in self.paths[first:last]:
            self.schedule_redraw()

    # --- egér --------------------------------------------------------------
    def _hit(self, event):
        """(index, cellán belüli x, y) vagy None."""
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        col, row = int(x // self.CELL_W), int(y // self.CELL_H)
        if col >= self.cols or x < 0 or y < 0:
            return None
        i = row * self.cols + col
        if i >= len(self.paths):
            return None
        return i, x - col * self.CELL_W, y - row * self.CELL_H

    def _on_click(self, event, extend=False):
        hit = self._hit(event)
        if hit is None:
            return
        i, cx, cy = hit
        path = self.paths[i]
        if 132 <= cx <= 160 and 128 <= cy <= 152 and not extend:
            self.on_locate(path)
            return
        if extend and self.anchor in self.paths:
            a = self.paths.index(self.anchor)
            lo, hi = sorted((a, i))
            self.selected.update(self.paths[lo:hi + 1])
        else:
            self.selected.symmetric_difference_update({path})
            self.anchor = path
        self.redraw()
        self.on_selection_change()

    def _on_double(self, event):
        hit = self._hit(event)
        if hit is None:
            return
        path = self.paths[hit[0]]
        # A dupla kattintás első fele már átváltotta a kijelölést: visszaállítjuk
        self.selected.symmetric_difference_update({path})
        self.redraw()
        self.on_selection_change()
        self.on_open(path)

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
            # Érintőpadon a delta 120-nál kisebb is lehet: legalább egy lépés legyen
            step = -event.delta / 120
            self.canvas.yview_scroll(int(step) or (-1 if event.delta > 0 else 1), "units")
        elif IS_MAC:
            self.canvas.yview_scroll(int(-1 * event.delta), "units")
        elif event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        self.schedule_redraw()


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
                ('UI', {'theme': DEFAULT_APPEARANCE, 'language': 'hu', 'recursive': 'yes', 'last_folder': '',
                        'move_base': ''}),
                ('Naming', {'pattern': DEFAULT_PATTERN, 'recent_suffixes': '[]', 'place': 'no'})):
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
    def place_enabled(self):
        try:
            return self.config.getboolean('Naming', 'place')
        except ValueError:
            return False

    def effective_pattern(self):
        """A sablon; ha a „Helyszín a névben” be van kapcsolva, a {place} mezővel kiegészítve."""
        return pattern_with_place(self.pattern) if self.place_enabled else self.pattern

    @property
    def move_base(self):
        """Mozgatáskor az új mappa helye; üres, ha nincs megadva vagy nem elérhető (pl. kihúzott pendrive)."""
        folder = self.config['UI']['move_base']
        return folder if folder and os.path.isdir(folder) else ""

    @move_base.setter
    def move_base(self, folder):
        self.config['UI']['move_base'] = folder

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
        lb = tk.Listbox(self)
        self._system_listbox = (lb.cget("background"), lb.cget("foreground"))
        lb.destroy()
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

        self.async_loader = AsyncThumbnailLoader()
        self.async_loader.start()
        self.date_cache = DateCache()
        self._index_generation = 0
        self.filter_frame = tk.Frame(self)
        self.grid_view = ThumbGrid(self, self.async_loader, self.call_in_ui, on_open=self.open_media,
                                   on_locate=self.open_file_location, on_selection_change=self._update_counts)
        self.btn_frame = tk.Frame(self)
        status_frame = tk.Frame(self, bd=1, relief=tk.SUNKEN)
        self.status_bar = tk.Label(status_frame, text=self.t("ready"), anchor=tk.W)
        self.count_label = tk.Label(status_frame, text="", anchor=tk.E)
        self.count_label.pack(side=tk.RIGHT, padx=4)
        self.status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.filter_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 0))
        self.grid_view.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.icons = {key: self.load_icon(name) for key, name in {
            "folder": "folder.png", "rename": "rename.png", "refresh": "refresh.png",
            "unmark": "unmark.png", "markall": "MarkAll.png", "delete": "delete.png",
            "exit": "exit.png"}.items()}

        self.recursive_var = tk.BooleanVar(value=self.settings.config.getboolean('UI', 'recursive'))
        self.history = UndoHistory(os.path.join(_config_dir(), "history.json"))
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
        self._build_filter_bar()
        for seq in ("<Control-a>", "<Control-A>"):
            self.bind_all(seq, self._on_select_all_key)
        # A bélyegkép-gyorsítótár méretének korlátozása a háttérben
        threading.Thread(target=ThumbnailGenerator.cache.prune, daemon=True).start()
        self.prev_suffixes = self.settings.recent_suffixes
        self.busy = False
        self.running = True
        self.folder = ""
        self.moved_out = set()  # új mappába mozgatott fájlok: az almappákból se töltődjenek vissza a listába

        self.daysort_button = tk.Button(self.btn_frame, text=self.t("btn_daysort"), image=self.icons["folder"],
                                        compound="left", padx=4, command=self.sort_by_day)
        self.daysort_button.pack(side=tk.LEFT, padx=2)
        self.action_buttons.append(self.daysort_button)
        # Keskeny ablakban a gombok új sorba törnek, egyik sem csúszik ki (a Törlés és Kilépés a végére kerül)
        self._flow_order = self.action_buttons[1:] + [self.delete_button, self.exit_button]
        for btn in self._flow_order:
            btn.pack_forget()
        self.btn_frame.bind("<Configure>", lambda e: self._flow_buttons())
        self._flow_buttons()

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

    def _flow_buttons(self):
        """Az alsó gombsor tördelése az ablak szélességéhez (sorfolytonos elrendezés)."""
        width = self.btn_frame.winfo_width()
        if width <= 1:
            width = self.winfo_width() if self.winfo_width() > 1 else 1000
        x = y = row_h = 0
        pad = 2
        for btn in self._flow_order:
            w, h = btn.winfo_reqwidth(), btn.winfo_reqheight()
            if x and x + w > width:
                x, y, row_h = 0, y + row_h + pad, 0
            btn.place(x=x + pad, y=y + pad)
            x += w + 2 * pad
            row_h = max(row_h, h)
        height = y + row_h + 2 * pad
        if int(self.btn_frame.cget("height")) != height:
            self.btn_frame.configure(height=height)

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
        self.place_var = tk.BooleanVar(value=self.settings.place_enabled)
        config_menu.add_checkbutton(label=self.t("menu_place"), variable=self.place_var,
                                    command=self._on_place_toggle,
                                    state=tk.NORMAL if _place_index.available() else tk.DISABLED)
        config_menu.add_checkbutton(label=self.t("chk_recursive"), variable=self.recursive_var,
                                    command=self._on_recursive_toggle)
        menu.add_cascade(label=self.t("menu_settings"), menu=config_menu)
        edit_menu = tk.Menu(menu, tearoff=0)
        edit_menu.add_command(label=self.t("btn_undo"), accelerator="Ctrl+Z", command=self.undo_last)
        edit_menu.add_command(label=self.t("btn_daysort"), command=self.sort_by_day)
        edit_menu.add_command(label=self.t("menu_duplicates"), command=self.find_duplicates_ui)
        menu.add_cascade(label=self.t("menu_edit"), menu=edit_menu)
        self.config(menu=menu)
        self.edit_menu = edit_menu
        self._refresh_undo_label()

    def _refresh_undo_label(self):
        """A Szerkesztés menü első sora megmutatja, mi lenne visszavonva."""
        step = self.history.last()
        if step:
            label = self.t("undo_menu", what=self.t("history_" + step["kind"]), n=len(step["moves"]),
                           time=step["time"])
        else:
            label = self.t("btn_undo")
        self.edit_menu.entryconfigure(0, label=label, state=tk.NORMAL if step else tk.DISABLED)

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
        example = render_name(template, datetime(2024, 5, 1, 14, 30, 0), "Balaton", 0, 1, "IMG_1234", ".jpg", "Siófok")
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
        st.configure("TCombobox", fieldbackground=c["field"], foreground=c["fg"], background=c["button"],
                     arrowcolor=c["fg"], lightcolor=c["field"], darkcolor=c["field"])
        st.map("TCombobox", fieldbackground=[("readonly", c["field"])], foreground=[("readonly", c["fg"])],
               selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["fg"])],
               background=[("active", c["button_active"])])
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

        # A legördülő lista (Combobox) klasszikus Tk Listbox: a színét az option adatbázis adja
        if name == "system":
            lb_bg, lb_fg = self._system_listbox
        else:
            lb_bg, lb_fg = colors["field"], colors["fg"]
        self.option_add("*TCombobox*Listbox.background", lb_bg, 70)
        self.option_add("*TCombobox*Listbox.foreground", lb_fg, 70)
        fg = palette["foreground"]
        select = colors.get("select_bg", "#2563eb")
        self.grid_view.set_colors(canvas=colors["canvas"], thumb=colors["thumb"], fg=fg, select=select,
                                  select_fill=_blend(self._rgb(select), self._rgb(colors["canvas"]), 0.22))
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

    def _rgb(self, color):
        """Bármilyen Tk színnév (pl. "white", "SystemButtonFace") -> (r, g, b) 0-255."""
        return tuple(v // 257 for v in self.winfo_rgb(color))

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

    def _on_place_toggle(self):
        self.settings.config['Naming']['place'] = 'yes' if self.place_var.get() else 'no'
        self.settings.save_settings()
        if self.place_var.get():
            example = render_name(self.settings.effective_pattern(), datetime(2024, 7, 12, 14, 30, 0), "Balaton",
                                  place="Siófok", ext=".jpg")
            self.show_info(self.t("info"), self.t("place_on", example=example))

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
        self.moved_out.clear()
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

    def update_gui(self, files):
        files = [p for p in files if _key(p) not in self.moved_out]
        self.files = files
        recursive = self.recursive_var.get()
        labels = {p: os.path.relpath(p, self.folder) if recursive else os.path.basename(p) for p in files}
        self.grid_view.live = set(find_live_pairs(files))
        self.grid_view.set_items(self.filtered(files), labels)
        self._update_counts()
        self.set_status(self.t("loaded", n=len(files)))
        self._start_date_index(files)

    # --- szűrés ------------------------------------------------------------
    def _build_filter_bar(self):
        f = self.filter_frame
        self.filter_kind = tk.StringVar(value="all")
        self.filter_text = tk.StringVar()
        self.filter_from = tk.StringVar()
        self.filter_to = tk.StringVar()
        self.filter_file_dated = tk.BooleanVar(value=False)
        kinds = {self.t("filter_" + k): k for k in FILTER_KINDS}
        tk.Label(f, text=self.t("filter_kind")).pack(side=tk.LEFT)
        combo = ttk.Combobox(f, state="readonly", width=8, values=list(kinds))
        combo.set(self.t("filter_all"))
        combo.bind("<<ComboboxSelected>>", lambda e: (self.filter_kind.set(kinds[combo.get()]), self.apply_filter()))
        combo.pack(side=tk.LEFT, padx=(2, 10))
        tk.Label(f, text=self.t("filter_search")).pack(side=tk.LEFT)
        ttk.Entry(f, textvariable=self.filter_text, width=12).pack(side=tk.LEFT, padx=(2, 10))
        tk.Label(f, text=self.t("filter_from")).pack(side=tk.LEFT)
        ttk.Entry(f, textvariable=self.filter_from, width=10).pack(side=tk.LEFT, padx=2)
        tk.Label(f, text=self.t("filter_to")).pack(side=tk.LEFT)
        ttk.Entry(f, textvariable=self.filter_to, width=10).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Checkbutton(f, text=self.t("filter_file_dated"), variable=self.filter_file_dated,
                        command=self.apply_filter).pack(side=tk.LEFT)
        for var in (self.filter_text, self.filter_from, self.filter_to):
            var.trace_add("write", lambda *a: self._schedule_filter())
        self._filter_job = None

    def _schedule_filter(self):
        # Gépelés közben ne szűrjön minden leütésre
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(250, self.apply_filter)

    def filtered(self, files):
        try:
            day_from, day_to = parse_day(self.filter_from.get()), parse_day(self.filter_to.get())
        except ValueError:
            day_from = day_to = None  # félig beírt dátum: addig nem szűr dátumra
        return filter_paths(files, self.filter_kind.get(), self.filter_text.get(), day_from, day_to,
                            self.filter_file_dated.get(), self.date_cache.peek)

    def apply_filter(self):
        self._filter_job = None
        self.grid_view.show(self.filtered(self.files))
        self._update_counts()

    def filter_active(self):
        return (self.filter_kind.get() != "all" or self.filter_text.get().strip() or self.filter_from.get().strip()
                or self.filter_to.get().strip() or self.filter_file_dated.get())

    def _update_counts(self):
        shown, total = len(self.grid_view.paths), len(self.files)
        text = self.t("count_selected", sel=len(self.grid_view.visible_selected()), shown=shown)
        if shown != total:
            text += self.t("count_filtered", total=total)
        self.count_label.config(text=text)

    def _start_date_index(self, files):
        """A dátumok beolvasása a háttérben, hogy a dátumszűrő és az átnevezés gyors legyen."""
        self._index_generation += 1
        gen = self._index_generation

        def work():
            for i, path in enumerate(files, 1):
                if gen != self._index_generation or not self.running:
                    return
                try:
                    self.date_cache.get(path)
                except OSError:
                    continue
                if i % 200 == 0:
                    self.call_in_ui(self._on_dates_progress, gen)
            self.call_in_ui(self._on_dates_progress, gen)

        threading.Thread(target=work, daemon=True).start()

    def _on_dates_progress(self, gen):
        # Fő szálon: a Tk változókat csak itt szabad olvasni
        if gen == self._index_generation and self.filter_active():
            self.apply_filter()

    def _on_select_all_key(self, event):
        if isinstance(event.widget, (tk.Entry, ttk.Entry)) or event.widget.winfo_toplevel() is not self:
            return
        self.mark_all()

    # --- megnyitás / lejátszás ---------------------------------------------
    def open_media(self, path):
        if is_video(path):
            self.open_video_player(path)
        else:
            self.open_file(path)

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
        """A kijelölt és a szűrés szerint látható fájlok (az elrejtettekhez nem nyúlunk)."""
        return self.grid_view.visible_selected()

    def rename_selected(self):
        """Átnevezés: téma választása, dátumok olvasása, előnézet (időeltolással), végrehajtás."""
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
        pattern, base_folder = self.settings.effective_pattern(), self.folder
        move_root = self.settings.move_base or base_folder
        # Live Photo: a fotó és a videója együtt mozog, akkor is, ha csak az egyik van kijelölve
        selected, partners = with_live_partners(selected, self.files)
        followers = {v for vids in partners.values() for v in vids}
        places = {}

        def work():
            items = []
            for i, path in enumerate(selected, 1):
                self.call_in_ui(self.set_status, self.t("reading_dates", i=i, n=len(selected)))
                dt, source = self.date_cache.get(path)
                items.append((path, dt, source))
                if "{place}" in pattern and path not in followers:
                    places[path] = get_place(path)
            return items

        self.run_in_background(work, lambda items: self.after(
            0, self._rename_preview, items, suffix, move_files, pattern, base_folder, partners, places, move_root))

    def _center_pos(self, width, height):
        """Wm geometry pozíció, amivel egy ekkora ablak a főablak közepére kerül."""
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        return f"+{x}+{y}"

    def _add_shift_row(self, win, on_change):
        """Időeltolás mező az előnézetekhez. Vissza: függvény, ami a timedelta-t adja (hibánál None)."""
        row = tk.Frame(win)
        row.pack(fill=tk.X, padx=10, pady=4)
        tk.Label(row, text=self.t("shift_label")).pack(side=tk.LEFT)
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=10).pack(side=tk.LEFT, padx=4)
        hint = tk.Label(row, text=self.t("shift_hint"), anchor="w")
        hint.pack(side=tk.LEFT, fill=tk.X, expand=True)
        normal_fg, job = hint.cget("foreground"), {}

        def value():
            try:
                return parse_shift(var.get())
            except ValueError:
                return None

        def changed(*_):
            ok = value() is not None
            hint.config(text=self.t("shift_hint" if ok else "shift_invalid"),
                        foreground=normal_fg if ok else self.colors["warn"])
            if job.get("id"):
                win.after_cancel(job["id"])
            job["id"] = win.after(300, on_change)

        var.trace_add("write", changed)
        return value

    def _preview_tree(self, win, columns):
        frame = tk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        tree = ttk.Treeview(frame, columns=[c for c, _, _ in columns[1:]], show="tree headings")
        for col, text, width in columns:
            tree.heading(col, text=text)
            tree.column(col, width=width, stretch=col != "#0")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return tree

    def _preview_buttons(self, win, accept):
        bottom = tk.Frame(win)
        bottom.pack(pady=10)
        ok_btn = ttk.Button(bottom, text=self.t("ok"), command=accept)
        ok_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text=self.t("cancel"), command=win.destroy).pack(side=tk.LEFT, padx=4)
        win.bind("<Return>", lambda e: accept())
        win.bind("<Escape>", lambda e: win.destroy())
        return ok_btn

    def _rename_preview(self, items, suffix, move_files, pattern, base_folder, partners=None, places=None,
                        move_root=None):
        self.set_status(self.t("ready"))
        file_dated = {path for path, _, source in items if source == "file"}
        name_dated = {path for path, _, source in items if source == "filename"}
        state, result = {}, {"ok": False}

        win = tk.Toplevel(self)
        win.title(self.t("rename_preview_title"))
        win.transient(self)
        win.geometry("860x520" + self._center_pos(860, 520))
        summary = tk.Label(win, justify=tk.LEFT, anchor="w", wraplength=820)
        summary.pack(fill=tk.X, padx=10, pady=(10, 4))
        if file_dated:
            tk.Label(win, text=self.t("daysort_file_dates", n=len(file_dated)), justify=tk.LEFT,
                     anchor="w", wraplength=820, fg=self.colors["warn"]).pack(fill=tk.X, padx=10)
        shift = self._add_shift_row(win, lambda: refresh())
        tree = self._preview_tree(win, [("#0", self.t("col_old"), 260), ("date", self.t("col_date"), 160),
                                        ("new", self.t("daysort_col_new"), 360)])

        def accept():
            if state.get("plan"):
                result["ok"] = True
                win.destroy()

        ok_btn = self._preview_buttons(win, accept)

        def refresh():
            delta = shift()
            if delta is None:
                ok_btn.state(["disabled"])
                return
            shifted = [(p, dt + delta) for p, dt, _ in items]
            target = move_target_folder(move_root or base_folder, shifted, suffix) if move_files else None
            plan = plan_renames(shifted, suffix, pattern, target, partners=partners, places=places)
            dates = dict(shifted)
            for photo, videos in (partners or {}).items():
                dates.update((v, dates[photo]) for v in videos if photo in dates)
            state.update(plan=plan, target=target)
            tree.delete(*tree.get_children())
            unchanged = 0
            for old, new in plan:
                same = old == new
                unchanged += same
                mark = " *" if old in file_dated else self.t("from_name") if old in name_dated else ""
                tree.insert("", tk.END, text=os.path.relpath(old, base_folder),
                            values=(dates[old].strftime("%Y-%m-%d %H:%M:%S") + mark,
                                    self.t("unchanged_mark") if same else
                                    # A cél másik meghajtón is lehet, a betöltött mappához képest nincs relatív út
                                    (os.path.relpath(new, os.path.dirname(target)) if target
                                     else os.path.basename(new))))
            text = self.t("rename_preview_summary", n=len(plan) - unchanged, unchanged=unchanged)
            if target:
                text += "\n" + self.t("moved_to", folder=target).strip()
            summary.config(text=text)
            ok_btn.state(["!disabled"] if len(plan) > unchanged else ["disabled"])

        refresh()
        win.focus_set()
        win.grab_set()
        self.wait_window(win)
        if result["ok"]:
            self._rename_run(state["plan"], state["target"], len(file_dated))

    def _rename_run(self, plan, target_folder, file_dated):
        self.close_video_player()  # Windowson a lejátszott fájl nem nevezhető át

        def work():
            created = False
            if target_folder:
                created = not os.path.isdir(target_folder)
                os.makedirs(target_folder, exist_ok=True)
            done, unchanged, errors = execute_plan(
                plan, lambda i, n: self.call_in_ui(self.set_status, self.t("renaming", i=i, n=n)))
            if created and not done:
                remove_empty_folders([target_folder])  # semmi sem került bele: ne maradjon üres mappa
            return {"done": done, "unchanged": unchanged, "errors": errors, "file_dated": file_dated,
                    "target": target_folder, "created": target_folder if created else None}

        self.run_in_background(work, self._rename_finished)

    def _rename_finished(self, r):
        if r["done"]:
            self.history.push("rename", r["done"], [r["created"]] if r["created"] else [])
            self._refresh_undo_label()
        if r["target"]:
            self.moved_out.update(_key(new) for _, new in r["done"])
        self.load_media()  # a lista már az üzenetablak mögött is a friss állapotot mutassa
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

    def undo_last(self):
        if self.busy:
            return
        step = self.history.last()
        if not step:
            self.show_info(self.t("info"), self.t("undo_none"))
            return
        if not messagebox.askyesno(self.t("btn_undo"), self.t(
                "undo_confirm", what=self.t("history_" + step["kind"]), time=step["time"],
                n=len(step["moves"]), left=len(self.history) - 1)):
            return
        reverse_plan = [(new, old) for old, new in reversed(step["moves"])]
        created = step["created"]
        self.close_video_player()

        def work():
            done, _, errors = execute_plan(reverse_plan)
            remove_empty_folders(created)
            return done, errors

        def finished(result):
            done, errors = result
            self.history.pop()
            self._refresh_undo_label()
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
            shown = list(self.grid_view.paths)  # szűrésnél csak a láthatók
            if not shown:
                messagebox.showinfo(self.t("none_selected_title"), self.t("none_selected"))
                return
            if not messagebox.askyesno(self.t("btn_daysort"), self.t("daysort_all", n=len(shown))):
                return
            selected = shown
        base_folder = self.folder
        selected, partners = with_live_partners(selected, self.files)

        def work():
            items = []
            for i, path in enumerate(selected, 1):
                self.call_in_ui(self.set_status, self.t("reading_dates", i=i, n=len(selected)))
                dt, source = self.date_cache.get(path)
                items.append((path, dt, source))
            return items

        # Az előnézet saját eseményhurkot futtat, ezért ne a UI-sor feldolgozásán belül nyíljon meg
        self.run_in_background(work, lambda items: self.after(
            0, self._daysort_preview, base_folder, items, partners))

    def _daysort_preview(self, base_folder, items, partners=None):
        self.set_status(self.t("ready"))
        file_dated = {path for path, _, source in items if source == "file"}
        name_dated = {path for path, _, source in items if source == "filename"}
        dates = {path: dt for path, dt, _ in items}
        include_var = tk.BooleanVar(value=True)
        result = {"ok": False}

        win = tk.Toplevel(self)
        win.title(self.t("daysort_title"))
        win.transient(self)
        win.geometry("760x480" + self._center_pos(760, 480))
        summary = tk.Label(win, justify=tk.LEFT, anchor="w", wraplength=720)
        summary.pack(fill=tk.X, padx=10, pady=(10, 4))
        if file_dated:
            tk.Label(win, text=self.t("daysort_file_dates", n=len(file_dated)), justify=tk.LEFT,
                     anchor="w", wraplength=720, fg=self.colors["warn"]).pack(fill=tk.X, padx=10)
            ttk.Checkbutton(win, text=self.t("daysort_include_file"), variable=include_var,
                            command=lambda: refresh()).pack(anchor="w", padx=10, pady=4)
        shift = self._add_shift_row(win, lambda: refresh())

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
            delta = shift()
            if delta is None:
                ok_btn.state(["disabled"])
                return
            chosen = [(p, dt + delta) for p, dt in dates.items() if include_var.get() or p not in file_dated]
            plan, in_place = plan_day_sort(chosen, base_folder, partners=partners)
            state["plan"] = plan
            tree.delete(*tree.get_children())
            days = {}
            for old, new in plan:
                folder = os.path.dirname(new)
                if folder not in days:
                    label = os.path.basename(folder) + ("" if os.path.isdir(folder) else " (+)")
                    days[folder] = tree.insert("", tk.END, text=label, open=len(plan) <= 200)
                mark = " *" if old in file_dated else self.t("from_name") if old in name_dated else ""
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
                self.history.push("daysort", done, created)
                self._refresh_undo_label()
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

    # --- duplikátumok ------------------------------------------------------
    def find_duplicates_ui(self):
        """Azonos tartalmú fájlok keresése a kijelöltek (ha nincs kijelölés, a láthatók) között."""
        if self.busy:
            self.show_info(self.t("info"), self.t("busy"))
            return
        paths = self.selected_paths() or list(self.grid_view.paths)
        if len(paths) < 2:
            self.show_info(self.t("info"), self.t("dup_none"))
            return

        def work():
            return find_duplicates(paths, lambda i, n: self.call_in_ui(
                self.set_status, self.t("dup_progress", i=i, n=n)))

        self.run_in_background(work, lambda groups: self.after(0, self._show_duplicates, groups))

    def _show_duplicates(self, groups):
        self.set_status(self.t("ready"))
        if not groups:
            self.show_info(self.t("info"), self.t("dup_none"))
            return
        extra = [p for g in groups for p in g[1:]]
        size = sum(os.path.getsize(p) for p in extra if os.path.exists(p))
        win = tk.Toplevel(self)
        win.title(self.t("dup_title"))
        win.transient(self)
        win.geometry("820x480" + self._center_pos(820, 480))
        tk.Label(win, text=self.t("dup_summary", g=len(groups), n=len(extra), mb=size / 1024 / 1024),
                 justify=tk.LEFT, anchor="w", wraplength=780).pack(fill=tk.X, padx=10, pady=(10, 4))
        tree = self._preview_tree(win, [("#0", self.t("dup_col_file"), 520), ("role", "", 200)])
        for i, group in enumerate(groups, 1):
            node = tree.insert("", tk.END, text=self.t("dup_group", i=i, n=len(group)), open=True)
            for j, p in enumerate(group):
                tree.insert(node, tk.END, text=os.path.relpath(p, self.folder) if self.folder else p,
                            values=(self.t("dup_keep") if j == 0 else self.t("dup_copy"),))

        def select_copies():
            self.grid_view.selected = set(extra)
            self.grid_view.redraw()
            self._update_counts()
            win.destroy()
            self.show_info(self.t("info"), self.t("dup_selected", n=len(extra)))

        bottom = tk.Frame(win)
        bottom.pack(pady=10)
        ttk.Button(bottom, text=self.t("dup_select"), command=select_copies).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text=self.t("cancel"), command=win.destroy).pack(side=tk.LEFT, padx=4)
        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_set()

    def get_suffix(self):
        """Téma választó ablak pipálható mozgatási opcióval és választható célmappával"""
        result = {"suffix": None, "move": False}
        win = tk.Toplevel(self)
        win.withdraw()  # csak a végleges helyén jelenjen meg, ne villanjon fel a képernyő sarkában
        win.title(self.t("suffix_title"))
        win.transient(self)
        win.minsize(620, 0)

        tk.Label(win, text=self.t("suffix_prompt")).pack(pady=(14, 5), padx=20)
        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=5)

        move_var = tk.BooleanVar(value=False)
        saved_base = self.settings.move_base
        base_var = tk.StringVar(value=saved_base)

        def choose(value):
            value = value.strip()
            if value:
                result["suffix"] = value
                result["move"] = move_var.get()
                if base_var.get() != saved_base:  # egy épp kihúzott pendrive ne vesszen el a beállításból
                    self.settings.move_base = base_var.get()
                win.destroy()

        for s in self.prev_suffixes:
            ttk.Button(btn_frame, text=s, width=25, command=partial(choose, s)).pack(pady=2)

        suffix_var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=suffix_var, width=30)
        entry.pack(fill=tk.X, pady=5, padx=20)
        entry.focus_set()

        ttk.Checkbutton(win, text=self.t("move_check"), variable=move_var).pack(anchor="w", padx=20, pady=(10, 2))
        base_row = tk.Frame(win)
        base_row.pack(fill=tk.X, padx=20, pady=2)
        tk.Label(base_row, text=self.t("move_base_label")).pack(side=tk.LEFT)
        base_label = tk.Label(base_row, anchor="w")
        base_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        def browse():
            folder = filedialog.askdirectory(parent=win, title=self.t("move_base_title"),
                                             initialdir=base_var.get() or self.folder or None)
            if folder:
                base_var.set(os.path.normpath(folder))
                move_var.set(True)

        reset_btn = ttk.Button(base_row, text=self.t("move_base_reset"), command=lambda: base_var.set(""))
        reset_btn.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(base_row, text=self.t("move_base_browse"), command=browse).pack(side=tk.RIGHT)
        info = tk.Label(win, justify=tk.LEFT, anchor="w", wraplength=580)
        info.pack(fill=tk.X, padx=20, pady=(2, 6))

        day = self._earliest_known_day(self.selected_paths()) or self.t("move_date_placeholder")

        def update_move_info(*_):
            topic = suffix_var.get().strip()
            topic = sanitize_component(topic) if topic else self.t("move_topic_placeholder")
            base_label.config(text=base_var.get() or self.t("move_base_current"))
            reset_btn.state(["!disabled"] if base_var.get() else ["disabled"])
            info.config(text=self.t("move_folder", path=os.path.join(base_var.get() or self.folder, f"{day}_{topic}")),
                        state=tk.NORMAL if move_var.get() else tk.DISABLED)

        for var in (suffix_var, base_var, move_var):
            var.trace_add("write", update_move_info)
        update_move_info()

        bottom = tk.Frame(win)
        bottom.pack(pady=10)
        ttk.Button(bottom, text=self.t("ok"), command=lambda: choose(suffix_var.get())).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text=self.t("cancel"), command=win.destroy).pack(side=tk.LEFT, padx=4)
        win.bind("<Return>", lambda e: choose(suffix_var.get()))
        win.bind("<Escape>", lambda e: win.destroy())

        win.update_idletasks()
        win.geometry(self._center_pos(max(620, win.winfo_reqwidth()), win.winfo_reqheight()))
        win.deiconify()
        win.grab_set()
        self.wait_window(win)

        if result["suffix"]:
            # A legutóbb használt téma kerül előre, és a program újraindítása után is megmarad
            self.prev_suffixes = [result["suffix"]] + [s for s in self.prev_suffixes if s != result["suffix"]]
            self.settings.recent_suffixes = self.prev_suffixes
            self.settings.save_settings()
        return result["suffix"], result["move"]

    def _earliest_known_day(self, paths):
        """A legkorábbi felvétel napja a már beolvasott dátumokból; None, ha még nem mind ismert."""
        known = [self.date_cache.peek(p) for p in paths]
        if not known or any(k is None or k[0] is None for k in known):
            return None
        return min(k[0] for k in known).strftime("%Y-%m-%d")

    def unmark_all(self):
        self.grid_view.select_all(False)

    def mark_all(self):
        self.grid_view.select_all(True)

    # --- törlés ------------------------------------------------------------
    def delete_selected(self):
        if self.busy:
            return
        selected = self.selected_paths()
        if not selected:
            self.show_info(self.t("none_selected_title"), self.t("delete_none"))
            return
        selected, _ = with_live_partners(selected, self.files)  # a Live Photo videója is megy

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
        if not self.running:
            return  # már bezárva
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
