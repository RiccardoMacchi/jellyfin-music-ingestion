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

from backend.config import settings
from backend.utils.logging import get_logger

logger = get_logger(__name__)

# Estensioni considerate "audio" per capire se una cartella e' rimasta vuota.
_AUDIO_EXTS = {".m4a", ".mp3", ".flac", ".opus", ".ogg", ".wav", ".aac", ".webm"}


class MoveError(RuntimeError):
    pass


def _is_within(path: Path, root: Path) -> bool:
    """True se `path` sta dentro `root` (dopo resolve). Guardrail di sicurezza:
    impedisce di eliminare qualunque cosa fuori dalla libreria musicale."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def delete_from_library(file_path: str) -> bool:
    """Elimina DAVVERO il file audio dalla libreria e ripulisce le cartelle
    rimaste orfane (cover.jpg residua + directory vuote). Ritorna True se ha
    eliminato il file. Per sicurezza opera esclusivamente dentro MUSIC_DIR:
    un path fuori dalla libreria viene ignorato."""
    if not file_path:
        return False

    music_root = Path(settings.music_dir)
    target = Path(file_path)

    if not _is_within(target, music_root):
        logger.warning("Rifiuto di eliminare un file fuori da MUSIC_DIR: %s", file_path)
        return False

    deleted = False
    if target.exists():
        try:
            target.unlink()
            deleted = True
        except OSError as exc:
            logger.warning("Impossibile eliminare %s: %s", file_path, exc)
            return False

    # Cleanup: se nella cartella non restano piu' file audio, rimuovi la cover
    # residua e le directory vuote (album e, a cascata, artista).
    folder = target.parent
    root_resolved = music_root.resolve()
    try:
        if folder.is_dir() and _is_within(folder, music_root) and folder.resolve() != root_resolved:
            has_audio = any(p.suffix.lower() in _AUDIO_EXTS for p in folder.iterdir())
            if not has_audio:
                for leftover in folder.iterdir():
                    leftover.unlink(missing_ok=True)
                folder.rmdir()
                parent = folder.parent
                if _is_within(parent, music_root) and parent.resolve() != root_resolved and not any(parent.iterdir()):
                    parent.rmdir()
    except OSError as exc:
        logger.warning("Cleanup cartella dopo eliminazione non riuscito (%s): %s", folder, exc)

    return deleted


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
