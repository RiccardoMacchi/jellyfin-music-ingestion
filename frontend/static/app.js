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
    $("#f-genre").value = "";
    $("#f-composer").value = "";
    $("#f-compilation").checked = false;
    $("#preview-panel").hidden = false;
    $("#preview-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  $("#preview-cancel").addEventListener("click", () => {
    $("#preview-panel").hidden = true;
    lastAnalyzed = null;
  });

  $("#preview-download").addEventListener("click", async () => {
    if (!lastAnalyzed) return;
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
          composer: $("#f-composer").value.trim(),
          is_compilation: $("#f-compilation").checked,
          thumbnail_url: lastAnalyzed.thumbnail_url,
          duration_seconds: lastAnalyzed.duration_seconds,
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
        renderQueue(data.downloads || []);
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

  async function loadHistory(status) {
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
      if (d.artist) tdTrack.appendChild(el("span", "hartist", d.artist));
      if (d.error) tdTrack.appendChild(el("div", "herror", d.error));

      const tdAlbum = document.createElement("td");
      tdAlbum.textContent = d.album || "—";

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
      const delBtn = el("button", "btn btn-ghost btn-sm", "Elimina");
      delBtn.addEventListener("click", async () => {
        await fetchJSON(`/api/downloads/${d.id}`, { method: "DELETE" });
        loadHistory(currentHistoryStatus);
      });
      tdActions.appendChild(delBtn);

      tr.append(tdTrack, tdAlbum, tdStatus, tdActions);
      body.appendChild(tr);
    });
  }

  // ------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------
  loadSystemInfo();
  refreshQueue();
  loadHistory("");
  connectEvents();
})();
