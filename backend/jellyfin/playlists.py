"""
Playlist per genere in Jellyfin.

Per ogni genere presente tra i brani completati crea (o aggiorna) una
playlist "<GENRE_PLAYLIST_PREFIX><Genere>" di proprieta' dell'utente
JELLYFIN_USER (default: primo amministratore). La sincronizzazione e'
idempotente: aggiunge i brani mancanti e toglie quelli che hanno cambiato
genere. Le playlist che iniziano col prefisso sono considerate "gestite"
dall'app: non metterci brani a mano, verrebbero rimossi.

I file vengono abbinati agli item Jellyfin confrontando il percorso relativo
alla libreria (Artist/Album/file.m4a): cosi' funziona anche se Jellyfin
monta la cartella musica su un path diverso da /music.

Un brano appena scaricato compare in Jellyfin solo dopo la scansione della
libreria: per questo la sync automatica parte con un ritardo
(GENRE_PLAYLIST_SYNC_DELAY_SECONDS) e i brani non ancora indicizzati vengono
ripresi alla sync successiva.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import httpx

from backend.config import settings
from backend.database.repository import DownloadRepository
from backend.utils.logging import get_logger

logger = get_logger(__name__)

_BATCH = 100  # id per richiesta: evita URL troppo lunghi


class PlaylistSyncError(RuntimeError):
    pass


@dataclass
class PlaylistSyncResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    not_indexed: int = 0  # brani non (ancora) trovati in Jellyfin
    playlists: dict[str, int] = field(default_factory=dict)  # nome -> n. brani


def _headers() -> dict:
    token = settings.jellyfin_api_key
    # Header moderno + legacy: le versioni recenti di Jellyfin preferiscono
    # "Authorization: MediaBrowser Token=...", le piu' vecchie X-Emby-Token.
    return {"Authorization": f'MediaBrowser Token="{token}"', "X-Emby-Token": token}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.jellyfin_url.rstrip("/"), headers=_headers(), timeout=30)


def playlists_available() -> bool:
    return bool(
        settings.genre_playlists_enabled and settings.jellyfin_enabled
        and settings.jellyfin_url and settings.jellyfin_api_key
    )


async def _get(client: httpx.AsyncClient, path: str, **params) -> dict | list:
    response = await client.get(path, params=params)
    response.raise_for_status()
    return response.json()


async def _resolve_user_id(client: httpx.AsyncClient) -> str:
    users = await _get(client, "/Users")
    if not users:
        raise PlaylistSyncError("Nessun utente trovato su Jellyfin")
    wanted = settings.jellyfin_user.strip().lower()
    if wanted:
        for user in users:
            if str(user.get("Name", "")).lower() == wanted:
                return user["Id"]
        raise PlaylistSyncError(f"Utente Jellyfin '{settings.jellyfin_user}' non trovato")
    admins = [u for u in users if (u.get("Policy") or {}).get("IsAdministrator")]
    return (admins or users)[0]["Id"]


def _relative_library_path(file_path: str) -> str | None:
    try:
        return Path(file_path).resolve().relative_to(Path(settings.music_dir).resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _index_items_by_filename(items: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """nome file -> [(path normalizzato, item id)]"""
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for item in items:
        path = str(item.get("Path") or "").replace("\\", "/")
        if path:
            index[PurePosixPath(path).name].append((path, item["Id"]))
    return index


def _match_item(index: dict, relative_path: str) -> str | None:
    for path, item_id in index.get(PurePosixPath(relative_path).name, []):
        if path == relative_path or path.endswith("/" + relative_path):
            return item_id
    return None


def _chunks(values: list[str]):
    for i in range(0, len(values), _BATCH):
        yield values[i:i + _BATCH]


async def sync_genre_playlists(repo: DownloadRepository) -> PlaylistSyncResult:
    if not playlists_available():
        raise PlaylistSyncError(
            "Playlist per genere non disponibili: servono JELLYFIN_ENABLED=true, "
            "JELLYFIN_URL, JELLYFIN_API_KEY e GENRE_PLAYLISTS_ENABLED=true"
        )

    records = await asyncio.to_thread(repo.list_completed)
    result = PlaylistSyncResult()
    prefix = settings.genre_playlist_prefix

    async with _client() as client:
        user_id = await _resolve_user_id(client)

        audio = await _get(
            client, "/Items", userId=user_id, Recursive="true", IncludeItemTypes="Audio",
            Fields="Path", EnableImages="false", EnableUserData="false",
        )
        index = _index_items_by_filename(audio.get("Items") or [])

        desired: dict[str, list[str]] = defaultdict(list)  # nome playlist -> item ids
        for record in records:
            if not record.genre.strip():
                continue
            relative = _relative_library_path(record.file_path)
            item_id = _match_item(index, relative) if relative else None
            if not item_id:
                result.not_indexed += 1
                continue
            name = f"{prefix}{record.genre.strip()}"
            if item_id not in desired[name]:
                desired[name].append(item_id)
        desired = {n: ids for n, ids in desired.items() if len(ids) >= max(1, settings.genre_playlist_min_tracks)}

        existing_raw = await _get(
            client, "/Items", userId=user_id, Recursive="true", IncludeItemTypes="Playlist",
        )
        # Senza prefisso non possiamo distinguere le playlist "nostre": in quel
        # caso gestiamo solo quelle col nome esatto di un genere attuale.
        existing = {
            p["Name"]: p["Id"] for p in (existing_raw.get("Items") or [])
            if (str(p.get("Name", "")).startswith(prefix) if prefix else p.get("Name") in desired)
        }

        for name, item_ids in desired.items():
            if name not in existing:
                response = await client.post("/Playlists", json={
                    "Name": name, "Ids": item_ids, "UserId": user_id, "MediaType": "Audio",
                })
                response.raise_for_status()
                result.created.append(name)
                result.added += len(item_ids)
                result.playlists[name] = len(item_ids)

        # Playlist gia' esistenti (anche quelle di generi ormai vuoti, che
        # vengono svuotate): allinea il contenuto a quello desiderato.
        for name, playlist_id in existing.items():
            wanted = desired.get(name, [])
            current = await _get(client, f"/Playlists/{playlist_id}/Items", userId=user_id)
            entries = current.get("Items") or []
            current_ids = {e["Id"] for e in entries}

            to_add = [i for i in wanted if i not in current_ids]
            to_remove = [e["PlaylistItemId"] for e in entries if e["Id"] not in set(wanted) and e.get("PlaylistItemId")]

            for chunk in _chunks(to_add):
                response = await client.post(
                    f"/Playlists/{playlist_id}/Items", params={"ids": ",".join(chunk), "userId": user_id},
                )
                response.raise_for_status()
            for chunk in _chunks(to_remove):
                response = await client.delete(
                    f"/Playlists/{playlist_id}/Items", params={"entryIds": ",".join(chunk)},
                )
                response.raise_for_status()

            if to_add or to_remove:
                result.updated.append(name)
            result.added += len(to_add)
            result.removed += len(to_remove)
            if wanted:
                result.playlists[name] = len(wanted)

    logger.info(
        "Playlist per genere sincronizzate: %s create, %s aggiornate, +%s/-%s brani, %s non indicizzati",
        len(result.created), len(result.updated), result.added, result.removed, result.not_indexed,
    )
    return result


# ---------------------------------------------------------------------------
# Sync automatica "debounced": tanti download ravvicinati (es. una playlist)
# producono UNA sola sincronizzazione, qualche tempo dopo l'ultimo.
# ---------------------------------------------------------------------------

_scheduled: asyncio.Task | None = None


def schedule_playlist_sync(repo: DownloadRepository, delay: float | None = None) -> None:
    global _scheduled
    if not playlists_available():
        return
    if _scheduled and not _scheduled.done():
        _scheduled.cancel()
    wait = settings.genre_playlist_sync_delay_seconds if delay is None else delay
    _scheduled = asyncio.create_task(_delayed_sync(repo, wait), name="genre-playlist-sync")


async def _delayed_sync(repo: DownloadRepository, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        await sync_genre_playlists(repo)
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # mai far crashare nulla per una sync fallita
        logger.warning("Sync automatica delle playlist per genere fallita: %s", exc)
