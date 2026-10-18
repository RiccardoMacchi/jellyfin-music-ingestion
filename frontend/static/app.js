/* Jellyfin Music Ingestion — frontend vanilla JS (nessun build step).
 * Comunica esclusivamente con le API sotto /api. Vedi README per i dettagli. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  const ACTIVE_STATUSES = new Set(["PENDING", "DOWNLOADING", "PROCESSING"]);

  let lastAnalyzed = null; // risposta di /api/analyze in corso di conferma

  // ------------------------------------------------------------------
  // Bootstrap: versione + health
  // ------------------------------------------------------------------
  async function loadSystemInfo() {
    try {
      const v = await fetchJSON("/api/version");
      $("#version-pill").textContent = `v${v.app_version}`;
    } catch { $("#version-pill").textContent = "v?"; }
  }

  async function fetchJSON(url, opts) {
    const res = await fetch(url, opts);
    let body = null;
    try { body = await res.json(); } catch { /* no body */ }
    if (!res.ok) {
      const detail = (body && body.detail) || res.statusText || "Errore sconosciuto";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return body;
  }

  // ------------------------------------------------------------------
  // Analyze
  // ------------------------------------------------------------------
  $("#analyze-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = $("#url-input").value.trim();
    if (!url) return;

    setAnalyzeError("");
    setAnalyzing(true);
    hidePreviewPanels();

    try {
      const preview = await fetchJSON("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      if (preview.is_playlist) {
        const playlist = await fetchJSON("/api/playlist/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url }),
        });
        showPlaylistPreview(playlist);
      } else {
        showSinglePreview(preview);
      }
    } catch (err) {
      setAnalyzeError(err.message);
    } finally {
      setAnalyzing(false);
    }
  });

  function setAnalyzing(state) {
    $("#analyze-btn").disabled = state;
    $("#analyze-btn").textContent = state ? "Analisi…" : "Analizza";
  }
  function setAnalyzeError(msg) {
    const e = $("#analyze-error");
    e.textContent = msg;
    e.hidden = !msg;
  }
  function hidePreviewPanels() {
    $("#preview-panel").hidden = true;
    $("#playlist-panel").hidden = true;
  }

  // ------------------------------------------------------------------
  // Preview: singolo brano
  // ------------------------------------------------------------------
  function showSinglePreview(p) {
    lastAnalyzed = p;
    $("#preview-cover").src = p.thumbnail_url || "";
    $("#f-title").value = p.suggested_title || "";
    $("#f-artist").value = p.suggested_artist || "";
    $("#f-album").value = "";
    $("#f-album-artist").value = p.suggested_album_artist || p.suggested_artist || "";
    $("#f-track").value = "";
    $("#f-disc").value = "";
    $("#f-year").value = "";
    $("#f-genre").value = p.suggested_genre || "";
    $("#f-genre-source").textContent = p.suggested_genre ? `(suggerito da ${sourceLabel(p.suggested_genre_source)})` : "";
    $("#f-composer").value = "";
    $("#f-compilation").checked = false;
    $("#f-trim-start").value = "";
    $("#f-trim-end").value = "";
    updatePreviewTrimHint();
    $("#preview-panel").hidden = false;
    $("#preview-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function updatePreviewTrimHint() {
    return readTrim($("#f-trim-start"), $("#f-trim-end"),
      lastAnalyzed && lastAnalyzed.duration_seconds, $("#f-trim-hint"));
  }
  $("#f-trim-start").addEventListener("input", updatePreviewTrimHint);
  $("#f-trim-end").addEventListener("input", updatePreviewTrimHint);

  $("#preview-cancel").addEventListener("click", () => {
    $("#preview-panel").hidden = true;
    lastAnalyzed = null;
  });

  $("#preview-download").addEventListener("click", async () => {
    if (!lastAnalyzed) return;
    const trim = updatePreviewTrimHint();
    if (!trim) return;
    const btn = $("#preview-download");
    btn.disabled = true;
    try {
      await fetchJSON("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: lastAnalyzed.url,
          youtube_id: lastAnalyzed.youtube_id,
          title: $("#f-title").value.trim(),
          artist: $("#f-artist").value.trim(),
          album: $("#f-album").value.trim(),
          album_artist: $("#f-album-artist").value.trim() || undefined,
          track_number: numOrNull($("#f-track").value),
          disc_number: numOrNull($("#f-disc").value),
          year: numOrNull($("#f-year").value),
          genre: $("#f-genre").value.trim(),
          // Genere suggerito e lasciato invariato -> resta "automatico",
          // cosi' un futuro ricalcolo potra' aggiornarlo; se modificato e' manuale.
          genre_source: $("#f-genre").value.trim() && $("#f-genre").value.trim() === lastAnalyzed.suggested_genre
            ? lastAnalyzed.suggested_genre_source : undefined,
          composer: $("#f-composer").value.trim(),
          is_compilation: $("#f-compilation").checked,
          thumbnail_url: lastAnalyzed.thumbnail_url,
          duration_seconds: lastAnalyzed.duration_seconds,
          trim_start_seconds: trim.start,
          trim_end_seconds: trim.end,
        }),
      });
      $("#preview-panel").hidden = true;
      $("#url-input").value = "";
      lastAnalyzed = null;
      refreshQueue();
    } catch (err) {
      setAnalyzeError(err.message);
    } finally {
      btn.disabled = false;
    }
  });

  // "83", "83.5", "1:23", "1:02:03" -> secondi. "" -> 0. Non valido -> NaN.
  function parseTime(v) {
    const s = String(v || "").trim().replace(",", ".");
    if (!s) return 0;
    if (!/^\d+(\.\d+)?$|^\d+(:\d{1,2}){1,2}(\.\d+)?$/.test(s)) return NaN;
    return s.split(":").reduce((acc, part) => acc * 60 + Number(part), 0);
  }

  function formatTime(sec) {
    if (sec === null || sec === undefined || !Number.isFinite(sec)) return "";
    const total = Math.max(0, Math.round(sec));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
  }

  // Valida i due campi di taglio rispetto alla durata e scrive l'esito in
  // `hintEl`. Ritorna {start, end} oppure null se i valori non sono validi.
  const MIN_REMAINING_SECONDS = 5;
  function readTrim(startInput, endInput, duration, hintEl) {
    const start = parseTime(startInput.value);
    const end = parseTime(endInput.value);
    hintEl.classList.remove("error");
    if (Number.isNaN(start) || Number.isNaN(end)) {
      hintEl.textContent = "Formato non valido: usa secondi (es. 12) oppure m:ss (es. 1:05).";
      hintEl.classList.add("error");
      return null;
    }
    if (duration && duration - start - end < MIN_REMAINING_SECONDS) {
      hintEl.textContent = `Taglio troppo lungo: il brano dura ${formatTime(duration)}.`;
      hintEl.classList.add("error");
      return null;
    }
    if (!start && !end) {
      hintEl.textContent = duration ? `Durata: ${formatTime(duration)}` : "";
    } else if (duration) {
      hintEl.textContent = `Durata: ${formatTime(duration)} → ${formatTime(duration - start - end)} dopo il taglio`;
    } else {
      hintEl.textContent = "";
    }
    return { start, end };
  }

  function sourceLabel(source) {
    return { deezer: "Deezer", musicbrainz: "MusicBrainz", manual: "te" }[source] || source;
  }

  function numOrNull(v) {
    if (v === "" || v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  // ------------------------------------------------------------------
  // Preview: playlist
  // ------------------------------------------------------------------
  let currentPlaylist = null;

  function showPlaylistPreview(playlist) {
    currentPlaylist = playlist;
    $("#playlist-title").textContent = playlist.title || "Playlist";
    $("#pl-album").value = "";
    $("#pl-album-artist").value = "";
    $("#pl-compilation").checked = false;

    const list = $("#playlist-items");
    list.innerHTML = "";
    playlist.entries.forEach((entry) => {
      const li = el("li", "playlist-item");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.dataset.index = String(entry.index);
      const idx = el("span", "idx", String(entry.index).padStart(2, "0"));
      const title = el("span", "ptitle", entry.title);
      li.append(cb, idx, title);
      list.appendChild(li);
    });

    $("#preview-panel").hidden = true;
    $("#playlist-panel").hidden = false;
    $("#playlist-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  $("#playlist-select-all").addEventListener("change", (e) => {
    document.querySelectorAll("#playlist-items input[type=checkbox]")
      .forEach((cb) => (cb.checked = e.target.checked));
  });

  $("#playlist-cancel").addEventListener("click", () => {
    $("#playlist-panel").hidden = true;
    currentPlaylist = null;
  });

  $("#playlist-queue").addEventListener("click", async () => {
    if (!currentPlaylist) return;
    const btn = $("#playlist-queue");
    btn.disabled = true;
    btn.textContent = "Accodo…";

    const album = $("#pl-album").value.trim();
    const albumArtist = $("#pl-album-artist").value.trim();
    const isCompilation = $("#pl-compilation").checked;

    const checked = Array.from(document.querySelectorAll("#playlist-items input[type=checkbox]:checked"))
      .map((cb) => Number(cb.dataset.index));
    const entries = currentPlaylist.entries.filter((e) => checked.includes(e.index));

    let queued = 0, failed = 0;
    for (const entry of entries) {
      try {
        await fetchJSON("/api/download", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: entry.url,
            youtube_id: entry.youtube_id,
            album,
            album_artist: albumArtist || undefined,
            track_number: album ? entry.index : null,
            is_compilation: isCompilation,
            source_type: "playlist_item",
            position_in_playlist: entry.index,
          }),
        });
        queued++;
      } catch {
        failed++;
      }
    }

    btn.disabled = false;
    btn.textContent = "Accoda selezionati";
    $("#playlist-panel").hidden = true;
    $("#url-input").value = "";
    currentPlaylist = null;
    refreshQueue();
    if (failed) setAnalyzeError(`${queued} brani accodati, ${failed} falliti.`);
  });

  // ------------------------------------------------------------------
  // Coda: rendering + SSE live updates
  // ------------------------------------------------------------------
  function renderVuMeter(status, progress) {
    const bars = 12;
    const lit = Math.round((progress / 100) * bars);
    const wrap = el("div", `vu-meter status-${status}`);
    for (let i = 0; i < bars; i++) {
      wrap.appendChild(el("span", `bar${i < lit ? " lit" : ""}`));
    }
    return wrap;
  }

  function renderQueueItem(d) {
    const li = el("li", "queue-item");

    const top = el("div", "queue-item-top");
    const left = el("div");
    left.appendChild(el("div", "queue-item-title", d.title || d.url));
    if (d.artist) left.appendChild(el("div", "queue-item-artist", d.artist));
    const meta = el("span", "queue-item-meta", metaLabel(d));
    top.append(left, meta);

    li.appendChild(top);
    li.appendChild(renderVuMeter(d.status, d.progress || 0));

    const footer = el("div", "queue-item-footer");
    footer.appendChild(el("span", `status-tag ${d.status}`, d.status));
    if (d.status === "PENDING" || d.status === "DOWNLOADING") {
      const cancelBtn = el("button", "btn btn-ghost btn-sm", "Annulla");
      cancelBtn.addEventListener("click", () => cancelDownload(d.id));
      footer.appendChild(cancelBtn);
    }
    li.appendChild(footer);

    if (d.error) {
      const err = el("div", "herror", d.error);
      li.appendChild(err);
    }

    return li;
  }

  function metaLabel(d) {
    if (d.status === "DOWNLOADING" || d.status === "PROCESSING") {
      const parts = [`${(d.progress || 0).toFixed(0)}%`];
      if (d.speed) parts.push(d.speed);
      if (d.eta) parts.push(`ETA ${d.eta}`);
      return parts.join(" · ");
    }
    return d.status;
  }

  async function cancelDownload(id) {
    try {
      await fetchJSON(`/api/downloads/${id}/cancel`, { method: "POST" });
      refreshQueue();
    } catch (err) {
      console.error(err);
    }
  }

  async function refreshQueue() {
    try {
      const all = await fetchJSON("/api/downloads");
      const active = all.filter((d) => ACTIVE_STATUSES.has(d.status));
      renderQueue(active);
    } catch (err) {
      console.error(err);
    }
  }

  function renderQueue(items) {
    const list = $("#queue-list");
    const empty = $("#queue-empty");
    list.querySelectorAll(".queue-item").forEach((n) => n.remove());
    $("#queue-count").textContent = String(items.length);
    empty.hidden = items.length > 0;
    items.forEach((d) => list.appendChild(renderQueueItem(d)));
  }

  function connectEvents() {
    const source = new EventSource("/api/events");
    source.addEventListener("update", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        const before = $("#queue-count").textContent;
        renderQueue(data.downloads || []);
        if ($("#queue-count").textContent !== before) loadGenres();
        // Un job puo' essere appena uscito dagli stati attivi (completato/fallito):
        // aggiorniamo anche la cronologia se e' la tab corrente.
        loadHistory(currentHistoryStatus);
      } catch (err) { console.error(err); }
    });
    source.onerror = () => {
      // EventSource riprova automaticamente la connessione; nel frattempo
      // manteniamo la coda aggiornata con un polling di fallback.
    };
  }

  // ------------------------------------------------------------------
  // Cronologia / libreria
  // ------------------------------------------------------------------
  let currentHistoryStatus = "";

  $("#history-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (!btn) return;
    document.querySelectorAll("#history-tabs .tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    currentHistoryStatus = btn.dataset.status;
    loadHistory(currentHistoryStatus);
  });

  // Mentre un editor in linea e' aperto, gli aggiornamenti live (SSE) NON
  // ridisegnano la tabella: si perderebbero i valori digitati e il focus.
  let openEditorId = null;
  let historyReloadPending = false;

  async function loadHistory(status) {
    if (openEditorId !== null) {
      historyReloadPending = true;
      return;
    }
    try {
      const qs = status ? `?status=${encodeURIComponent(status)}` : "";
      const all = await fetchJSON(`/api/downloads${qs}`);
      const rows = status ? all : all.filter((d) => !ACTIVE_STATUSES.has(d.status));
      renderHistory(rows);
    } catch (err) {
      console.error(err);
    }
  }

  function renderHistory(rows) {
    const body = $("#history-body");
    body.innerHTML = "";
    $("#history-empty").hidden = rows.length > 0;

    rows.forEach((d) => {
      const tr = document.createElement("tr");

      const tdTrack = document.createElement("td");
      tdTrack.appendChild(el("span", "htitle", d.title || d.url));
      const details = [d.artist, formatTime(d.duration_seconds)].filter(Boolean);
      const trimmed = (d.trim_start_seconds || 0) + (d.trim_end_seconds || 0);
      if (trimmed && d.status === "COMPLETED") details.push(`tagliati ${formatTime(trimmed)}`);
      if (details.length) tdTrack.appendChild(el("span", "hartist", details.join(" · ")));
      if (d.error) tdTrack.appendChild(el("div", "herror", d.error));

      const tdAlbum = document.createElement("td");
      tdAlbum.appendChild(el("span", "", d.album || "—"));
      if (d.genre) {
        const chip = el("span", "genre-chip small", d.genre);
        chip.title = d.genre_source ? `Genere da ${sourceLabel(d.genre_source)}` : "";
        tdAlbum.appendChild(chip);
      }

      const tdStatus = document.createElement("td");
      tdStatus.appendChild(el("span", `status-tag ${d.status}`, d.status));

      const tdActions = document.createElement("td");
      if (d.status === "FAILED" || d.status === "CANCELLED") {
        const retryBtn = el("button", "btn btn-ghost btn-sm", "Riprova");
        retryBtn.addEventListener("click", async () => {
          await fetchJSON(`/api/downloads/${d.id}/retry`, { method: "POST" });
          refreshQueue();
          loadHistory(currentHistoryStatus);
        });
        tdActions.appendChild(retryBtn);
      }
      if (d.status === "COMPLETED") {
        const editBtn = el("button", "btn btn-ghost btn-sm", "Modifica");
        editBtn.addEventListener("click", () => toggleEditor(tr, d));
        tdActions.appendChild(editBtn);
      }
      const delBtn = el("button", "btn btn-ghost btn-sm", "Elimina");
      delBtn.addEventListener("click", async () => {
        // Per i brani completati l'eliminazione rimuove ANCHE il file audio
        // dalla libreria: chiediamo conferma per evitare cancellazioni per
        // sbaglio.
        const removesFile = d.status === "COMPLETED";
        const msg = removesFile
          ? `Eliminare "${d.title || "questo brano"}" dalla libreria? Il file audio verra' rimosso definitivamente.`
          : `Rimuovere "${d.title || "questa voce"}" dalla cronologia?`;
        if (!window.confirm(msg)) return;
        await fetchJSON(`/api/downloads/${d.id}`, { method: "DELETE" });
        loadHistory(currentHistoryStatus);
      });
      tdActions.appendChild(delBtn);

      tr.append(tdTrack, tdAlbum, tdStatus, tdActions);
      body.appendChild(tr);
    });
  }

  function closeEditor() {
    document.querySelectorAll(".editor-row").forEach((n) => n.remove());
    openEditorId = null;
    if (historyReloadPending) {
      historyReloadPending = false;
      loadHistory(currentHistoryStatus);
    }
  }

  function toggleEditor(tr, d) {
    const wasOpen = openEditorId === d.id;
    closeEditor();
    if (wasOpen) return;
    openEditorId = d.id;

    const row = el("tr", "editor-row");
    const td = document.createElement("td");
    td.colSpan = 4;
    const box = el("div", "editor");

    // --- genere
    const genreRow = el("div", "editor-inline");
    const genreField = el("div", "field");
    const genreLabel = el("label", "", "Genere");
    genreLabel.htmlFor = `genre-${d.id}`;
    const genreInput = document.createElement("input");
    genreInput.type = "text";
    genreInput.id = `genre-${d.id}`;
    genreInput.value = d.genre || "";
    genreInput.setAttribute("list", "genre-options");
    genreField.append(genreLabel, genreInput);
    const genreBtn = el("button", "btn btn-ghost btn-sm", "Salva genere");
    const genreHint = el("p", "field-hint");
    genreBtn.addEventListener("click", async () => {
      genreBtn.disabled = true;
      genreHint.classList.remove("error");
      try {
        const updated = await fetchJSON(`/api/downloads/${d.id}/genre`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ genre: genreInput.value.trim() }),
        });
        d.genre = updated.genre;
        d.genre_source = updated.genre_source;
        genreHint.textContent = updated.genre ? `Genere salvato: ${updated.genre}` : "Genere rimosso";
        historyReloadPending = true;
        loadGenres();
      } catch (err) {
        genreHint.textContent = err.message;
        genreHint.classList.add("error");
      } finally {
        genreBtn.disabled = false;
      }
    });
    genreRow.append(genreField, genreBtn);

    const fields = el("div", "field-row");
    const mkField = (labelText, id) => {
      const f = el("div", "field");
      const label = el("label", "", labelText);
      label.htmlFor = id;
      const input = document.createElement("input");
      input.type = "text";
      input.id = id;
      input.inputMode = "decimal";
      input.placeholder = "0";
      f.append(label, input);
      fields.appendChild(f);
      return input;
    };
    const startInput = mkField("Taglia inizio (s o m:ss)", `trim-start-${d.id}`);
    const endInput = mkField("Taglia fine (s o m:ss)", `trim-end-${d.id}`);

    const hint = el("p", "field-hint");
    const update = () => readTrim(startInput, endInput, d.duration_seconds, hint);
    startInput.addEventListener("input", update);
    endInput.addEventListener("input", update);
    update();

    const note = el("p", "field-hint", "Il taglio modifica il file in libreria (senza ricompressione) e non si può annullare.");
    const actions = el("div", "editor-actions");
    const cancelBtn = el("button", "btn btn-ghost btn-sm", "Chiudi");
    cancelBtn.addEventListener("click", closeEditor);
    const applyBtn = el("button", "btn btn-accent btn-sm", "Applica taglio");
    applyBtn.addEventListener("click", async () => {
      const trim = update();
      if (!trim) return;
      if (!trim.start && !trim.end) {
        hint.textContent = "Indica almeno un taglio all'inizio o alla fine.";
        hint.classList.add("error");
        return;
      }
      applyBtn.disabled = true;
      applyBtn.textContent = "Taglio…";
      try {
        await fetchJSON(`/api/downloads/${d.id}/trim`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ trim_start_seconds: trim.start, trim_end_seconds: trim.end }),
        });
        historyReloadPending = true;
        closeEditor();
      } catch (err) {
        hint.textContent = err.message;
        hint.classList.add("error");
        applyBtn.disabled = false;
        applyBtn.textContent = "Applica taglio";
      }
    });
    actions.append(cancelBtn, applyBtn);

    box.append(genreRow, genreHint, fields, hint, note, actions);
    td.appendChild(box);
    row.appendChild(td);
    tr.after(row);
    startInput.focus();
  }

  // ------------------------------------------------------------------
  // Generi & playlist
  // ------------------------------------------------------------------
  let genrePollTimer = null;

  async function loadGenres() {
    let data;
    try {
      data = await fetchJSON("/api/genres");
    } catch (err) {
      console.error(err);
      return;
    }

    const chips = $("#genre-chips");
    chips.innerHTML = "";
    data.genres.forEach((g) => {
      const chip = el("span", "genre-chip", g.genre);
      chip.appendChild(el("span", "genre-chip-count", String(g.count)));
      chips.appendChild(chip);
    });
    $("#genre-count").textContent = String(data.genres.length);

    const options = $("#genre-options");
    options.innerHTML = "";
    data.genres.forEach((g) => {
      const o = document.createElement("option");
      o.value = g.genre;
      options.appendChild(o);
    });

    $("#genre-summary").textContent = data.untagged
      ? `${data.untagged} brani in libreria senza genere.`
      : (data.genres.length ? "Tutti i brani in libreria hanno un genere." : "");

    const syncBtn = $("#playlist-sync");
    syncBtn.disabled = !data.playlists_available;
    syncBtn.title = data.playlists_available
      ? `Crea/aggiorna su Jellyfin le playlist "${data.playlist_prefix}<genere>"`
      : "Configura JELLYFIN_ENABLED, JELLYFIN_URL e JELLYFIN_API_KEY per creare le playlist";

    const b = data.backfill;
    const detectBtn = $("#genre-detect");
    detectBtn.disabled = b.running;
    if (b.running) {
      setGenreStatus(`Riconoscimento in corso: ${b.processed}/${b.total}${b.current ? ` — ${b.current}` : ""}`);
      if (!genrePollTimer) genrePollTimer = setInterval(loadGenres, 3000);
    } else {
      if (genrePollTimer) {
        clearInterval(genrePollTimer);
        genrePollTimer = null;
        setGenreStatus(`Riconoscimento completato: ${b.updated} aggiornati, ${b.not_found} non trovati` +
          (b.errors ? `, ${b.errors} errori` : "") + ".");
        loadHistory(currentHistoryStatus);
      }
    }
  }

  function setGenreStatus(msg, isError) {
    const s = $("#genre-status");
    s.textContent = msg;
    s.classList.toggle("error", !!isError);
  }

  $("#genre-detect").addEventListener("click", async () => {
    try {
      await fetchJSON("/api/genres/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: $("#genre-force").checked }),
      });
      setGenreStatus("Riconoscimento avviato…");
      if (!genrePollTimer) genrePollTimer = setInterval(loadGenres, 3000);
      loadGenres();
    } catch (err) {
      setGenreStatus(err.message, true);
    }
  });

  $("#playlist-sync").addEventListener("click", async () => {
    const btn = $("#playlist-sync");
    btn.disabled = true;
    setGenreStatus("Sincronizzazione playlist in corso…");
    try {
      const r = await fetchJSON("/api/playlists/sync", { method: "POST" });
      const parts = [`${Object.keys(r.playlists).length} playlist`];
      if (r.created.length) parts.push(`${r.created.length} create`);
      if (r.added || r.removed) parts.push(`+${r.added} / −${r.removed} brani`);
      let msg = `Playlist sincronizzate: ${parts.join(", ")}.`;
      if (r.not_indexed) msg += ` ${r.not_indexed} brani non ancora indicizzati da Jellyfin: riprova tra qualche minuto.`;
      setGenreStatus(msg);
    } catch (err) {
      setGenreStatus(err.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  // ------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------
  loadSystemInfo();
  refreshQueue();
  loadHistory("");
  loadGenres();
  connectEvents();
})();
