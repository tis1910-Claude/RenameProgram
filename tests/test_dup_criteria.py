"""Duplikátumkeresés választható szempontokkal."""
import os
import shutil

import pytest
from PIL import Image

import Keprename5video as m
from conftest import pump


def jpg(path, dt=None, subsec=None, uid=None, make=None, model=None, serial=None, color="red", size=(60, 40),
        quality=90):
    img = Image.new("RGB", size, color)
    ex = Image.Exif()
    ifd = ex.get_ifd(0x8769)
    if dt:
        ifd[0x9003] = dt
    if subsec:
        ifd[0x9291] = subsec
    if uid:
        ifd[0xA420] = uid
    if serial:
        ifd[0xA431] = serial
    if make:
        ex[0x010F] = make
    if model:
        ex[0x0110] = model
    img.save(path, exif=ex.tobytes(), quality=quality)
    return str(path)


def test_read_metadata(tmp_path):
    p = jpg(tmp_path / "a.jpg", "2023:07:15 10:20:30", "45", "ABC123", "Canon", "EOS R6", "0123")
    meta = m.read_dup_metadata(p)
    assert meta == {"datetime": "2023:07:15 10:20:30.450", "unique_id": "ABC123", "camera": "Canon EOS R6 0123"}
    q = jpg(tmp_path / "b.jpg", "2023:07:15 10:20:30", uid="0000000000")
    assert m.read_dup_metadata(q) == {"datetime": "2023:07:15 10:20:30", "unique_id": None, "camera": None}
    (tmp_path / "c.txt").write_text("x")
    assert m.read_dup_metadata(str(tmp_path / "c.txt")) == {"datetime": None, "unique_id": None, "camera": None}


def test_content_only_matches_old_behaviour(tmp_path):
    a = jpg(tmp_path / "a.jpg", "2023:07:15 10:20:30")
    os.mkdir(tmp_path / "sub")
    b = str(tmp_path / "sub" / "b.jpg")
    shutil.copy(a, b)
    c = jpg(tmp_path / "c.jpg", "2023:07:15 10:20:30", color="blue")
    groups, missing = m.find_duplicates_by([b, c, a], ["content"])
    assert groups == [[a, b]] and missing == []
    assert groups == m.find_duplicates([b, c, a])


def test_datetime_ms_matches_recompressed_copy(tmp_path):
    # ugyanaz a felvétel, más minőséggel újramentve: a tartalom eltér, az EXIF idő azonos
    big = jpg(tmp_path / "a.jpg", "2023:07:15 10:20:30", "450", size=(400, 300), quality=95)
    small = jpg(tmp_path / "a_whatsapp.jpg", "2023:07:15 10:20:30", "450", size=(200, 150), quality=50)
    other_ms = jpg(tmp_path / "burst.jpg", "2023:07:15 10:20:30", "460")  # sorozatkép: más ezredmásodperc
    no_exif = jpg(tmp_path / "noexif.jpg")
    groups, missing = m.find_duplicates_by([small, other_ms, big, no_exif], ["datetime"])
    assert groups == [[big, small]]  # a nagyobb fájl a megtartandó
    assert missing == [no_exif]
    # a tartalommal együtt (ÉS) már nem egyeznek
    assert m.find_duplicates_by([small, big], ["datetime", "content"])[0] == []


def test_criteria_are_combined_with_and(tmp_path):
    a = jpg(tmp_path / "a.jpg", "2023:07:15 10:20:30", uid="U1", make="Canon", model="R6")
    b = jpg(tmp_path / "b.jpg", "2023:07:15 10:20:30", uid="U1", make="Canon", model="R6", color="blue")
    c = jpg(tmp_path / "c.jpg", "2023:07:15 10:20:30", uid="U2", make="Canon", model="R6")
    d = jpg(tmp_path / "d.jpg", "2023:07:15 10:20:30", make="Canon", model="R6")  # nincs ImageUniqueID
    groups, missing = m.find_duplicates_by([a, b, c, d], ["datetime", "camera"])
    assert len(groups) == 1 and sorted(groups[0]) == sorted([a, b, c, d])
    groups, missing = m.find_duplicates_by([a, b, c, d], ["datetime", "camera", "unique_id"])
    assert len(groups) == 1 and sorted(groups[0]) == sorted([a, b]) and missing == [d]
    with pytest.raises(ValueError):
        m.find_duplicates_by([a, b], [])


def test_settings_remember_criteria(tmp_path):
    s = m.SettingsManager(str(tmp_path / "s.ini"))
    assert s.dup_criteria == ["content"]
    s.dup_criteria = ["unique_id", "datetime", "bogus"]
    s.save_settings()
    assert m.SettingsManager(str(tmp_path / "s.ini")).dup_criteria == ["datetime", "unique_id"]
    s.config["UI"]["dup_criteria"] = ""
    assert s.dup_criteria == ["content"]


def test_dup_options_in_guide(app, tmp_path, monkeypatch):
    pump(app, 0.2)
    opts = app.feature_options["duplicates"]
    assert not opts.winfo_ismapped()
    app.select_feature("duplicates")
    pump(app, 0.2)
    assert opts.winfo_ismapped()
    assert opts.winfo_y() < app.guide_run.winfo_y()  # a pipák az Indítás gomb fölött
    assert [c for c, v in app.dup_vars.items() if v.get()] == ["content"]
    app.dup_vars["datetime"].set(True)
    app._on_dup_criteria()
    assert app.settings.dup_criteria == ["content", "datetime"]
    for v in app.dup_vars.values():
        v.set(False)
    app._on_dup_criteria()
    assert app.settings.dup_criteria == ["content", "datetime"]  # üreset nem ment
    calls = []
    monkeypatch.setattr(m.messagebox, "showinfo", lambda *a, **k: calls.append(a))
    app.find_duplicates_ui()
    assert calls and calls[-1][1] == app.t("dup_crit_none")
    app.select_feature("rename")
    pump(app, 0.2)
    assert not opts.winfo_ismapped()


def test_dup_search_runs_with_metadata(app, tmp_path):
    folder = tmp_path / "media"
    folder.mkdir()
    jpg(folder / "a.jpg", "2023:07:15 10:20:30", "450", size=(300, 200), quality=95)
    jpg(folder / "a_small.jpg", "2023:07:15 10:20:30", "450", size=(100, 80), quality=40)
    jpg(folder / "x.jpg")
    app._open_folder(str(folder))
    pump(app, 0, until=lambda: len(app.files) == 3)
    shown = []
    app._show_duplicates = lambda groups, missing, criteria: shown.append((groups, missing, criteria))
    app.select_feature("duplicates")
    app.dup_vars["content"].set(False)
    app.dup_vars["datetime"].set(True)
    app.guide_run.invoke()
    pump(app, 0, until=lambda: shown, limit=10)
    groups, missing, criteria = shown[0]
    assert criteria == ["datetime"]
    assert [[os.path.basename(p) for p in g] for g in groups] == [["a.jpg", "a_small.jpg"]]
    assert [os.path.basename(p) for p in missing] == ["x.jpg"]


def test_start_button_visible_in_small_window(app):
    app.geometry("800x600")
    app.select_feature("duplicates")
    pump(app, 0.5)
    top = app.winfo_rooty() + app.winfo_height()
    assert app.guide_run.winfo_ismapped()
    assert app.guide_run.winfo_rooty() + app.guide_run.winfo_height() <= top
    assert app._panel_scroll.winfo_ismapped()  # a többi görgethető
    app.geometry("1100x900")
    app.select_feature(None)
    pump(app, 0.5)
    assert not app._panel_scroll.winfo_ismapped()
