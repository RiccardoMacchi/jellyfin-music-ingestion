"""
Scrittura dei metadata audio (tag) sul file gia' convertito nel formato
finale, incluso l'embed della cover art. Supporta m4a (MP4/AAC), mp3, flac:
gli unici tre formati che il progetto espone come scelta (vedi library
skill "FORMATO AUDIO" nel README per il confronto).
"""
from __future__ import annotations

from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, ID3, TCOM, TCON, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from backend.metadata.normalizer import TrackMetadata


class TaggingError(RuntimeError):
    pass


def write_tags(file_path: str, metadata: TrackMetadata, cover_bytes: bytes | None = None) -> None:
    ext = Path(file_path).suffix.lower().lstrip(".")
    if ext == "m4a":
        _write_m4a(file_path, metadata, cover_bytes)
    elif ext == "mp3":
        _write_mp3(file_path, metadata, cover_bytes)
    elif ext == "flac":
        _write_flac(file_path, metadata, cover_bytes)
    else:
        raise TaggingError(f"Formato non supportato per il tagging: {ext}")


def _write_m4a(file_path: str, m: TrackMetadata, cover_bytes: bytes | None) -> None:
    audio = MP4(file_path)
    audio["\xa9nam"] = [m.title]
    audio["\xa9ART"] = [m.artist]
    audio["aART"] = [m.album_artist]
    if m.album:
        audio["\xa9alb"] = [m.album]
    if m.year:
        audio["\xa9day"] = [str(m.year)]
    if m.genre:
        audio["\xa9gen"] = [m.genre]
    if m.composer:
        audio["\xa9wrt"] = [m.composer]
    if m.comment:
        audio["\xa9cmt"] = [m.comment]
    if m.track_number:
        audio["trkn"] = [(m.track_number, 0)]
    if m.disc_number:
        audio["disk"] = [(m.disc_number, 0)]
    if m.is_compilation:
        audio["cpil"] = True
    if cover_bytes:
        audio["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def _write_mp3(file_path: str, m: TrackMetadata, cover_bytes: bytes | None) -> None:
    try:
        tags = ID3(file_path)
    except Exception:
        tags = ID3()

    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=m.title))
    tags.delall("TPE1")
    tags.add(TPE1(encoding=3, text=m.artist))
    tags.delall("TPE2")
    tags.add(TPE2(encoding=3, text=m.album_artist))
    if m.album:
        tags.delall("TALB")
        tags.add(TALB(encoding=3, text=m.album))
    if m.year:
        tags.delall("TDRC")
        tags.add(TDRC(encoding=3, text=str(m.year)))
    if m.genre:
        tags.delall("TCON")
        tags.add(TCON(encoding=3, text=m.genre))
    if m.composer:
        tags.delall("TCOM")
        tags.add(TCOM(encoding=3, text=m.composer))
    if m.comment:
        tags.delall("COMM")
        tags.add(COMM(encoding=3, lang="eng", desc="", text=m.comment))
    if m.track_number:
        tags.delall("TRCK")
        tags.add(TRCK(encoding=3, text=str(m.track_number)))
    if m.disc_number:
        tags.delall("TPOS")
        tags.add(TPOS(encoding=3, text=str(m.disc_number)))
    if cover_bytes:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes))

    tags.save(file_path, v2_version=3)


def _write_flac(file_path: str, m: TrackMetadata, cover_bytes: bytes | None) -> None:
    audio = FLAC(file_path)
    audio["title"] = m.title
    audio["artist"] = m.artist
    audio["albumartist"] = m.album_artist
    if m.album:
        audio["album"] = m.album
    if m.year:
        audio["date"] = str(m.year)
    if m.genre:
        audio["genre"] = m.genre
    if m.composer:
        audio["composer"] = m.composer
    if m.comment:
        audio["comment"] = m.comment
    if m.track_number:
        audio["tracknumber"] = str(m.track_number)
    if m.disc_number:
        audio["discnumber"] = str(m.disc_number)

    if cover_bytes:
        audio.clear_pictures()
        pic = Picture()
        pic.data = cover_bytes
        pic.type = 3
        pic.mime = "image/jpeg"
        audio.add_picture(pic)

    audio.save()
