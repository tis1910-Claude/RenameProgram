"""Szűrés, dátum- és bélyegkép-gyorsítótár, valamint a bélyegképrács (ha van kijelző)."""
import os
import time
import tkinter as tk
from datetime import date, datetime

import pytest
from PIL import Image

import Keprename5video as m
from conftest import make_jpg


def test_parse_day():
    assert m.parse_day("2024-05-01") == date(2024, 5, 1)
    assert m.parse_day("2024.05.01.") == date(2024, 5, 1)
    assert m.parse_day("  ") is None
    with pytest.raises(ValueError):
        m.parse_day("2024-13")


def test_filter_paths():
    paths = ["/a/IMG_1.jpg", "/a/MOV_2.mp4", "/a/DSC_3.NEF", "/a/balaton.png"]
    dates = {"/a/IMG_1.jpg": (datetime(2024, 5, 1, 10), "exif"),
             "/a/MOV_2.mp4": (datetime(2024, 5, 3, 10), "video"),
             "/a/DSC_3.NEF": (datetime(2024, 5, 2, 10), "exif")}  # a PNG dátuma még nem ismert
    f = lambda **kw: m.filter_paths(paths, date_of=dates.get, **kw)
    assert f() == paths
    assert f(kind="videos") == ["/a/MOV_2.mp4"]
    assert f(kind="images") == ["/a/IMG_1.jpg", "/a/DSC_3.NEF", "/a/balaton.png"]
    assert f(kind="raw") == ["/a/DSC_3.NEF"]
    assert f(text="BALA") == ["/a/balaton.png"]
    assert f(day_from=date(2024, 5, 2)) == ["/a/MOV_2.mp4", "/a/DSC_3.NEF", "/a/balaton.png"]
    assert f(day_from=date(2024, 5, 2), day_to=date(2024, 5, 2)) == ["/a/DSC_3.NEF", "/a/balaton.png"]
    dates["/a/balaton.png"] = (datetime(2020, 1, 1), "file")
    assert f(only_file_dated=True) == ["/a/balaton.png"]


def test_date_cache_rereads_changed_file(tmp_path):
    path = make_jpg(str(tmp_path / "a.jpg"), "2023:07:15 10:20:30")
    calls = []
    cache = m.DateCache(lambda p: calls.append(p) or m.get_media_datetime(p))
    assert cache.peek(path) is None
    assert cache.get(path)[0] == datetime(2023, 7, 15, 10, 20, 30)
    cache.get(path)
    assert len(calls) == 1 and cache.peek(path)[1] == "exif"
    make_jpg(path, "2022:01:01 00:00:00", size=(10, 10))
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 10**9))
    assert cache.get(path)[0] == datetime(2022, 1, 1) and len(calls) == 2


def test_thumbnail_disk_cache(tmp_path):
    cache = m.ThumbnailCache(str(tmp_path / "cache"))
    m.ThumbnailGenerator.cache = cache
    path = make_jpg(str(tmp_path / "a.jpg"), size=(400, 300))
    first = m.ThumbnailGenerator.generate(path)
    files = [os.path.join(r, n) for r, _, ns in os.walk(cache.folder) for n in ns]
    assert len(files) == 1 and first.size[0] == 150
    assert cache.get(path, m.THUMB_SIZE).size == first.size
    # Hibás fájl szürke képe nem kerül a gyorsítótárba
    bad = str(tmp_path / "bad.jpg")
    open(bad, "wb").write(b"nem kep")
    m.ThumbnailGenerator.generate(bad)
    assert len([n for _, _, ns in os.walk(cache.folder) for n in ns]) == 1


def test_thumbnail_cache_prune(tmp_path):
    cache = m.ThumbnailCache(str(tmp_path / "c"), max_bytes=10_000)
    os.makedirs(cache.folder)
    for i in range(10):
        p = os.path.join(cache.folder, f"{i}.jpg")
        open(p, "wb").write(b"x" * 2000)
        os.utime(p, (1000 + i, 1000 + i))
    assert cache.prune() == 7  # 20 kB -> 7 kB alá (a keret 70%-a), a legrégebbiek mennek
    assert sorted(os.listdir(cache.folder)) == ["7.jpg", "8.jpg", "9.jpg"]


def test_short_name():
    assert m.short_name("rovid.jpg") == "rovid.jpg"
    s = m.short_name("nagyon_hosszu_fajlnev_ami_nem_fer_ki_a_cellaba_2024.jpg")
    assert len(s) == 40 and s.endswith("2024.jpg") and "…" in s


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setattr(m, "_config_dir", lambda: str(tmp_path / "cfg"))
    try:
        gui = m.ImageRenamerGUI()
    except tk.TclError as e:
        pytest.skip(f"nincs kijelző: {e}")
    gui.geometry("1000x700")
    yield gui
    gui.on_close()


def _pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def test_grid_click_select_and_filter(app, tmp_path):
    folder = tmp_path / "media"
    folder.mkdir()
    for i in range(60):
        make_jpg(str(folder / f"IMG_{i:03d}.jpg"), f"2023:07:{1 + i % 3:02d} 10:00:00", size=(40, 30))
    app._open_folder(str(folder))
    _pump(app, 2)
    g = app.grid_view
    assert len(g.paths) == 60
    assert len(g.photos) <= 60 and g.canvas.find_all()  # csak a látható cellák vannak kirajzolva

    class Ev:
        def __init__(self, i):
            self.x = (i % g.cols) * g.CELL_W + 80
            self.y = (i // g.cols) * g.CELL_H + 60

    g._on_click(Ev(0))
    g._on_click(Ev(4), extend=True)
    assert len(app.selected_paths()) == 5
    g._on_click(Ev(2))
    assert len(app.selected_paths()) == 4

    app.filter_from.set("2023-07-02")
    app.filter_to.set("2023-07-02")
    _pump(app, 1.5)
    assert len(g.paths) == 20
    assert all(p in g.paths for p in app.selected_paths())  # rejtett fájlhoz nem nyúl
    app.filter_from.set("")
    app.filter_to.set("")
    _pump(app, 0.5)
    assert len(app.selected_paths()) == 4
