import pytest

from backend.library.validator import ValidationError, validate_audio_file, validate_cover_file


@pytest.mark.asyncio
async def test_validate_audio_file_accepts_valid_m4a(sample_audio_file):
    probe = await validate_audio_file(sample_audio_file, "m4a")
    assert "streams" in probe


@pytest.mark.asyncio
async def test_validate_audio_file_rejects_missing_file(tmp_path):
    with pytest.raises(ValidationError):
        await validate_audio_file(str(tmp_path / "nope.m4a"), "m4a")


@pytest.mark.asyncio
async def test_validate_audio_file_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.m4a"
    empty.write_bytes(b"")
    with pytest.raises(ValidationError):
        await validate_audio_file(str(empty), "m4a")


@pytest.mark.asyncio
async def test_validate_audio_file_rejects_wrong_codec(sample_audio_file):
    with pytest.raises(ValidationError):
        await validate_audio_file(sample_audio_file, "flac")


def test_validate_cover_file_missing(tmp_path):
    with pytest.raises(ValidationError):
        validate_cover_file(str(tmp_path / "missing.jpg"))


def test_validate_cover_file_valid(tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 100)
    validate_cover_file(str(cover))  # non deve sollevare
