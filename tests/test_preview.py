"""Időeltolás és az átnevezés előnézete."""
import os
import tkinter as tk
from datetime import datetime, timedelta

import pytest

import Keprename5video as m
from conftest import accept_dialog, make_jpg, pump


@pytest.mark.parametrize("text, expected", [
    ("", timedelta(0)),
    ("+1", timedelta(hours=1)),
    ("-0:30", timedelta(minutes=-30)),
    ("+1d 2:05", timedelta(days=1, hours=2, minutes=5)),
    ("-2n", timedelta(days=-2)),
    (" 3:00 ", timedelta(hours=3)),
])
def test_parse_shift(text, expected):
    assert m.parse_shift(text) == expected


@pytest.mark.parametrize("text", ["abc", "+1:60", "1:2:3", "++1"])
def test_parse_shift_invalid(text):
    with pytest.raises(ValueError):
        m.parse_shift(text)


def test_move_target_folder_uses_earliest_day():
    items = [("b", datetime(2024, 5, 3)), ("a", datetime(2024, 5, 1, 23))]
    assert m.move_target_folder("/base", items, "Bala/ton") == os.path.join("/base", "2024-05-01_Bala-ton")


def _set_shift(text):
    def prepare(win):
        entry = next(w for w in m.ImageRenamerGUI._walk(win) if isinstance(w, tk.ttk.Entry))
        entry.insert(0, text)
    return prepare


def test_rename_with_preview_and_shift(app, tmp_path, monkeypatch):
    folder = tmp_path / "media"
    folder.mkdir()
    make_jpg(str(folder / "IMG_1.jpg"), "2023:07:15 23:30:00")
    make_jpg(str(folder / "IMG_2.jpg"), "2023:07:15 10:00:00")
    app._open_folder(str(folder))
    pump(app, 1)
    app.mark_all()
    monkeypatch.setattr(app, "get_suffix", lambda: ("Nyaralás", True))
    monkeypatch.setattr(m.messagebox, "showinfo", lambda *a, **k: None)
    accept_dialog(app, _set_shift("+1"))
    app.rename_selected()
    pump(app, 1.5)
    target = folder / "2023-07-15_Nyaralás"
    # +1 óra: a 23:30-as kép átcsúszik a következő napra, a célmappa a legkorábbi napé
    assert sorted(os.listdir(target)) == ["2023-07-15_11-00-00_Nyaralás.jpg", "2023-07-16_00-30-00_Nyaralás.jpg"]
    assert len(app.history.last()["moves"]) == 2


def test_moved_files_leave_the_list_even_with_subfolders(app, tmp_path, monkeypatch):
    folder = tmp_path / "media"
    folder.mkdir()
    make_jpg(str(folder / "IMG_1.jpg"), "2023:07:15 10:00:00")
    make_jpg(str(folder / "IMG_2.jpg"), "2023:07:15 11:00:00")
    app._open_folder(str(folder))
    pump(app, 1)
    app.grid_view.select_all(True)
    app.grid_view.selected.discard(str(folder / "IMG_2.jpg"))
    monkeypatch.setattr(app, "get_suffix", lambda: ("Nyaralás", True))
    accept_dialog(app)
    app.rename_selected()
    pump(app, 1.5)
    assert (folder / "2023-07-15_Nyaralás" / "2023-07-15_10-00-00_Nyaralás.jpg").exists()
    assert [os.path.basename(p) for p in app.files] == ["IMG_2.jpg"]
    app.load_media()  # a Frissítés sem hozza vissza
    pump(app, 0.5)
    assert [os.path.basename(p) for p in app.files] == ["IMG_2.jpg"]


def test_move_uses_saved_base_folder(app, tmp_path, monkeypatch):
    folder, album = tmp_path / "media", tmp_path / "album"
    folder.mkdir()
    album.mkdir()
    make_jpg(str(folder / "IMG_1.jpg"), "2023:07:15 10:00:00")
    app.settings.move_base = str(album)
    app._open_folder(str(folder))
    pump(app, 1)
    app.mark_all()
    monkeypatch.setattr(app, "get_suffix", lambda: ("Tó", True))
    accept_dialog(app)
    app.rename_selected()
    pump(app, 1.5)
    assert os.listdir(album / "2023-07-15_Tó") == ["2023-07-15_10-00-00_Tó.jpg"]
    assert app.files == []
    assert not (folder / "2023-07-15_Tó").exists()


def test_move_base_setting_ignores_missing_folder(tmp_path):
    s = m.SettingsManager(str(tmp_path / "s.ini"))
    assert s.move_base == ""
    s.move_base = str(tmp_path)
    s.save_settings()
    assert m.SettingsManager(str(tmp_path / "s.ini")).move_base == str(tmp_path)
    s.move_base = str(tmp_path / "nincs")
    assert s.move_base == ""


def test_suffix_dialog_is_centered_and_shows_target(app, tmp_path):
    folder = tmp_path / "media"
    folder.mkdir()
    make_jpg(str(folder / "IMG_1.jpg"), "2023:07:15 10:00:00")
    app._open_folder(str(folder))
    pump(app, 1.5)
    app.mark_all()
    seen = {}

    def prepare(win):
        win.update()
        entry = next(w for w in m.ImageRenamerGUI._walk(win) if isinstance(w, tk.ttk.Entry))
        entry.insert(0, "Balaton")
        seen["text"] = [w.cget("text") for w in m.ImageRenamerGUI._walk(win) if isinstance(w, tk.Label)]
        seen["centre"] = win.winfo_rootx() + win.winfo_width() / 2
        seen["width"] = win.winfo_width()

    accept_dialog(app, prepare)
    assert app.get_suffix() == ("Balaton", False)
    assert any(t.endswith(os.path.join(str(folder), "2023-07-15_Balaton")) for t in seen["text"])
    assert seen["width"] >= 620
    assert abs(seen["centre"] - (app.winfo_rootx() + app.winfo_width() / 2)) < 30
