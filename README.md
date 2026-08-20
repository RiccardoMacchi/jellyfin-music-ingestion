# Jellyfin Music Ingestion

Incolli un link YouTube, e ottieni un brano correttamente inserito nella tua
libreria musicale **Jellyfin** — con metadata, cover e struttura di cartelle
che Jellyfin sa riconoscere.

Non è un "YouTube → MP3 downloader": è una **pipeline di ingestion** che tratta
ogni brano come un elemento di libreria, non come un file qualsiasi.

```text
YouTube URL → metadata → analisi → download → conversione → tag →
cover → filename → organizzazione → validazione → move atomico → /music
```

---

## Indice

- [Come funziona la pipeline](#come-funziona-la-pipeline)
- [Scelte di design Jellyfin-first](#scelte-di-design-jellyfin-first)
- [Formato audio: perché M4A/AAC di default](#formato-audio-perché-m4aaac-di-default)
- [Sviluppo locale](#sviluppo-locale)
- [Docker](#docker)
- [Volumi](#volumi)
- [Deploy con Coolify](#deploy-con-coolify)
- [Integrazione Jellyfin (opzionale)](#integrazione-jellyfin-opzionale)
- [Variabili d'ambiente](#variabili-dambiente)
- [API](#api)
- [Produzione: best practice](#produzione-best-practice)
- [Backup](#backup)
- [Aggiornamento](#aggiornamento)
- [Troubleshooting](#troubleshooting)
- [Test](#test)

---

## Come funziona la pipeline

Ogni download attraversa passi separati e modulari. Il file finale **non viene
mai scritto direttamente** in `/music`: tutto avviene in un'area temporanea
(`/downloads`), e solo dopo la validazione il file viene spostato in libreria
con un `os.replace` atomico. Se un passaggio fallisce, `/music` resta intatta.

1. **Metadata extraction** — yt-dlp estrae titolo, canale, durata, thumbnail (nessun download).
2. **Content analysis** — il titolo grezzo (`Artist - Song (Official Video)`) viene analizzato per ricavare artista, titolo ed eventuali `feat.`, **senza inventare** dati quando il pattern non è riconoscibile.
3. **Preview** — la UI mostra i metadata proposti; puoi correggerli prima di scaricare.
4. **Download** — yt-dlp scarica **solo l'audio** alla miglior qualità sorgente.
5. **Conversione** — FFmpeg produce il formato finale in **un solo passaggio** (remux senza re-encode quando la sorgente è già AAC → M4A).
6. **Tag** — i metadata vengono scritti nel file (m4a/mp3/flac).
7. **Cover** — la thumbnail viene normalizzata in `cover.jpg`, incorporata nel file e salvata nella cartella dell'album (secondo `COVER_POLICY`).
8. **Filename & organizzazione** — nome file e percorso derivano dai metadata, con sanitizzazione sicura per Linux.
9. **Validazione** — FFprobe verifica che il file sia integro, con codec e durata corretti.
10. **Move atomico** — il file entra in `/music`.
11. **Refresh Jellyfin** (opzionale) — se configurato, chiede a Jellyfin di riscansionare.

---

## Scelte di design Jellyfin-first

La struttura di libreria è pensata per lo scanner musicale di Jellyfin:

```text
/music/
├── Artist A/
│   ├── Great Album/
│   │   ├── 01 - Song.m4a
│   │   ├── 02 - Song.m4a
│   │   └── cover.jpg
│   └── Singles/
│       └── Song.m4a
└── Various Artists/
    └── Compilation 2023/
        ├── 01 - Track.m4a   (Artist = artista della traccia)
        └── cover.jpg
```

Decisioni specifiche e perché:

- **La cartella di primo livello è l'Album Artist, non l'Artist del singolo brano.** Un brano `Artist A feat. Artist B` ha `Artist = "Artist A feat. Artist B"` ma `Album Artist = "Artist A"`. Jellyfin raggruppa gli album per Album Artist: usare l'Artist qui creerebbe artisti duplicati ad ogni featuring diverso.
- **Compilation → `Various Artists`.** Quando marchi un download come compilation, l'Album Artist diventa `Various Artists` (e viene impostato il flag di compilation nei tag), così Jellyfin la riconosce come raccolta e non come un album di un singolo artista.
- **Singoli → `Artist/Singles/`.** Se non c'è un album affidabile, il brano finisce in `Singles`, ma mantiene comunque i tag Artist/Title. I singoli **non** condividono una `cover.jpg` di cartella (ogni singolo può avere copertine diverse); la cover resta comunque **incorporata** nel file.
- **Track number solo quando ha senso.** Il numero di traccia viene assegnato dalla posizione in playlist **solo se** hai confermato che quella playlist rappresenta un album/raccolta. Altrimenti non viene inventato.
- **Metadata prima del filename.** Il nome file è una conseguenza dei tag, mai il contrario.

---

## Formato audio: perché M4A/AAC di default

Il formato è configurabile (`AUDIO_FORMAT`), ma il default è **M4A/AAC** per queste ragioni:

| Formato | Qualità | Compatibilità Jellyfin | Spazio | Transcoding | Metadata / Cover |
|---|---|---|---|---|---|
| **M4A/AAC** (default) | Ottima a 192k, indistinguibile dalla sorgente YouTube | Nativa, direct-play su quasi ogni client | Compatto | Raramente necessario | Pieni, cover incorporata bene |
| MP3 | Buona, leggermente inferiore ad AAC a pari bitrate | Universale | Compatto | Raro | Pieni (ID3v2) |
| FLAC | Lossless | Nativa | **Grande** (2–5×) | Spesso richiesto in streaming | Pieni |

**Perché non FLAC di default:** l'audio di YouTube è già compresso con perdita (tipicamente Opus). Ri-codificarlo in FLAC produce un file enorme senza recuperare qualità: staresti solo impacchettando in lossless un audio già lossy. FLAC ha senso solo se importi da sorgenti realmente lossless — e in quel caso puoi impostare `AUDIO_FORMAT=flac`.

**Perché AAC e non MP3:** a parità di bitrate AAC rende meglio, ed è direct-play sui client Jellyfin senza transcoding lato server.

**Un solo passaggio di conversione.** Quando la sorgente YouTube è già AAC (itag 140), il servizio fa un **remux** (copia dello stream, nessuna ricodifica: qualità identica, operazione quasi istantanea). Negli altri casi fa **un solo** encode diretto verso il formato finale, mai sorgente → intermedio → finale.

---

## Sviluppo locale

Requisiti: **Python 3.12+**, **FFmpeg** (`ffmpeg` + `ffprobe`) nel PATH.

```bash
# 1. Dipendenze
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. Configurazione (per lo sviluppo locale usa cartelle relative)
cp .env.example .env
#   e in .env imposta, ad esempio:
#     MUSIC_DIR=./music
#     DATA_DIR=./data
#     DOWNLOAD_DIR=./downloads
mkdir -p music data downloads

# 3. Avvio (hot-reload)
uvicorn backend.main:app --reload --port 8000
```

Apri <http://localhost:8000> per la UI e <http://localhost:8000/docs> per la
documentazione OpenAPI interattiva.

---

## Docker

Il progetto si builda direttamente dal `Dockerfile` (nessuno script esterno).

```bash
# Build
docker build -t jellyfin-music-ingestion .

# Run (esempio: mount su cartelle locali)
docker run -d --name jmi \
  -p 8000:8000 \
  -v /percorso/host/Music:/music \
  -v /percorso/host/jmi-data:/data \
  -v /percorso/host/jmi-downloads:/downloads \
  -e AUDIO_FORMAT=m4a \
  -e COVER_POLICY=preserve \
  jellyfin-music-ingestion
```

In alternativa, per uso standalone c'è un `docker-compose.yml` pronto:

```bash
docker compose up -d --build
```

L'immagine include FFmpeg, gira come utente non-root (UID/GID 1000), espone un
`HEALTHCHECK` su `/api/health` e gestisce `SIGTERM` con shutdown pulito della coda.

---

## Volumi

Il container ragiona **solo** in termini di questi tre mount point. Il mapping
verso il filesystem reale del server è configurazione di deployment, non del software.

| Mount nel container | Cosa contiene | Note |
|---|---|---|
| `/music` | La libreria Jellyfin (output finale) | Deve puntare alla **stessa** cartella che Jellyfin usa come libreria musicale (nel tuo caso `/data/media/Music`). |
| `/data` | Database SQLite + stato della coda | **Va persistito**: è la memoria della coda e della cronologia. |
| `/downloads` | Lavoro temporaneo | Può essere effimero; viene ripulito automaticamente. Persisterlo aiuta solo a non riscaricare tra un redeploy e l'altro. |

> Il servizio **non** conosce né assume alcun percorso host. `/data/media/Music`
> è una tua configurazione di mount; il codice usa sempre `/music`.

---

## Deploy con Coolify

Il progetto è pensato per Coolify ma **non contiene codice specifico di Coolify**.
A grandi linee:

1. **Nuova risorsa → build dal Dockerfile.** Punta Coolify a questo repository; userà il `Dockerfile` alla radice.
2. **Porta.** Esponi la porta HTTP `8000` (Coolify la mette dietro al suo reverse proxy / Traefik, come per gli altri tuoi subdomain).
3. **Volumi.** Configura i mount:
   - `/data/media/Music` (host) → `/music` (container) — la stessa libreria che monti in Jellyfin
   - un volume persistente → `/data`
   - un volume (anche effimero) → `/downloads`
4. **Environment variables.** Imposta le variabili dalla sezione qui sotto direttamente nell'interfaccia di Coolify (non serve un file `.env` in produzione).
5. **Deploy.** Coolify builda l'immagine, avvia il container e usa l'`HEALTHCHECK` integrato per sapere quando è pronto.

Nessun passo di configurazione avviene dentro il software: colleghi tu i volumi
e le variabili in fase di deployment.

---

## Integrazione Jellyfin (opzionale)

L'applicazione funziona **anche senza** l'API di Jellyfin: il file finisce
comunque correttamente in `/music`, e Jellyfin lo troverà alla sua prossima
scansione (schedulata o manuale).

Se vuoi un refresh automatico dopo ogni inserimento:

```env
JELLYFIN_ENABLED=true
JELLYFIN_URL=http://jellyfin:8096      # URL raggiungibile dal container
JELLYFIN_API_KEY=la-tua-api-key        # Jellyfin → Dashboard → API Keys
```

Comportamento voluto: se la chiamata a Jellyfin fallisce (Jellyfin spento,
rete non raggiungibile, ecc.), **il download non è considerato fallito** — il
file è già in libreria. L'errore viene solo loggato.

---

## Variabili d'ambiente

| Variabile | Default | Descrizione |
|---|---|---|
| `APP_NAME` | `Jellyfin Music Ingestion` | Nome mostrato nella UI. |
| `APP_VERSION` | `1.0.0` | Versione, esposta da `/api/version`. |
| `PORT` | `8000` | Porta HTTP del servizio. |
| `MUSIC_DIR` | `/music` | Mount della libreria Jellyfin (output finale). |
| `DATA_DIR` | `/data` | Mount per DB SQLite e stato. Da persistere. |
| `DOWNLOAD_DIR` | `/downloads` | Mount per il lavoro temporaneo. |
| `AUDIO_FORMAT` | `m4a` | `m4a` \| `mp3` \| `flac`. Vedi sezione formato audio. |
| `AUDIO_BITRATE` | `192K` | Bitrate per formati lossy (ignorato per `flac`). |
| `MAX_CONCURRENT_DOWNLOADS` | `1` | Download processati in parallelo. `1` è consigliato per non saturare CPU/rete su un self-host. |
| `COVER_POLICY` | `preserve` | `preserve` (non sovrascrive una `cover.jpg` già presente) \| `overwrite`. |
| `PUID` | `1000` | UID con cui l'app scrive i file. Allinealo all'owner della cartella host montata su `/music`. |
| `PGID` | `1000` | GID con cui l'app scrive i file. Come sopra. |
| `JELLYFIN_ENABLED` | `false` | Attiva il refresh automatico della libreria Jellyfin. |
| `JELLYFIN_URL` | *(vuoto)* | URL base di Jellyfin, raggiungibile dal container. |
| `JELLYFIN_API_KEY` | *(vuoto)* | API key Jellyfin. |
| `TZ` | `Europe/Rome` | Timezone per log e timestamp. |

---

## API

Documentazione OpenAPI interattiva su `/docs` (e schema su `/openapi.json`).

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `POST` | `/api/analyze` | Analizza un URL video: ritorna i metadata proposti (nessun download). |
| `POST` | `/api/playlist/analyze` | Analizza una playlist: ritorna l'elenco delle tracce. |
| `POST` | `/api/download` | Accoda un download (con eventuali correzioni manuali dei metadata). Idempotente per `youtube_id`. |
| `GET` | `/api/downloads` | Elenca i download (filtro opzionale `?status=`). |
| `GET` | `/api/downloads/{id}` | Dettaglio di un download. |
| `POST` | `/api/downloads/{id}/retry` | Ri-accoda un download `FAILED`/`CANCELLED`. |
| `POST` | `/api/downloads/{id}/cancel` | Annulla un download in coda o in corso. |
| `DELETE` | `/api/downloads/{id}` | Rimuove un download dalla cronologia. |
| `GET` | `/api/events` | Stream **SSE** con progresso in tempo reale (percentuale, velocità, ETA, stato). |
| `GET` | `/api/health` | Healthcheck (usato anche dal container). |
| `GET` | `/api/version` | Nome e versione applicazione. |

**Perché SSE e non WebSocket:** il progresso è unidirezionale (server → UI), e
SSE si integra con `EventSource` nel browser senza librerie extra e attraversa i
reverse proxy (incluso quello davanti a Coolify) senza configurazioni particolari.

---

## Produzione: best practice

- **Persisti `/data`.** È dove vivono il database e la coda; senza persistenza perdi cronologia e job in attesa ad ogni redeploy.
- **Punta `/music` alla stessa cartella di Jellyfin.** Il valore aggiunto è che il file appare direttamente nella libreria reale.
- **Tieni `MAX_CONCURRENT_DOWNLOADS=1`** su hardware modesto (es. una VM Oracle Cloud): la conversione FFmpeg è CPU-bound.
- **Metti il servizio dietro autenticazione.** Non ha un login integrato; usa il reverse proxy di Coolify (basic auth / access control) per non esporlo pubblicamente in chiaro.
- **`COVER_POLICY=preserve`** se curi manualmente alcune copertine: evita che un nuovo download sovrascriva una cover migliore già presente.

---

## Backup

Da salvare:

- **`/data`** — contiene `app.db` (SQLite): cronologia, coda, stato. È l'unico stato che non puoi rigenerare. Un semplice backup periodico del file `app.db` è sufficiente (il DB usa WAL; per un backup a caldo copia `app.db`, `app.db-wal`, `app.db-shm` insieme, oppure ferma il container un istante).
- **`/music`** — è la tua libreria; presumibilmente è già nel tuo backup dei media.

`/downloads` **non** va salvato: è solo lavoro temporaneo.

---

## Aggiornamento

Il downloader dipende da **yt-dlp**, che va aggiornato spesso (YouTube cambia
di frequente). yt-dlp è una normale dipendenza Python: per aggiornarlo basta
ricostruire l'immagine.

```bash
# Aggiorna yt-dlp (e le altre dipendenze) alla versione pinnata più recente
#   -> modifica la versione in requirements.txt, poi:
docker build --no-cache -t jellyfin-music-ingestion .
```

Su Coolify: fai un redeploy con build pulita quando aggiorni yt-dlp. Se un
download inizia a fallire con errori di estrazione, quasi sempre la causa è un
yt-dlp datato: aggiorna e riprova.

---

## Troubleshooting

**Un download resta `FAILED` con errore di estrazione / "Unable to extract".**
yt-dlp è probabilmente datato. Aggiorna (vedi sopra) e usa "Riprova" nella UI.

**Il file appare in `/music` ma Jellyfin non lo vede.**
Verifica che `/music` nel container sia mappato sulla **stessa** cartella che
Jellyfin usa come libreria. Poi fai un refresh in Jellyfin (o attiva
`JELLYFIN_ENABLED=true`). Controlla anche che i permessi sui file siano leggibili
dall'utente di Jellyfin.

**Artisti o album duplicati in Jellyfin.**
Di solito è un problema di Album Artist. Per gli album usa un Album Artist
coerente (senza i `feat.`); per le compilation marca il flag "Various Artists".

**`music_dir_writable: false` in `/api/health`.**
L'utente del container non può scrivere nella cartella montata su `/music`.
Imposta `PUID`/`PGID` uguali all'owner della cartella host (ricavalo con
`stat -c '%u:%g' /data/media/Music`) e ridistribuisci, oppure correggi i
permessi della cartella lato host.

**La coda sembra "bloccata" dopo un crash/redeploy.**
All'avvio il servizio recupera automaticamente i job rimasti "in volo"
(`DOWNLOADING`/`PROCESSING`) rimettendoli in `PENDING`. Se non riparte, controlla
i log del container.

**Progresso non aggiornato nella UI.**
La UI usa SSE su `/api/events`. Se hai un reverse proxy davanti, assicurati che
non bufferizzi le risposte `text/event-stream` (per Nginx: `proxy_buffering off`).

---

## Test

La suite non effettua **mai** download reali da YouTube: yt-dlp è sempre
mockato. FFmpeg e mutagen, invece, girano davvero su file audio di test generati
al volo, così la conversione, il tagging e la validazione sono verificati end-to-end.

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Copertura: validazione URL, parsing e normalizzazione metadata, sanitizzazione
filename, costruzione path libreria, move atomico (incluso il fallback
cross-device), policy cover, tagging reale, conversione audio reale, database,
coda e recovery dopo crash, retry, cancellazione, pipeline completa (yt-dlp
mockato) e l'intero layer API, più l'integrazione Jellyfin con httpx mockato.
