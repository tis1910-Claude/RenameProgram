import os
import shutil
import subprocess
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe nincs a PATH-on")


def make_jpg(path, dt=None, orient=None, size=(400, 200), color="red"):
    """JPEG beágyazott DateTimeOriginal-lel (ÉÉÉÉ:HH:NN óó:pp:mm) és tájolással."""
    img = Image.new("RGB", size, color)
    ex = Image.Exif()
    if dt:
        ex.get_ifd(0x8769)[0x9003] = dt
    if orient:
        ex[0x0112] = orient
    img.save(path, exif=ex.tobytes())
    return path


def make_png(path, dt=None):
    ex = Image.Exif()
    if dt:
        ex.get_ifd(0x8769)[0x9003] = dt
    Image.new("RGB", (50, 50)).save(path, exif=ex.tobytes())
    return path


def make_video(path, seconds, creation_time=None):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
           f"testsrc=duration={seconds}:size=320x240:rate=10", "-pix_fmt", "yuv420p"]
    if creation_time:
        cmd += ["-metadata", f"creation_time={creation_time}"]
    subprocess.run(cmd + [path], check=True)
    return path


@pytest.fixture(autouse=True)
def _thumb_cache_in_tmp(tmp_path_factory, monkeypatch):
    """A tesztek ne a felhasználó valódi bélyegkép-gyorsítótárába írjanak."""
    import Keprename5video as m
    monkeypatch.setattr(m.ThumbnailGenerator, "cache", m.ThumbnailCache(str(tmp_path_factory.mktemp("thumbs"))))


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A teljes GUI, ideiglenes beállításokkal; kijelző nélkül a teszt kimarad."""
    import tkinter as tk
    import Keprename5video as m
    monkeypatch.setattr(m, "_config_dir", lambda: str(tmp_path / "cfg"))
    # Egy váratlan üzenetablak ne akassza meg a tesztet (a tesztek felülírhatják)
    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(m.messagebox, name, lambda *a, **k: None)
    for name in ("askyesno", "askokcancel"):
        monkeypatch.setattr(m.messagebox, name, lambda *a, **k: True)
    try:
        gui = m.ImageRenamerGUI()
    except tk.TclError as e:
        pytest.skip(f"nincs kijelző: {e}")
    gui.geometry("1000x700")
    yield gui
    if gui.running:
        pump(gui, 0, until=lambda: not gui.busy, limit=20)
    gui.on_close()


def pump(app, seconds, until=None, limit=10):
    """A Tk eseményhurok futtatása adott ideig (a háttérszálak eredményei így érkeznek meg),
    until megadásakor addig, amíg a feltétel teljesül (legfeljebb limit másodpercig)."""
    import time
    start = time.time()
    while True:
        elapsed = time.time() - start
        if until is not None and (until() or elapsed >= limit):
            break
        if until is None and elapsed >= seconds:
            break
        app.update()
        time.sleep(0.02)


def accept_dialog(app, prepare=None):
    """Megvárja a következő saját párbeszédablakot, előkészíti, majd az OK gombjával elfogadja.

    Nem Enter-eseményt küld: Windowson a billentyűesemény a fókuszban lévő ablakhoz megy,
    és ha az nem a párbeszédablak, a teszt örökre várna."""
    import tkinter as tk
    from tkinter import ttk
    import Keprename5video as m

    def press_ok(win):
        ok = app.t("ok")
        for w in m.ImageRenamerGUI._walk(win):
            if isinstance(w, ttk.Button) and w.cget("text") == ok:
                w.invoke()
                return

    def step():
        tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_exists()]
        if not tops:
            app.after(50, step)
            return
        win = tops[-1]
        if prepare:
            prepare(win)
        app.after(500, lambda: press_ok(win))  # az előnézet 300 ms után frissül

    app.after(50, step)
