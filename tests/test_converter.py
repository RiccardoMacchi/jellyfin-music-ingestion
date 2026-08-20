import pytest

from backend.audio.converter import ConversionError, convert_audio


@pytest.mark.asyncio
async def test_convert_m4a_source_to_m4a_is_remux(tmp_path, sample_audio_file):
    dest = tmp_path / "out.m4a"
    result = await convert_audio(sample_audio_file, str(dest), "m4a")
    assert result == str(dest)
    assert dest.exists()
    assert dest.stat().st_size > 0


@pytest.mark.asyncio
async def test_convert_wav_source_to_mp3_encodes(tmp_path, sample_wav_file):
    dest = tmp_path / "out.mp3"
    await convert_audio(sample_wav_file, str(dest), "mp3")
    assert dest.exists()
    assert dest.stat().st_size > 0


@pytest.mark.asyncio
async def test_convert_wav_source_to_flac(tmp_path, sample_wav_file):
    dest = tmp_path / "out.flac"
    await convert_audio(sample_wav_file, str(dest), "flac")
    assert dest.exists()


@pytest.mark.asyncio
async def test_convert_unsupported_format_raises(tmp_path, sample_wav_file):
    with pytest.raises(ConversionError):
        await convert_audio(sample_wav_file, str(tmp_path / "out.ogg"), "ogg")


@pytest.mark.asyncio
async def test_convert_missing_source_raises(tmp_path):
    with pytest.raises(ConversionError):
        await convert_audio(str(tmp_path / "missing.wav"), str(tmp_path / "out.m4a"), "m4a")
