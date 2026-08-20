import errno
from pathlib import Path

import pytest

from backend.library.mover import MoveError, atomic_move, copy_cover_if_needed


def test_atomic_move_same_filesystem(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("hello")
    dest = tmp_path / "nested" / "dest.txt"

    atomic_move(str(src), str(dest))

    assert dest.exists()
    assert dest.read_text() == "hello"
    assert not src.exists()


def test_atomic_move_creates_parent_dirs(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("data")
    dest = tmp_path / "a" / "b" / "c" / "dest.txt"

    atomic_move(str(src), str(dest))

    assert dest.exists()


def test_atomic_move_falls_back_on_cross_device(tmp_path, monkeypatch):
    src = tmp_path / "src.txt"
    src.write_text("cross-device content")
    dest = tmp_path / "dest.txt"

    import os
    real_replace = os.replace
    calls = {"count": 0}

    def fake_replace(a, b):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(a, b)

    monkeypatch.setattr(os, "replace", fake_replace)
    atomic_move(str(src), str(dest))

    assert dest.exists()
    assert dest.read_text() == "cross-device content"
    assert not src.exists()


def test_atomic_move_never_leaves_partial_dest_on_real_failure(tmp_path):
    with pytest.raises(MoveError):
        atomic_move(str(tmp_path / "does_not_exist.txt"), str(tmp_path / "dest.txt"))
    assert not (tmp_path / "dest.txt").exists()


def test_copy_cover_if_needed(tmp_path):
    src = tmp_path / "cover.jpg"
    src.write_bytes(b"\xff\xd8\xff\xe0fakejpegdata")
    dest = tmp_path / "album" / "cover.jpg"

    copy_cover_if_needed(str(src), str(dest))

    assert dest.exists()
    assert src.exists()  # la sorgente NON viene rimossa (e' una copy, non un move)
