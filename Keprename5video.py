"""Media Renamer Pro 4.1

Képek és videók csoportos átnevezése a felvétel dátuma és egy téma alapján,
opcionálisan közös (dátum_téma) mappába mozgatva.

Kötelező függőség: Pillow.
Opcionális: tkinterdnd2 (fogd és vidd), python-vlc + VLC (beépített lejátszó),
send2trash (törlés lomtárba), ffmpeg/ffprobe a PATH-on (videó dátum, bélyegkép).
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
from datetime import datetime, timezone
from functools import partial

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageTk, ImageOps, ImageDraw

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

APP_NAME = "Media Renamer Pro 4.1"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp", ".mts")
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


def is_media(path):
    return path.lower().endswith(MEDIA_EXTS)


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
        "undo_none": "Nincs visszavonható átnevezés.",
        "undo_confirm": "Visszavonod az utolsó átnevezést ({n} fájl)?",
        "undo_done": "{n} fájl visszanevezve.",
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
        "undo_confirm": "Undo the last rename ({n} files)?",
        "undo_done": "{n} files renamed back.",
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
    },
}


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


def get_exif_datetime(path):
    """DateTimeOriginal > DateTimeDigitized > DateTime. PNG/TIFF/WebP is jó."""
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
        print(f"EXIF hiba ({path}): {e}")
    return None


def parse_iso_datetime(text):
    """ISO 8601 dátum (pl. 2023-05-01T10:20:30.000000Z vagy ...+0200) helyi időre,
    időzóna nélkül. A 'Z'/eltolás nélküli értéket UTC-nek veszi (QuickTime szabvány)."""
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


def get_video_datetime(path):
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
        fields = {f for _, f, spec, conv in string.Formatter().parse(pattern) if f is not None}
    except ValueError as e:
        return str(e)
    unknown = fields - PATTERN_FIELDS
    if unknown:
        return "ismeretlen mező / unknown field: " + ", ".join("{%s}" % f for f in sorted(unknown))
    if "" in fields:
        return "üres {} mező / empty {} field"
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
    def _image(path, size):
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
                ('UI', {'theme': 'light', 'language': 'hu', 'recursive': 'yes', 'last_folder': ''}),
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


def fallback_icon(name, size=(32, 32)):
    """Hiányzó ikonfájl helyett: frissítéshez rajzolt környíl, egyébként átlátszó üres ikon."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    if name.lower().startswith("refresh"):
        w, h = size
        pad, color, width = w // 6, (40, 120, 200, 255), max(2, w // 10)
        draw = ImageDraw.Draw(img)
        draw.arc((pad, pad, w - pad, h - pad), start=30, end=330, fill=color, width=width)
        # Nyílhegy a körív felső végén (330°), az óramutató járásával megegyező irányba
        tip_x, tip_y = w - pad, h // 2 - h // 6
        draw.polygon([(tip_x - w // 5, tip_y - h // 10), (tip_x + w // 10, tip_y - h // 10),
                      (tip_x - w // 20, tip_y + h // 5)], fill=color)
    return img


class ImageRenamerGUI(_BaseTk):
    def __init__(self):
        super().__init__()
        self.settings = SettingsManager()
        self.lang = self.settings.language
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
        self.bind_all("<Control-z>", lambda e: self.undo_last())

        self.exit_button = tk.Button(self.btn_frame, text=self.t("btn_exit"), image=self.icons["exit"],
                                     compound="left", padx=4, command=self.on_close)
        self.exit_button.pack(side=tk.RIGHT, padx=2)
        self.delete_button = tk.Button(self.btn_frame, text=self.t("btn_delete"), image=self.icons["delete"],
                                       compound="left", padx=4, command=self.delete_selected)
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
                            compound="left", padx=4, command=cmd)
            btn.pack(side=tk.LEFT, padx=2)
            self.action_buttons.append(btn)

        self.files = []
        self.prev_suffixes = self.settings.recent_suffixes
        self.last_rename = []  # [(régi, új)] a visszavonáshoz
        self.last_created_folder = None
        self.busy = False
        self.running = True
        self.folder = ""
        self.async_loader = AsyncThumbnailLoader()
        self.async_loader.start()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if HAS_DND:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind('<<Drop>>', self._on_drop)
            except Exception as e:
                print(f"Fogd és vidd hiba: {e}")

        last = self.settings.config['UI'].get('last_folder', '')
        if last and os.path.isdir(last):
            self.folder = last
            self.load_media()

    # --- segédek -----------------------------------------------------------
    def t(self, key, **kwargs):
        text = TEXTS[self.lang].get(key) or TEXTS["hu"].get(key, key)
        return text.format(**kwargs) if kwargs else text

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
            return ImageTk.PhotoImage(fallback_icon(path, default_size))

    def setup_menu(self):
        menu = tk.Menu(self)
        config_menu = tk.Menu(menu, tearoff=0)
        config_menu.add_command(label=self.t("menu_templates"), image=self.icons["rename"],
                                compound="left", command=self.edit_templates)
        config_menu.add_command(label=self.t("menu_language"), image=self.icons["folder"],
                                compound="left", command=self.set_language)
        config_menu.add_separator()
        config_menu.add_checkbutton(label=self.t("chk_recursive"), variable=self.recursive_var,
                                    command=self._on_recursive_toggle)
        menu.add_cascade(label=self.t("menu_settings"), menu=config_menu)
        edit_menu = tk.Menu(menu, tearoff=0)
        edit_menu.add_command(label=self.t("btn_undo"), accelerator="Ctrl+Z", command=self.undo_last)
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

    def _on_recursive_toggle(self):
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
        self.scrollable_canvas.canvas.yview_moveto(0)

    def update_gui(self, files):
        self.clear_gui()
        self.files = files
        inner_frame = self.scrollable_canvas.inner_frame

        for path in files:
            frame = tk.Frame(inner_frame, width=160, height=180)
            frame.grid_propagate(False)

            lbl = tk.Label(frame, bg="#eeeeee")
            lbl.place(x=0, y=0, width=150, height=150)
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
            return {"done": done, "unchanged": unchanged, "errors": errors, "file_dated": file_dated,
                    "target": target_folder, "created": target_folder if created else None}

        self.run_in_background(work, self._rename_finished)

    def _rename_finished(self, r):
        if r["done"]:
            self.last_rename = r["done"]
            self.last_created_folder = r["created"]
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
        created = self.last_created_folder

        def work():
            done, _, errors = execute_plan(reverse_plan)
            if created and os.path.isdir(created) and not os.listdir(created):
                os.rmdir(created)
            return done, errors

        def finished(result):
            done, errors = result
            self.last_rename, self.last_created_folder = [], None
            msg = self.t("undo_done", n=len(done))
            if errors:
                self.show_error(msg + "\n\n" + self.t("rename_errors", n=len(errors)) + "\n".join(errors[:20]))
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
