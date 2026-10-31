"""Időeltolás és az átnevezés előnézete."""
import os
import tkinter as tk
from datetime import datetime, timedelta

import pytest

import Keprename5video as m
from conftest import make_jpg, pump


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


def _find_toplevel(app):
    tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    return tops[-1] if tops else None


def _drive_preview(app, shift_text):
    """Megvárja az előnézet ablakot, beírja az eltolást, és Enterrel elfogadja."""
    def step():
        win = _find_toplevel(app)
        if win is None:
            app.after(50, step)
            return
        entry = next(w for w in m.ImageRenamerGUI._walk(win) if isinstance(w, tk.ttk.Entry))
        entry.insert(0, shift_text)
        app.after(500, lambda: win.event_generate("<Return>"))  # az előnézet 300 ms után frissül

    app.after(50, step)


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
    _drive_preview(app, "+1")
    app.rename_selected()
    pump(app, 1.5)
    target = folder / "2023-07-15_Nyaralás"
    # +1 óra: a 23:30-as kép átcsúszik a következő napra, a célmappa a legkorábbi napé
    assert sorted(os.listdir(target)) == ["2023-07-15_11-00-00_Nyaralás.jpg", "2023-07-16_00-30-00_Nyaralás.jpg"]
    assert len(app.last_rename) == 2
