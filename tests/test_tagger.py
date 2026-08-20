import shutil

from mutagen.mp4 import MP4

from backend.metadata.tagger import write_tags
from backend.metadata.normalizer import TrackMetadata


def test_write_tags_m4a_roundtrip(tmp_path, sample_audio_file, sample_cover_bytes):
    working_copy = tmp_path / "track.m4a"
    shutil.copyfile(sample_audio_file, working_copy)

    meta = TrackMetadata(
        title="Test Title", artist="Test Artist", album_artist="Test Artist",
        album="Test Album", track_number=4, disc_number=1, year=2021,
        genre="Electronic", composer="Some Composer", is_single=False,
    )

    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.open(sample_cover_bytes).convert("RGB").save(buf, format="JPEG")

    write_tags(str(working_copy), meta, cover_bytes=buf.getvalue())

    audio = MP4(str(working_copy))
    assert audio["\xa9nam"][0] == "Test Title"
    assert audio["\xa9ART"][0] == "Test Artist"
    assert audio["aART"][0] == "Test Artist"
    assert audio["\xa9alb"][0] == "Test Album"
    assert audio["trkn"][0][0] == 4
    assert audio["disk"][0][0] == 1
    assert audio["\xa9day"][0] == "2021"
    assert "covr" in audio
