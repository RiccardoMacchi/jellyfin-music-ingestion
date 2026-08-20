#!/bin/sh
# Entrypoint: allinea l'utente applicativo a PUID/PGID e droppa i privilegi.
#
# Perche' serve: il servizio scrive nella tua libreria musicale, che e'
# condivisa con Jellyfin e ha gia' un proprietario sull'host. Invece di
# obbligarti a cambiare i permessi della libreria (rischioso), qui adeguiamo
# l'utente DENTRO il container all'UID/GID che possiede quella cartella.
#
# Il container parte come root solo per il tempo di questo script; l'app viene
# poi eseguita come utente non privilegiato via gosu.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Riallinea GID e UID dell'utente applicativo se differiscono da PUID/PGID.
current_gid="$(id -g appuser)"
current_uid="$(id -u appuser)"

if [ "$current_gid" != "$PGID" ]; then
    groupmod -o -g "$PGID" appuser
fi
if [ "$current_uid" != "$PUID" ]; then
    usermod -o -u "$PUID" appuser
fi

# Le dir di stato/lavoro devono appartenere all'utente applicativo.
# NB: /music NON viene mai chownato: e' la libreria condivisa, ne rispettiamo
# i permessi esistenti. Deve solo essere scrivibile da PUID/PGID lato host.
chown -R appuser:appuser /app /data /downloads 2>/dev/null || true

# Avviso diagnostico se /music non risulta scrivibile: e' la causa numero uno
# di file che "non vengono salvati". Non blocchiamo l'avvio (l'health endpoint
# lo segnala comunque), ma lo rendiamo visibile nei log.
if [ ! -w /music ]; then
    echo "ATTENZIONE: /music non e' scrivibile dall'utente $PUID:$PGID." >&2
    echo "           I download non potranno essere inseriti in libreria." >&2
    echo "           Allinea PUID/PGID all'owner della cartella host, oppure" >&2
    echo "           correggi i permessi della cartella montata su /music." >&2
fi

exec gosu appuser "$@"
