"""
Atomic library insert.

Il file finale viene costruito e validato interamente in DOWNLOAD_DIR (area
di lavoro temporanea); solo alla fine viene spostato in MUSIC_DIR con
`os.replace`, che su uno stesso filesystem e' atomico: o il file appare
completo, o non appare affatto. Se qualsiasi passo precedente fallisce,
MUSIC_DIR non viene mai toccata.

NB: os.replace richiede che sorgente e destinazione siano sullo stesso
filesystem. Se DOWNLOAD_DIR e MUSIC_DIR sono volumi Docker diversi, il primo
tentativo di replace fallira' con EXDEV: in quel caso si esegue una copy +
fsync + rename all'interno del filesystem di destinazione, mai un file
parzialmente scritto direttamente nel path finale.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


class MoveError(RuntimeError):
    pass


def atomic_move(source_path: str, dest_path: str) -> None:
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.replace(source_path, dest_path)
        return
    except OSError as exc:
        if getattr(exc, "errno", None) != 18:  # 18 = EXDEV, cross-device link
            raise MoveError(f"Spostamento fallito: {exc}") from exc

    # Cross-device: scrivi in un file temporaneo nella STESSA directory di
    # destinazione, poi rename (atomico sullo stesso filesystem).
    tmp_dest = dest.with_suffix(dest.suffix + ".partial")
    try:
        shutil.copyfile(source_path, tmp_dest)
        with open(tmp_dest, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp_dest, dest_path)
        os.remove(source_path)
    except OSError as exc:
        if tmp_dest.exists():
            tmp_dest.unlink(missing_ok=True)
        raise MoveError(f"Spostamento cross-device fallito: {exc}") from exc


def copy_cover_if_needed(source_cover: str, dest_cover: str) -> None:
    """Copia (non move: la cover puo' servire per piu' tracce dello stesso
    album) la cover normalizzata nella directory dell'album, se non gia'
    presente/da sovrascrivere (la policy e' gia' stata valutata a monte)."""
    dest = Path(dest_cover)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_cover, dest_cover)
