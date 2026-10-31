"""HEIC, RAW és MP4/MOV fejléc olvasása ffprobe nélkül."""
import os
import subprocess
from datetime import datetime

import pytest
from PIL import Image

import Keprename5video as m
from conftest import make_video, needs_ffmpeg


def _exif(dt):
    ex = Image.Exif()
    ex.get_ifd(0x8769)[0x9003] = dt
    return ex.tobytes()


@pytest.mark.skipif(not m.HAS_HEIF, reason="pillow-heif nincs telepítve")
def test_heic_listed_dated_and_thumbnailed(tmp_path):
    path = str(tmp_path / "IMG_0001.HEIC")
    Image.new("RGB", (300, 200), "blue").save(path, exif=_exif("2024:08:01 18:45:00"))
    assert m.scan_media(str(tmp_path), False) == [path]
    assert m.get_media_datetime(path) == (datetime(2024, 8, 1, 18, 45, 0), "exif")
    assert m.ThumbnailGenerator.generate(path).size == (150, 100)


def test_raw_date_from_tiff_based_raw(tmp_path):
    # A DNG TIFF-alapú; egy EXIF-es TIFF .dng néven ugyanazt az utat járja be
    path = str(tmp_path / "IMG_0002.dng")
    Image.new("RGB", (300, 200), "green").save(path, format="TIFF", exif=_exif("2021:03:04 05:06:07"))
    assert m.is_media(path) and m.is_raw(path)
    assert m.get_media_datetime(path) == (datetime(2021, 3, 4, 5, 6, 7), "exif")
    assert m.ThumbnailGenerator.generate(path).size == (150, 100)


def test_raw_without_exifread_falls_back_to_pillow(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "exifread", None)
    path = str(tmp_path / "x.dng")
    Image.new("RGB", (64, 48)).save(path, format="TIFF", exif=_exif("2021:03:04 05:06:07"))
    assert m.get_media_datetime(path) == (datetime(2021, 3, 4, 5, 6, 7), "exif")


def test_unreadable_raw_uses_file_date(tmp_path):
    path = str(tmp_path / "broken.cr2")
    with open(path, "wb") as f:
        f.write(b"not a raw file")
    assert m.get_media_datetime(path)[1] == "file"
    assert m.ThumbnailGenerator.generate(path).size == m.THUMB_SIZE  # szürke tartalék


@needs_ffmpeg
@pytest.mark.parametrize("name", ["v.mp4", "v.mov"])
def test_bmff_creation_time_and_duration(tmp_path, name):
    path = make_video(str(tmp_path / name), 3, "2023-07-16T12:00:00.000000Z")
    meta = m.read_bmff_metadata(path)
    assert meta["creation_time"] == "2023-07-16T12:00:00Z"
    assert meta["duration"] == pytest.approx(3.0, abs=0.2)


@needs_ffmpeg
def test_apple_creationdate_key(tmp_path):
    path = str(tmp_path / "iphone.mov")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
                    "-pix_fmt", "yuv420p", "-movflags", "use_metadata_tags",
                    "-metadata", "com.apple.quicktime.creationdate=2023-07-16T22:30:00-0400",
                    "-metadata", "creation_time=2023-07-17T02:30:00Z", path], check=True)
    assert m.read_bmff_metadata(path)["apple_date"] == "2023-07-16T22:30:00-0400"
    assert m.get_media_datetime(path) == (datetime(2023, 7, 16, 22, 30, 0), "video")


@needs_ffmpeg
def test_video_date_without_ffprobe(tmp_path, monkeypatch):
    path = make_video(str(tmp_path / "v.mp4"), 1, "2023-07-16T12:00:00Z")
    monkeypatch.setattr(m, "ffprobe_available", lambda: False)
    dt, src = m.get_media_datetime(path)
    assert src == "video" and dt == m.parse_iso_datetime("2023-07-16T12:00:00Z")


def test_bmff_garbage_is_safe(tmp_path):
    path = str(tmp_path / "bad.mp4")
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x10moov\x00\x00\x00\x08mvhd" + os.urandom(64))
    assert isinstance(m.read_bmff_metadata(path), dict)
    assert m.get_media_datetime(path)[1] in ("video", "file")
