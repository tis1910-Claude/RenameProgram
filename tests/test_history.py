"""Mentett, többlépéses visszavonás és duplikátumkeresés."""
import os
import tkinter as tk

import pytest

import Keprename5video as m
from conftest import make_jpg, pump


def test_history_persists_and_is_lifo(tmp_path):
    path = str(tmp_path / "cfg" / "history.json")
    h = m.UndoHistory(path)
    h.push("rename", [("a", "b")])
    h.push("daysort", [("c", "d"), ("e", "f")], ["/x/2024-05-01"])
    h.push("rename", [])  # üres lépés nem kerül be
    h2 = m.UndoHistory(path)
    assert len(h2) == 2 and h2.last()["kind"] == "daysort" and h2.last()["created"] == ["/x/2024-05-01"]
    assert h2.pop()["moves"] == [["c", "d"], ["e", "f"]]
    assert m.UndoHistory(path).last()["moves"] == [["a", "b"]]


def test_history_keeps_last_steps_only(tmp_path):
    h = m.UndoHistory(str(tmp_path / "h.json"))
    for i in range(m.UndoHistory.MAX_STEPS + 5):
        h.push("rename", [(f"{i}", f"{i}x")])
    assert len(h) == m.UndoHistory.MAX_STEPS and h.last()["moves"] == [[f"{i}", f"{i}x"]]


def test_history_survives_corrupt_file(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{nem json")
    assert len(m.UndoHistory(str(path))) == 0


def test_find_duplicates(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    a = make_jpg(str(tmp_path / "a.jpg"), "2023:07:15 10:20:30")
    with open(a, "rb") as f:
        data = f.read()
    for p in (sub / "a_copy.jpg", sub / "b_copy.jpg"):
        p.write_bytes(data)
    (tmp_path / "same_size.jpg").write_bytes(data[:-1] + bytes([data[-1] ^ 1]))  # azonos méret, más tartalom
    big1, big2 = tmp_path / "big1.bin", tmp_path / "big2.bin"  # azonos eleje, eltérő vége
    big1.write_bytes(b"x" * 100_000 + b"1")
    big2.write_bytes(b"x" * 100_000 + b"2")
    paths = [str(p) for p in (sub / "b_copy.jpg", tmp_path / "same_size.jpg", sub / "a_copy.jpg", big1, big2)] + [a]
    groups = m.find_duplicates(paths)
    assert groups == [[a, str(sub / "a_copy.jpg"), str(sub / "b_copy.jpg")]]


def test_undo_two_steps_after_restart(app, tmp_path, monkeypatch):
    folder = tmp_path / "media"
    folder.mkdir()
    make_jpg(str(folder / "IMG_1.jpg"), "2023:07:15 10:00:00")
    monkeypatch.setattr(m.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(m.messagebox, "askyesno", lambda *a, **k: True)
    app._open_folder(str(folder))
    pump(app, 1)
    # 1. lépés: átnevezés, 2. lépés: rendezés napok szerint
    app._rename_run(m.plan_renames([(str(folder / "IMG_1.jpg"), m.datetime(2023, 7, 15, 10))], "Teszt",
                                   m.DEFAULT_PATTERN), None, 0)
    pump(app, 1)
    renamed = str(folder / "2023-07-15_10-00-00_Teszt.jpg")
    assert os.path.exists(renamed)
    plan, _ = m.plan_day_sort([(renamed, m.datetime(2023, 7, 15, 10))], str(folder))
    app._daysort_run(plan)
    pump(app, 1)
    assert os.path.exists(folder / "2023-07-15" / "2023-07-15_10-00-00_Teszt.jpg")
    assert "Rendezés napok szerint" in app.edit_menu.entrycget(0, "label")

    # Újraindítás: az új példány az előzményeket a fájlból tölti vissza
    app.on_close()
    app2 = m.ImageRenamerGUI()
    try:
        assert len(app2.history) == 2
        app2._open_folder(str(folder))
        pump(app2, 1)
        app2.undo_last()
        pump(app2, 1)
        app2.undo_last()
        pump(app2, 1)
        assert sorted(os.listdir(folder)) == ["IMG_1.jpg"]  # a létrehozott napi mappa is törölve
        assert len(app2.history) == 0 and app2.edit_menu.entrycget(0, "state") == tk.DISABLED
    finally:
        app2.on_close()
