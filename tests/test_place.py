"""Helyszín a GPS-koordinátából (offline GeoNames adatbázis)."""
import os
import subprocess
from datetime import datetime
from fractions import Fraction

import pytest
from PIL import Image

import Keprename5video as m
from conftest import needs_ffmpeg


def _jpg_with_gps(path, lat, lon):
    def dms(x):
        x = abs(x)
        d = int(x)
        mins = int((x - d) * 60)
        secs = round(((x - d) * 60 - mins) * 60, 2)
        return (Fraction(d), Fraction(mins), Fraction(secs).limit_denominator(100))
    ex = Image.Exif()
    gps = ex.get_ifd(0x8825)
    gps[1], gps[2] = ("N" if lat >= 0 else "S"), dms(lat)
    gps[3], gps[4] = ("E" if lon >= 0 else "W"), dms(lon)
    Image.new("RGB", (10, 10)).save(path, exif=ex.tobytes())
    return path


@pytest.mark.parametrize("lat, lon, expected", [
    (46.9041, 18.0580, "Siófok"),
    (46.9137, 17.8892, "Tihany"),
    (47.4979, 19.0402, None),        # Budapest belváros: valamelyik budapesti név
    (40.7128, -74.0060, None),        # New York: a nyugati hosszúság is működik
    (45.0, -30.0, ""),               # Atlanti-óceán: nincs 25 km-en belül település
])
def test_nearest_place(lat, lon, expected):
    name = m._place_index.nearest(lat, lon)
    if expected is None:
        assert name
    else:
        assert name == expected


def test_gps_from_jpeg_and_place(tmp_path):
    path = _jpg_with_gps(str(tmp_path / "a.jpg"), 46.9041, 18.0580)
    lat, lon = m.get_gps(path)
    assert abs(lat - 46.9041) < 1e-3 and abs(lon - 18.0580) < 1e-3
    assert m.get_place(path) == "Siófok"
    west = _jpg_with_gps(str(tmp_path / "b.jpg"), -33.8688, -70.6)  # déli szélesség, nyugati hosszúság
    lat, lon = m.get_gps(west)
    assert lat < 0 and lon < 0


def test_no_gps_no_place(tmp_path):
    path = str(tmp_path / "a.jpg")
    Image.new("RGB", (10, 10)).save(path)
    assert m.get_gps(path) is None and m.get_place(path) == ""


@needs_ffmpeg
def test_iphone_video_location(tmp_path):
    path = str(tmp_path / "v.mov")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
                    "-pix_fmt", "yuv420p", "-movflags", "use_metadata_tags",
                    "-metadata", "com.apple.quicktime.location.ISO6709=+46.9137+017.8892+105.000/", path], check=True)
    assert m.get_place(path) == "Tihany"


@pytest.mark.parametrize("pattern, place, expected", [
    ("{date}_{suffix}_{place}_{counter}", "Siófok", "2024-07-12_14-30-00_Balaton_Siófok.jpg"),
    ("{date}_{suffix}_{place}_{counter}", "", "2024-07-12_14-30-00_Balaton.jpg"),
    ("{place}_{day}", "", "2024-07-12.jpg"),
    ("{day}_{place}", "São Paulo", "2024-07-12_São Paulo.jpg"),
])
def test_render_place(pattern, place, expected):
    assert m.render_name(pattern, datetime(2024, 7, 12, 14, 30), "Balaton", place=place, ext=".jpg") == expected


def test_pattern_with_place():
    assert m.pattern_with_place(m.DEFAULT_PATTERN) == "{date}_{suffix}_{place}_{counter}"
    assert m.pattern_with_place("{day}_{place}") == "{day}_{place}"
    assert m.pattern_with_place("{day}_{counter}") == "{day}_{place}_{counter}"
    assert m.validate_pattern("{day}_{place}") is None


def test_place_setting_off_by_default(tmp_path):
    s = m.SettingsManager(str(tmp_path / "s.ini"))
    assert not s.place_enabled and s.effective_pattern() == m.DEFAULT_PATTERN
    s.config["Naming"]["place"] = "yes"
    assert "{place}" in s.effective_pattern()


def test_rename_plan_uses_places(tmp_path):
    a, b = str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")
    for p in (a, b):
        open(p, "w").close()
    dt = datetime(2024, 7, 12, 14, 30)
    plan = dict(m.plan_renames([(a, dt), (b, dt)], "X", m.pattern_with_place(m.DEFAULT_PATTERN),
                               places={a: "Siófok", b: ""}))
    assert os.path.basename(plan[a]) == "2024-07-12_14-30-00_X_Siófok.jpg"
    assert os.path.basename(plan[b]) == "2024-07-12_14-30-00_X.jpg"
