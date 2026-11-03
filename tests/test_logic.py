"""A nem grafikus részek tesztjei: python -m pytest"""
import os
import shutil
from datetime import datetime

import pytest
from PIL import Image

import Keprename5video as m
from conftest import make_jpg, make_png, make_video, needs_ffmpeg

DT0 = datetime(2024, 5, 1, 14, 30, 0)


@pytest.fixture
def media_dir(tmp_path):
    """a.jpg és b.JPG azonos időponttal, alma/c.jpg álló tájolással, EXIF nélküli JPEG, PNG EXIF-fel."""
    d = tmp_path
    sub = d / "alma"
    sub.mkdir()
    make_jpg(str(d / "a.jpg"), "2023:07:15 10:20:30")
    make_jpg(str(d / "b.JPG"), "2023:07:15 10:20:30")
    make_jpg(str(sub / "c.jpg"), "2023:07:14 08:00:00", orient=6)
    Image.new("RGB", (50, 50)).save(str(d / "noexif.jpg"))
    make_png(str(d / "p.png"), "2022:01:02 03:04:05")
    return d


def dated(files):
    return [(f, m.get_media_datetime(f)[0]) for f in files]


# --- beolvasás -----------------------------------------------------------
def test_scan_recursive_and_flat(media_dir):
    assert len(m.scan_media(str(media_dir), True)) == 5
    assert len(m.scan_media(str(media_dir), False)) == 4


def test_macos_sidecar_files_skipped(media_dir):
    (media_dir / "._a.jpg").write_bytes(b"\x00\x05\x16\x07")
    assert not m.is_media(str(media_dir / "._a.jpg"))
    assert m.is_media("IMG_1234.JPG")
    assert len(m.scan_media(str(media_dir), False)) == 4


# --- dátumok -------------------------------------------------------------
def test_jpeg_exif_date(media_dir):
    assert m.get_media_datetime(str(media_dir / "a.jpg")) == (datetime(2023, 7, 15, 10, 20, 30), "exif")


def test_png_exif_date(media_dir):
    dt, src = m.get_media_datetime(str(media_dir / "p.png"))
    assert src == "exif" and dt.year == 2022


def test_file_date_fallback(media_dir):
    assert m.get_media_datetime(str(media_dir / "noexif.jpg"))[1] == "file"


def test_iso_offset_keeps_local_wall_clock():
    # iPhone: a felvétel helyi ideje + eltolás; a fotók EXIF-je is helyi időt tárol
    assert m.parse_iso_datetime("2023-07-16T14:00:00+0200") == datetime(2023, 7, 16, 14, 0, 0)
    assert m.parse_iso_datetime("2023-07-16T22:30:00-0400") == datetime(2023, 7, 16, 22, 30, 0)


def test_iso_utc_converted_to_local():
    dt = m.parse_iso_datetime("2023-07-16T12:00:00Z")
    expected = datetime(2023, 7, 16, 12, 0, 0).replace(tzinfo=m.timezone.utc).astimezone().replace(tzinfo=None)
    assert dt == expected


def test_empty_quicktime_date_rejected():
    assert m.parse_iso_datetime("1904-01-01T00:00:00Z") is None


@needs_ffmpeg
def test_video_date_and_short_video_thumbnail(tmp_path):
    short = make_video(str(tmp_path / "short.mp4"), 2, "2023-07-16T12:00:00.000000Z")
    dt, src = m.get_media_datetime(short)
    assert src == "video" and dt == m.parse_iso_datetime("2023-07-16T12:00:00Z")
    im = m.ThumbnailGenerator.generate(short)
    assert im.getextrema() != ((128, 128), (128, 128), (128, 128))  # nem a szürke tartalék


def test_thumbnail_respects_exif_orientation(media_dir):
    im = m.ThumbnailGenerator.generate(str(media_dir / "alma" / "c.jpg"))
    assert im.size == (75, 150)


# --- névsablon -----------------------------------------------------------
@pytest.mark.parametrize("pattern, counter, seq, suffix, expected", [
    (m.DEFAULT_PATTERN, 0, 1, "Balaton", "2024-05-01_14-30-00_Balaton.jpg"),
    (m.DEFAULT_PATTERN, 2, 1, "Balaton", "2024-05-01_14-30-00_Balaton_2.jpg"),
    ("{suffix}_{seq}", 0, 7, "Bala/ton:", "Bala-ton-_007.jpg"),
    ("{day}_{suffix}", 3, 1, "B", "2024-05-01_B_3.jpg"),
])
def test_render_name(pattern, counter, seq, suffix, expected):
    assert m.render_name(pattern, DT0, suffix, counter, seq, "x", ".jpg") == expected


@pytest.mark.parametrize("pattern", [
    "{datum}_{suffix}", "{date}/{suffix}", "{date}_{suffix", "{seq:05d}_{suffix}", "{date!r}_{suffix}", "",
])
def test_invalid_patterns(pattern):
    assert m.validate_pattern(pattern) is not None


def test_valid_pattern():
    assert m.validate_pattern("{day}_{time}_{suffix}_{counter}") is None


# --- átnevezés, mozgatás, visszavonás -------------------------------------
def test_rename_in_place_then_idempotent(media_dir):
    files = m.scan_media(str(media_dir), True)
    plan = m.plan_renames(dated(files), "Nyaralás", m.DEFAULT_PATTERN)
    names = [os.path.basename(n) for _, n in plan]
    assert len({m._key(n) for _, n in plan}) == len(plan)
    assert {"2023-07-15_10-20-30_Nyaralás_1.JPG", "2023-07-15_10-20-30_Nyaralás_1.jpg"} & set(names)
    sub_file = str(media_dir / "alma" / "c.jpg")
    assert os.path.dirname(dict(plan)[sub_file]) == os.path.dirname(sub_file)
    done, unchanged, errors = m.execute_plan(plan)
    assert len(done) == 5 and not errors
    # Második futás: a már jó nevek nem kapnak _1-et
    plan2 = m.plan_renames(dated(m.scan_media(str(media_dir), True)), "Nyaralás", m.DEFAULT_PATTERN)
    assert m.execute_plan(plan2)[1] == 5


def test_move_and_undo(media_dir):
    files = m.scan_media(str(media_dir), True)
    target = media_dir / "2023-07-14_Nyaralás"
    target.mkdir()
    done, _, errors = m.execute_plan(m.plan_renames(dated(files), "Nyaralás", m.DEFAULT_PATTERN, str(target)))
    assert len(os.listdir(target)) == 5 and not errors
    back, _, errors = m.execute_plan([(n, o) for o, n in reversed(done)])
    assert len(back) == 5 and not os.listdir(target) and not errors
    assert sorted(m.scan_media(str(media_dir), True)) == sorted(files)


def test_existing_file_never_overwritten(media_dir):
    target = media_dir / "cel"
    target.mkdir()
    (target / "2023-07-15_10-20-30_X.jpg").write_text("ne írd felül")
    src = str(media_dir / "a.jpg")
    plan = m.plan_renames([(src, datetime(2023, 7, 15, 10, 20, 30))], "X", m.DEFAULT_PATTERN, str(target))
    assert plan[0][1].endswith("_X_1.jpg")
    m.execute_plan(plan)
    assert (target / "2023-07-15_10-20-30_X.jpg").read_text() == "ne írd felül"


# --- beállítások és megjelenés --------------------------------------------
def test_settings_roundtrip(tmp_path):
    ini = str(tmp_path / "cfg" / "settings.ini")
    s = m.SettingsManager(ini)
    s.recent_suffixes = ["Balaton", "Esküvő"]
    s.save_settings()
    s2 = m.SettingsManager(ini)
    assert s2.recent_suffixes == ["Balaton", "Esküvő"]
    assert s2.appearance == "system"
    s2.appearance = "flat-dark"
    s2.save_settings()
    assert m.SettingsManager(ini).appearance == "flat-dark"


def test_settings_with_bom_or_garbage(tmp_path):
    ini = tmp_path / "settings.ini"
    ini.write_bytes("\ufeff[UI]\ntheme = nord\n".encode("utf-8"))
    assert m.SettingsManager(str(ini)).appearance == "nord"
    ini.write_text("ez nem ini fájl", encoding="utf-8")
    assert m.SettingsManager(str(ini)).appearance == "system"


@pytest.mark.parametrize("value, sv, expected", [
    ("light", True, "system"),
    ("Sun-Valley-Dark", True, "sun-valley-dark"),
    ("sun-valley-dark", False, "system"),
    ("rózsaszín", True, "system"),
])
def test_normalize_appearance(value, sv, expected):
    assert m.normalize_appearance(value, sv_available=sv) == expected


def test_palettes_and_texts_complete():
    keys = set(m.PALETTES["flat-light"])
    assert all(set(p) == keys for p in m.PALETTES.values()) and set(m.SYSTEM_COLORS) <= keys
    assert all(m.TEXTS[lang].get("appearance_" + a) for lang in m.TEXTS for a in m.APPEARANCES)
    assert set(m.TEXTS["hu"]) == set(m.TEXTS["en"])


# --- rendezés napok szerint -----------------------------------------------
@pytest.fixture
def day_dir(tmp_path):
    d = tmp_path
    sub = d / "regi_mappa"
    sub.mkdir()
    make_jpg(str(d / "a.jpg"), "2023:07:15 10:20:30")
    make_jpg(str(sub / "a.jpg"), "2023:07:15 11:00:00")  # azonos név másik mappából
    make_jpg(str(sub / "c.jpg"), "2023:07:14 08:00:00")
    make_png(str(d / "p.png"), "2022:01:02 03:04:05")
    Image.new("RGB", (50, 50)).save(str(d / "noexif.jpg"))
    (d / "2023-07-14").mkdir()
    make_jpg(str(d / "2023-07-14" / "kesz.jpg"), "2023:07:14 09:00:00")  # már a helyén van
    return d


def test_day_sort_plan_execute_undo(day_dir):
    d = str(day_dir)
    files = m.scan_media(d, True)
    items = dated(files)
    blocker = os.path.join(d, "2023-07-15", "a.jpg")  # a beolvasás után kerül oda
    os.makedirs(os.path.dirname(blocker))
    with open(blocker, "w") as f:
        f.write("ne írd felül")

    plan, in_place = m.plan_day_sort(items, d)
    new = dict(plan)
    assert in_place == 1
    assert len(plan) == len(files) - 1
    assert os.path.dirname(new[os.path.join(d, "regi_mappa", "c.jpg")]) == os.path.join(d, "2023-07-14")
    assert new[os.path.join(d, "p.png")].endswith(os.path.join("2022-01-02", "p.png"))
    assert os.path.join(d, "noexif.jpg") in new
    names = sorted(os.path.basename(new[p]) for p in (os.path.join(d, "a.jpg"), os.path.join(d, "regi_mappa", "a.jpg")))
    assert names == ["a_1.jpg", "a_2.jpg"]

    done, errors, created = m.execute_day_sort(plan)
    assert len(done) == len(plan) and not errors
    assert open(blocker).read() == "ne írd felül"
    assert os.path.join(d, "2023-07-15") not in created and os.path.join(d, "2022-01-02") in created
    again, _ = m.plan_day_sort(dated(f for f in m.scan_media(d, True) if f != blocker), d)
    assert again == []

    back, _, errors = m.execute_plan([(n, o) for o, n in reversed(done)])
    m.remove_empty_folders(created)
    assert len(back) == len(done) and not errors
    assert all(not os.path.exists(c) for c in created) and os.path.isdir(os.path.join(d, "2023-07-15"))
    assert sorted(f for f in m.scan_media(d, True) if f != blocker) == sorted(files)


@needs_ffmpeg
def test_day_sort_video_uses_local_day(tmp_path):
    late = make_video(str(tmp_path / "late.mp4"), 1, "2023-07-15T23:30:00Z")
    plan, _ = m.plan_day_sort(dated([late]), str(tmp_path))
    day = m.parse_iso_datetime("2023-07-15T23:30:00Z").strftime("%Y-%m-%d")
    assert os.path.dirname(plan[0][1]) == os.path.join(str(tmp_path), day)
