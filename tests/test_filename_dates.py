"""Dátum a fájlnévből (WhatsApp, Messenger, képernyőképek, Android)."""
from datetime import datetime, timezone

import pytest
from PIL import Image

import Keprename5video as m


@pytest.mark.parametrize("name, expected", [
    ("IMG-20230812-WA0001.jpg", datetime(2023, 8, 12)),
    ("VID-20230812-WA0003.mp4", datetime(2023, 8, 12)),
    ("IMG_20230812_143015.jpg", datetime(2023, 8, 12, 14, 30, 15)),
    ("VID_20230812_143015.mp4", datetime(2023, 8, 12, 14, 30, 15)),
    ("20230812_143015.jpg", datetime(2023, 8, 12, 14, 30, 15)),
    ("Screenshot_20230812-143015.png", datetime(2023, 8, 12, 14, 30, 15)),
    ("Screenshot_2023-08-12-14-30-15-123_com.whatsapp.jpg", datetime(2023, 8, 12, 14, 30, 15)),
    ("Screenshot 2023-08-12 at 14.30.15.png", datetime(2023, 8, 12, 14, 30, 15)),
    ("Képernyőkép 2023-08-12 143015.png", datetime(2023, 8, 12, 14, 30, 15)),
    ("signal-2023-08-12-143015.jpg", datetime(2023, 8, 12, 14, 30, 15)),
    ("2023-07-15_10-20-30_Nyaralás.jpg", datetime(2023, 7, 15, 10, 20, 30)),  # a program saját nevei
    ("2023-07-15_Balaton_3.jpg", datetime(2023, 7, 15)),
])
def test_filename_dates(name, expected):
    assert m.get_filename_datetime(name) == expected


def test_pixel_names_are_utc():
    expected = datetime(2023, 8, 12, 14, 30, 15, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert m.get_filename_datetime("PXL_20230812_143015123.jpg") == expected


def test_messenger_epoch_ms():
    assert m.get_filename_datetime("FB_IMG_1691843415123.jpg") == datetime.fromtimestamp(1691843415.123)


@pytest.mark.parametrize("name", [
    "IMG_1234.jpg", "received_1234567890123456.jpeg", "DSC01234.JPG", "IMG-20231345-WA0001.jpg",
    "photo_99999999_999999.jpg", "2099-01-01_kesobb.jpg", "1234567890.jpg",
])
def test_no_date_in_name(name):
    assert m.get_filename_datetime(name, now=datetime(2026, 1, 1)) is None


def test_exif_wins_then_filename_then_file(tmp_path):
    with_exif = tmp_path / "IMG-20230812-WA0001.jpg"
    ex = Image.Exif()
    ex.get_ifd(0x8769)[0x9003] = "2022:01:02 03:04:05"
    Image.new("RGB", (10, 10)).save(str(with_exif), exif=ex.tobytes())
    assert m.get_media_datetime(str(with_exif)) == (datetime(2022, 1, 2, 3, 4, 5), "exif")
    without = tmp_path / "IMG-20230812-WA0002.jpg"
    Image.new("RGB", (10, 10)).save(str(without))
    assert m.get_media_datetime(str(without)) == (datetime(2023, 8, 12), "filename")
    plain = tmp_path / "kep.jpg"
    Image.new("RGB", (10, 10)).save(str(plain))
    assert m.get_media_datetime(str(plain))[1] == "file"
