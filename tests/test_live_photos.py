"""Live Photo párok (IMG_1234.HEIC + IMG_1234.MOV) együtt kezelése."""
import os
from datetime import datetime

import Keprename5video as m
from conftest import make_jpg, pump


def test_find_live_pairs():
    paths = ["/a/IMG_1.HEIC", "/a/IMG_1.MOV", "/a/IMG_2.jpg", "/a/img_3.JPG", "/a/IMG_3.mov", "/b/IMG_2.MOV",
             "/a/IMG_4.MOV"]
    assert m.find_live_pairs(paths) == {"/a/IMG_1.HEIC": ["/a/IMG_1.MOV"], "/a/img_3.JPG": ["/a/IMG_3.mov"]}


def test_with_live_partners_adds_missing_half():
    files = ["/a/IMG_1.HEIC", "/a/IMG_1.MOV", "/a/IMG_2.jpg"]
    assert m.with_live_partners(["/a/IMG_1.MOV"], files) == (files[:2], {"/a/IMG_1.HEIC": ["/a/IMG_1.MOV"]})
    assert m.with_live_partners(["/a/IMG_2.jpg"], files) == (["/a/IMG_2.jpg"], {})


def test_rename_keeps_pair_together_even_on_collision(tmp_path):
    photo, video = str(tmp_path / "IMG_1.HEIC"), str(tmp_path / "IMG_1.MOV")
    other = str(tmp_path / "IMG_2.jpg")
    for p in (photo, video, other):
        open(p, "w").close()
    # A videó név már foglalt: a párnak együtt kell _1-et kapnia
    open(str(tmp_path / "2023-07-15_10-00-00_X.MOV"), "w").close()
    dt = datetime(2023, 7, 15, 10, 0, 0)
    items = [(photo, dt), (video, datetime(2023, 7, 15, 8, 0, 0)), (other, dt)]  # a videó ideje UTC lehet
    plan = dict(m.plan_renames(items, "X", m.DEFAULT_PATTERN, partners={photo: [video]}))
    assert os.path.basename(plan[photo]) == "2023-07-15_10-00-00_X_1.HEIC"
    assert os.path.basename(plan[video]) == "2023-07-15_10-00-00_X_1.MOV"
    assert os.path.basename(plan[other]) == "2023-07-15_10-00-00_X.jpg"


def test_day_sort_moves_video_with_photo(tmp_path):
    photo, video = str(tmp_path / "IMG_1.HEIC"), str(tmp_path / "IMG_1.MOV")
    for p in (photo, video):
        open(p, "w").close()
    items = [(photo, datetime(2023, 7, 15, 23, 59)), (video, datetime(2023, 7, 16, 0, 1))]
    plan = dict(m.plan_day_sort(items, str(tmp_path), partners={photo: [video]})[0])
    assert plan[video] == os.path.join(str(tmp_path), "2023-07-15", "IMG_1.MOV")


def test_gui_rename_and_undo_pair(app, tmp_path, monkeypatch):
    folder = tmp_path / "media"
    folder.mkdir()
    make_jpg(str(folder / "IMG_7.JPG"), "2023:07:15 10:00:00")
    with open(folder / "IMG_7.MOV", "wb") as f:
        f.write(b"\x00\x00\x00\x08free")
    monkeypatch.setattr(m.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(m.messagebox, "askyesno", lambda *a, **k: True)
    app._open_folder(str(folder))
    pump(app, 1)
    assert app.grid_view.live == {str(folder / "IMG_7.JPG")}
    app.grid_view.selected = {str(folder / "IMG_7.JPG")}  # csak a fotó kijelölve
    monkeypatch.setattr(app, "get_suffix", lambda: ("Balaton", False))
    app.after(800, lambda: [w for w in app.winfo_children() if isinstance(w, m.tk.Toplevel)][-1]
              .event_generate("<Return>"))
    app.rename_selected()
    pump(app, 1.5)
    assert sorted(os.listdir(folder)) == ["2023-07-15_10-00-00_Balaton.JPG", "2023-07-15_10-00-00_Balaton.MOV"]
    app.undo_last()
    pump(app, 1)
    assert sorted(os.listdir(folder)) == ["IMG_7.JPG", "IMG_7.MOV"]
