from pathlib import Path

import pytest

from backend.config import settings
from backend.cover.cover_manager import CoverError, normalize_to_jpeg, should_write_cover


def test_normalize_to_jpeg_creates_valid_file(tmp_path, sample_cover_bytes):
    dest = tmp_path / "cover.jpg"
    result_bytes = normalize_to_jpeg(sample_cover_bytes, str(dest))

    assert dest.exists()
    assert dest.read_bytes().startswith(b"\xff\xd8")  # magic bytes JPEG
    assert result_bytes == dest.read_bytes()


def test_normalize_to_jpeg_rejects_tiny_image(tmp_path):
    from PIL import Image
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (50, 50)).save(tiny)

    with pytest.raises(CoverError):
        normalize_to_jpeg(str(tiny), str(tmp_path / "out.jpg"))


def test_normalize_to_jpeg_rejects_invalid_file(tmp_path):
    bogus = tmp_path / "not_an_image.webp"
    bogus.write_bytes(b"this is not image data")

    with pytest.raises(CoverError):
        normalize_to_jpeg(str(bogus), str(tmp_path / "out.jpg"))


def test_should_write_cover_when_missing(tmp_path):
    target = tmp_path / "cover.jpg"
    assert should_write_cover(str(target)) is True


def test_should_write_cover_preserves_existing_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cover_policy", "preserve")
    target = tmp_path / "cover.jpg"
    target.write_bytes(b"existing")
    assert should_write_cover(str(target)) is False


def test_should_write_cover_overwrite_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cover_policy", "overwrite")
    target = tmp_path / "cover.jpg"
    target.write_bytes(b"existing")
    assert should_write_cover(str(target)) is True
