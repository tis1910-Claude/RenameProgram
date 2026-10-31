import os
import shutil
import subprocess
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe nincs a PATH-on")


def make_jpg(path, dt=None, orient=None, size=(400, 200), color="red"):
    """JPEG beágyazott DateTimeOriginal-lel (ÉÉÉÉ:HH:NN óó:pp:mm) és tájolással."""
    img = Image.new("RGB", size, color)
    ex = Image.Exif()
    if dt:
        ex.get_ifd(0x8769)[0x9003] = dt
    if orient:
        ex[0x0112] = orient
    img.save(path, exif=ex.tobytes())
    return path


def make_png(path, dt=None):
    ex = Image.Exif()
    if dt:
        ex.get_ifd(0x8769)[0x9003] = dt
    Image.new("RGB", (50, 50)).save(path, exif=ex.tobytes())
    return path


def make_video(path, seconds, creation_time=None):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
           f"testsrc=duration={seconds}:size=320x240:rate=10", "-pix_fmt", "yuv420p"]
    if creation_time:
        cmd += ["-metadata", f"creation_time={creation_time}"]
    subprocess.run(cmd + [path], check=True)
    return path


@pytest.fixture(autouse=True)
def _thumb_cache_in_tmp(tmp_path_factory, monkeypatch):
    """A tesztek ne a felhasználó valódi bélyegkép-gyorsítótárába írjanak."""
    import Keprename5video as m
    monkeypatch.setattr(m.ThumbnailGenerator, "cache", m.ThumbnailCache(str(tmp_path_factory.mktemp("thumbs"))))
