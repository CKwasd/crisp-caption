(() => {
  const ICE = [{ urls: 'stun:stun.l.google.com:19302' }];
  const $ = (id) => document.getElementById(id);
  const LAST_PROFILE_KEY = 'crispcaption-last-profile';
  const state = {
    wsState: 'connecting', rtcState: 'idle', audioState: 'none',
    crisp: 'stopped', profile: '', profiles: [],
    translator: 'disabled', queue: 0, latency: 0, lastError: '',
    sessionLabel: 'No active capture',
    rows: new Map(), finalSeq: new Map(),
    stats: { partial: 0, final: 0, translation: 0, error: 0 },
    settings: { showPartials: true, displayMode: 'both', autoScroll: true, fontPx: 18 },
    profileBusy: false, logLines: [], lastErrorDismissed: false,
  };
  let pc = null, stream = null, ws = null, reconnectTimer = 0;
  let vuCtx = null, vuRaf = 0;

  function nowLabel() {
    return new Date().toLocaleTimeString([], { hour12: false });
  }
  function log(line) {
    state.logLines.push(`[${nowLabel()}] ${line}`);
    if (state.logLines.length > 200) state.logLines.shift();
    $('log').textContent = state.logLines.join('\n');
    $('log').scrollTop = $('log').scrollHeight;
  }
  function dot(el, d) { el.className = 'dot' + (d ? ' ' + d : ''); }
  function crispDot(s) {
    if (s === 'running') return 'ok';
    if (s === 'starting') return 'warn';
    if (s === 'error') return 'bad';
    return '';
  }
  function translatorDot(s) {
    if (s === 'online') return 'ok';
    if (s === 'offline' || s === 'error') return 'bad';
    if (s === 'disabled') return '';
    return 'warn';
  }
  function captureDot() {
    if (state.wsState === 'error' || state.wsState === 'closed') return 'bad';
    if (state.rtcState === 'failed' || state.audioState === 'error') return 'bad';
    if (state.rtcState === 'connected' && state.audioState !== 'none') return 'ok';
    if (state.wsState === 'open' && state.rtcState === 'idle' && state.audioState === 'none') return '';
    return 'warn';
  }
  function captureText() {
    if (state.wsState === 'error' || state.wsState === 'closed') return 'bridge disconnected';
    if (state.rtcState === 'failed') return 'failed';
    if (state.rtcState === 'connected' && state.audioState !== 'none') return 'connected';
    if (state.audioState !== 'none') return state.rtcState === 'idle' ? state.audioState : state.rtcState;
    return 'idle';
  }
  function captureAllowed() {
    return !state.profileBusy && state.crisp === 'running' && state.audioState === 'none';
  }
  function renderStatus() {
    $('txt-capture').textContent = captureText();
    dot($('dot-capture'), captureDot());
    $('txt-crisp').textContent = state.crisp;
    dot($('dot-crisp'), crispDot(state.crisp));
    $('txt-profile').textContent = state.profile || 'none';
    dot($('dot-profile'), state.profile ? crispDot(state.crisp) : '');
    $('txt-translator').textContent = `${state.translator} / queue ${state.queue}`;
    dot($('dot-translator'), translatorDot(state.translator));
    const lat = state.latency;
    $('txt-latency').textContent = lat === 0 ? '0.0s' : `${lat.toFixed(1)}s`;
    $('session-label').textContent = state.sessionLabel;
    $('st-partial').textContent = state.stats.partial;
    $('st-final').textContent = state.stats.final;
    $('st-trans').textContent = state.stats.translation;
    $('st-err').textContent = state.stats.error;
    const err = (state.lastError || '').trim();
    const banner = $('error-banner');
    if (err && !state.lastErrorDismissed) {
      $('error-banner-text').textContent = err;
      banner.classList.toggle('warn', err === 'Select a profile before starting capture.');
      banner.classList.add('show');
    }
    else { banner.classList.remove('show'); banner.classList.remove('warn'); $('error-banner-text').textContent = ''; }
    $('btn-tab').disabled = !captureAllowed();
    $('btn-mic').disabled = !captureAllowed();
    $('btn-stop').disabled = state.audioState === 'none';
    $('profile-select').disabled = state.profileBusy;
    $('btn-load').disabled = state.profileBusy;
  }
  function rowKey(ev) {
    return ev.utterance_id != null ? `u:${ev.utterance_id}` : `s:${ev.seq}`;
  }
  function timeRange(row) {
    if (row.t0 == null || row.t1 == null) return '';
    return `${Number(row.t0).toFixed(1)}-${Number(row.t1).toFixed(1)}s`;
  }
  function renderTranscript() {
    const el = $('transcript');
    el.style.setProperty('--transcript-font-size', state.settings.fontPx + 'px');
    const rows = [...state.rows.values()].filter(
      (r) => state.settings.showPartials || r.kind !== 'partial'
    );
    if (!rows.length) {
      el.innerHTML = '<div class="empty">Waiting for transcript events.</div>';
      return;
    }
    el.innerHTML = rows.map((row) => {
      const cls = ['row'];
      if (row.kind === 'final') cls.push('final');
      if (row.error) cls.push('error');
      const source = state.settings.displayMode === 'translation'
        ? ''
        : `<div class="source">${esc(row.text || '')}</div>`;
      const targetText = row.error || row.translation
        || (row.kind === 'final' ? 'Translation pending' : 'Partial ASR');
      const pending = !row.translation && !row.error ? ' pending' : '';
      const metaId = row.utterance_id != null ? `utt ${row.utterance_id}` : `seq ${row.seq}`;
      const tr = timeRange(row);
      return `<article class="${cls.join(' ')}">
        <div class="meta">
          <span class="badge ${row.kind === 'final' ? 'final' : 'partial'}">${esc(row.kind || 'event')}</span>
          <span>${esc(metaId)}</span>${tr ? `<span>${esc(tr)}</span>` : ''}
        </div>
        ${source}
        <div class="target${pending}">${esc(targetText)}</div>
      </article>`;
    }).join('');
    if (state.settings.autoScroll) el.scrollTop = el.scrollHeight;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }
  function renderProfiles() {
    const sel = $('profile-select');
    const cur = state.profile;
    sel.innerHTML = '<option value="" disabled>Select profile</option>' +
      state.profiles.map((p) =>
        `<option value="${esc(p.name)}" title="${esc(p.description || p.name)}"${p.name === cur ? ' selected' : ''}>${esc(p.label || p.name)}</option>`
      ).join('');
    if (cur) sel.value = cur;
    else sel.selectedIndex = 0;
    // keep the Connect modal's profile dropdown in sync
    const conn = $('conn-profile');
    if (conn) {
      const prev = conn.value;
      conn.innerHTML = state.profiles.map((p) =>
        `<option value="${esc(p.name)}">${esc(p.label || p.name)}</option>`
      ).join('');
      if (state.profiles.some((p) => p.name === prev)) conn.value = prev;
      else if (conn.options.length) conn.value = conn.options[0].value;
    }
  }
  function paint() {
    renderStatus();
    renderTranscript();
  }

  function startVuMeter(media) {
    stopVuMeter();
    const el = $('vu-meter');
    if (!el || !media) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    try {
      vuCtx = new AudioCtx();
      const src = vuCtx.createMediaStreamSource(media);
      const analyser = vuCtx.createAnalyser();
      analyser.fftSize = 512; analyser.smoothingTimeConstant = 0.55;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const fill = $('vu-fill');
      el.classList.add('active');
      const tick = () => {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length);
        const pct = Math.min(100, Math.round((rms / 255) * 100));
        fill.style.width = (pct > 1 ? pct : 0) + '%';
        fill.classList.toggle('hot', pct > 70);
        vuRaf = requestAnimationFrame(tick);
      };
      tick();
    } catch (_) { vuCtx = null; }
  }
  function stopVuMeter() {
    if (vuRaf) { cancelAnimationFrame(vuRaf); vuRaf = 0; }
    if (vuCtx) { try { vuCtx.close(); } catch (_) {} vuCtx = null; }
    const el = $('vu-meter'); if (el) el.classList.remove('active');
    const fill = $('vu-fill'); if (fill) { fill.style.width = '0%'; fill.classList.remove('hot'); }
  }
  function stopCapture() {
    stopVuMeter();
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    if (pc) {
      const old = pc;
      pc = null;
      old.close();
    }
    state.audioState = 'none';
    state.rtcState = 'idle';
    state.sessionLabel = 'No active capture';
    paint();
  }
  async function connectStream(media, label) {
    stopCapture();
    const tracks = media.getAudioTracks();
    if (!tracks.length) {
      media.getTracks().forEach((t) => t.stop());
      throw new Error('No audio track was selected.');
    }
    stream = media;
    state.audioState = label;
    state.rtcState = 'connecting';
    state.sessionLabel = `Capturing ${label}`;
    paint();
    pc = new RTCPeerConnection({ iceServers: ICE });
    pc.onconnectionstatechange = () => {
      if (!pc) return;
      state.rtcState = pc.connectionState;
      if (state.rtcState === 'failed' || state.rtcState === 'closed') {
        log(`WebRTC ${state.rtcState}`);
        stopCapture();
      } else paint();
    };
    tracks.forEach((t) => pc.addTrack(t, media));
    media.getVideoTracks().forEach((t) => { t.enabled = false; });
    tracks[0].onended = () => { log('Audio track ended'); stopCapture(); };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const res = await fetch('/offer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sdp: offer.sdp, type: offer.type }),
    });
    if (!res.ok) {
      let detail = `POST /offer failed ${res.status}`;
      try {
        const err = await res.json();
        if (err.error) detail += `: ${err.error}`;
      } catch (_) {}
      throw new Error(detail);
    }
    const answer = await res.json();
    await pc.setRemoteDescription({ type: answer.type, sdp: answer.sdp });
    state.rtcState = 'connected';
    log(`Capture connected: ${label}`);
    startVuMeter(stream);
    paint();
  }
  async function startTab() {
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      await connectStream(s, 'tab audio');
    } catch (e) {
      log(`Capture error: ${e.message || e}`);
      stopCapture();
    }
  }
  async function startMic() {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      await connectStream(s, 'microphone');
    } catch (e) {
      log(`Capture error: ${e.message || e}`);
      stopCapture();
    }
  }

  function connectWs() {
    clearTimeout(reconnectTimer);
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    state.wsState = 'connecting';
    paint();
    ws.onopen = () => { state.wsState = 'open'; paint(); };
    ws.onerror = () => { state.wsState = 'error'; log('WebSocket error'); paint(); };
    ws.onclose = () => {
      state.wsState = 'closed';
      paint();
      reconnectTimer = setTimeout(connectWs, 1500);
    };
    ws.onmessage = (ev) => {
      try { handleEvent(JSON.parse(ev.data)); }
      catch (_) { state.stats.error += 1; log('Bad WebSocket JSON'); paint(); }
    };
  }
  function handleEvent(msg) {
    if (msg.type === 'transcript') {
      const key = rowKey(msg);
      state.rows.set(key, { ...(state.rows.get(key) || {}), ...msg, key, error: '' });
      if (msg.kind === 'final' && msg.seq != null) state.finalSeq.set(msg.seq, key);
      state.stats[msg.kind === 'partial' ? 'partial' : 'final'] += 1;
    } else if (msg.type === 'translation') {
      const key = state.finalSeq.get(msg.seq) || `s:${msg.seq}`;
      const row = state.rows.get(key) || { key, seq: msg.seq, kind: 'final', text: '' };
      state.rows.set(key, { ...row, translation: msg.text || '', error: '' });
      state.stats.translation += 1;
    } else if (msg.type === 'translation_error') {
      const key = state.finalSeq.get(msg.seq) || `s:${msg.seq}`;
      const row = state.rows.get(key) || { key, seq: msg.seq, kind: 'final', text: '' };
      const message = msg.message || 'Translation failed';
      state.rows.set(key, { ...row, error: message });
      state.stats.error += 1;
      log(message);
    } else if (msg.type === 'health') {
      if (state.crispEpoch == null) state.crispEpoch = msg.crisp_epoch;
      else if (msg.crisp_epoch != null && msg.crisp_epoch !== state.crispEpoch) {
        state.crispEpoch = msg.crisp_epoch;
        state.rows.clear();
        state.finalSeq.clear();
      }
      state.translator = msg.translator_status || 'unknown';
      state.queue = Number(msg.translation_queue_size) || 0;
      state.profile = msg.active_profile || state.profile;
      state.crisp = msg.crisp_status || state.crisp;
      state.latency = Number(msg.latency_sec) || 0;
      const err = (msg.last_error || '').trim();
      if (err && err !== state.lastError) { state.lastErrorDismissed = false; log(err); }
      state.lastError = err;
      renderProfiles();
    }
    paint();
  }

  async function loadProfiles() {
    try {
      const res = await fetch('/profiles');
      if (!res.ok) throw new Error(`GET /profiles failed ${res.status}`);
      const data = await res.json();
      state.profiles = data.profiles || [];
      state.profile = '';
      state.crisp = data.crisp_status || 'stopped';
      renderProfiles();
      paint();
    } catch (e) {
      log(`Profile list error: ${e.message || e}`);
    }
  }
  async function changeProfile(name) {
    if (!name || state.profileBusy) return;
    const capturing = state.audioState !== 'none';
    if (capturing) {
      if (state.rows.size > 0) {
        const ok = await askConfirm(
          'Switch profile now?',
          'This will stop the current capture. Your transcript will be kept.'
        );
        if (!ok) { $('profile-select').value = state.profile || ''; return; }
      } else {
        log('Switching profile: capture stopped');
      }
    }
    state.profileBusy = true;
    busy($('btn-load'), true);
    stopCapture();
    paint();
    try {
      const res = await fetch('/profiles/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        let detail = `POST /profiles/select failed ${res.status}`;
        try {
          const data = await res.json();
          if (data.error) detail += `: ${data.error}`;
        } catch (_) {}
        throw new Error(detail);
      }
      const data = await res.json();
      state.profiles = data.profiles || state.profiles;
      state.profile = data.active || name;
      state.crisp = data.crisp_status || state.crisp;
      localStorage.setItem(LAST_PROFILE_KEY, name);
      log(`Profile selected: ${state.profile}`);
      renderProfiles();
      toast(`Switched to profile "${state.profile}"`);
    } catch (e) {
      log(`Profile switch error: ${e.message || e}`);
      toast(e.message || 'Profile switch failed', 'warn');
      await loadProfiles();
    } finally {
      state.profileBusy = false;
      busy($('btn-load'), false);
      paint();
    }
  }
  function clearTranscript() {
    state.rows.clear();
    state.finalSeq.clear();
    state.stats = { partial: 0, final: 0, translation: 0, error: 0 };
    log('Transcript cleared');
    paint();
  }
  async function startOverlay() {
    busy($('btn-overlay'), true);
    try {
      const res = await fetch('/overlay/start', { method: 'POST' });
      if (!res.ok) throw new Error((await res.text()) || `Overlay start failed (${res.status})`);
      log('Subtitle overlay started');
      $('btn-overlay-stop').disabled = false;
      toast('Subtitle overlay started');
    } catch (e) {
      log(`Overlay error: ${e.message || e}`);
      toast(e.message || 'Overlay start failed', 'warn');
    } finally {
      busy($('btn-overlay'), false);
    }
  }
  async function stopOverlay() {
    busy($('btn-overlay-stop'), true);
    try {
      const res = await fetch('/overlay/stop', { method: 'POST' });
      if (!res.ok) throw new Error(`Overlay stop failed (${res.status})`);
      log('Subtitle overlay stopped');
      $('btn-overlay-stop').disabled = true;
      toast('Subtitle overlay stopped');
    } catch (e) {
      log(`Overlay error: ${e.message || e}`);
      toast(e.message || 'Overlay stop failed', 'warn');
    } finally {
      busy($('btn-overlay-stop'), false);
    }
  }
  async function syncOverlayStatus() {
    try {
      const res = await fetch('/overlay/status');
      if (!res.ok) return;
      const data = await res.json();
      $('btn-overlay-stop').disabled = !data.running;
    } catch (_) {}
  }
  function vttTime(sec) {
    const v = Math.max(0, Number(sec) || 0);
    const h = Math.floor(v / 3600);
    const m = Math.floor((v % 3600) / 60);
    const s = Math.floor(v % 60);
    const ms = Math.floor((v - Math.floor(v)) * 1000);
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${String(ms).padStart(3,'0')}`;
  }
  let toastTimer = 0;
  function toast(msg, kind) {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'toast' + (kind === 'warn' ? ' warn' : '');
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
  }
  function busy(btn, on) { if (btn) btn.classList.toggle('busy', !!on); }

  function srtTime(sec) {
    const v = Math.max(0, Number(sec) || 0);
    const h = Math.floor(v / 3600);
    const m = Math.floor((v % 3600) / 60);
    const s = Math.floor(v % 60);
    const ms = Math.floor((v - Math.floor(v)) * 1000);
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')},${String(ms).padStart(3,'0')}`;
  }
  function openExportModal() {
    $('export-modal').hidden = false;
    const f = $('export-filename');
    f.value = 'crispasr-subtitles';
    f.focus(); f.select();
  }
  function closeExportModal() { $('export-modal').hidden = true; }

  function doExport() {
    const format = $('export-format').value;
    const base = ($('export-filename').value.trim() || 'crispasr-subtitles')
      .replace(/[\\/:*?"<>|]/g, '_');
    const finals = [...state.rows.values()].filter((r) => r.kind === 'final');
    const entries = finals
      .map((row) => {
        const start = row.t0 != null ? Number(row.t0) : -1;
        const end = row.t1 != null ? Number(row.t1) : -1;
        let text;
        if (state.settings.displayMode === 'translation') text = (row.error || row.translation || '').trim();
        else text = [row.text, row.error || row.translation].filter(Boolean).join('\n').trim();
        return { start, end, text };
      })
      .filter((e) => e.text);
    let content = '';
    if (format === 'txt') {
      content = entries.map((e) => e.text).join('\n\n') + '\n';
    } else {
      const time = format === 'vtt' ? vttTime : srtTime;
      const cues = entries.map((e, i) => {
        const start = e.start >= 0 ? e.start : i * 3;
        const end = e.end >= 0 ? e.end : start + 3;
        const t = `${time(start)} --> ${time(Math.max(end, start + 0.5))}`;
        return format === 'vtt' ? `${t}\n${e.text}` : `${i + 1}\n${t}\n${e.text}`;
      });
      content = format === 'vtt'
        ? `WEBVTT\n\n${cues.join('\n\n')}\n`
        : `${cues.join('\n\n')}\n`;
    }
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${base}.${format}`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    closeExportModal();
    toast(`Exported ${entries.length} ${entries.length === 1 ? 'cue' : 'cues'} as .${format}`);
  }

  let confirmResolve = null;
  const confirmModal = $('confirm-modal');
  function askConfirm(text, sub) {
    $('confirm-text').textContent = text;
    $('confirm-sub').textContent = sub || '';
    confirmModal.hidden = false;
    return new Promise((res) => { confirmResolve = res; });
  }

  // ---- Connection modal ----
  const connModal = $('connect-modal');
  const connProfile = $('conn-profile');
  function fillConnProfile() {
    connProfile.innerHTML = '';
    (state.profiles || []).forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.name;
      opt.textContent = p.label || p.name;
      connProfile.appendChild(opt);
    });
    if (connProfile.options.length && ![...connProfile.options].some((o) => o.value === connProfile.value)) {
      connProfile.value = connProfile.options[0].value;
    }
  }
  function setFieldDisabled(sel, disabled) {
    document.querySelectorAll(sel).forEach((label) => {
      const input = label.querySelector('input');
      label.classList.toggle('conn-disabled', disabled);
      if (input) input.disabled = disabled;
    });
  }
  function syncConnFields() {
    const asrRemote = $('conn-asr-mode').value === 'remote';
    setFieldDisabled('.conn-asr-remote', !asrRemote);
    const transRemote = $('conn-trans-mode').value !== 'local';
    setFieldDisabled('.conn-trans-remote', !transRemote);
  }
  function openConnModal() {
    fillConnProfile();
    syncConnFields();
    connModal.hidden = false;
  }
  function closeConnModal() {
    connModal.hidden = true;
  }
  async function applyConnection() {
    const name = connProfile.value;
    if (!name) { log('Connect: no profile selected'); return; }
    const asrMode = $('conn-asr-mode').value;
    const transMode = $('conn-trans-mode').value;
    const asrSource = asrMode === 'remote'
      ? { mode: 'remote', url: $('conn-asr-url').value.trim(), key: $('conn-asr-key').value.trim() }
      : { mode: 'local' };
    const translateSource = transMode === 'local'
      ? { mode: 'local' }
      : { mode: 'remote', url: $('conn-trans-url').value.trim(), key: $('conn-trans-key').value.trim() };
    closeConnModal();
    state.profileBusy = true;
    busy($('btn-connect'), true);
    stopCapture();
    paint();
    try {
      const res = await fetch('/profiles/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, asr_source: asrSource, translate_source: translateSource }),
      });
      if (!res.ok) {
        let detail = `POST /profiles/select failed ${res.status}`;
        try { const d = await res.json(); if (d.error) detail += `: ${d.error}`; } catch (_) {}
        throw new Error(detail);
      }
      const data = await res.json();
      state.profile = name;
      localStorage.setItem(LAST_PROFILE_KEY, name);
      log(`Connection applied: ${name} (ASR=${asrMode}, translate=${transMode})`);
      renderProfiles();
    } catch (e) {
      log(`Connect error: ${e.message || e}`);
      await loadProfiles();
    } finally {
      state.profileBusy = false;
      busy($('btn-connect'), false);
      paint();
    }
  }

  // ---- Event bindings ----
  $('btn-tab').onclick = startTab;
  $('btn-mic').onclick = startMic;
  $('btn-stop').onclick = stopCapture;
  $('btn-clear').onclick = clearTranscript;
  $('btn-overlay').onclick = startOverlay;
  $('btn-overlay-stop').onclick = stopOverlay;
  $('btn-export').onclick = openExportModal;
  $('btn-export-apply').onclick = doExport;
  $('btn-export-cancel').onclick = closeExportModal;
  $('export-modal').addEventListener('click', (e) => {
    if (e.target === $('export-modal')) closeExportModal();
  });
  $('btn-confirm-ok').onclick = () => {
    const r = confirmResolve; confirmResolve = null;
    confirmModal.hidden = true; if (r) r(true);
  };
  $('btn-confirm-cancel').onclick = () => {
    const r = confirmResolve; confirmResolve = null;
    confirmModal.hidden = true; if (r) r(false);
  };
  confirmModal.addEventListener('click', (e) => {
    if (e.target === confirmModal) {
      const r = confirmResolve; confirmResolve = null;
      confirmModal.hidden = true; if (r) r(false);
    }
  });
  $('btn-connect').onclick = openConnModal;
  $('btn-conn-apply').onclick = applyConnection;
  $('btn-conn-cancel').onclick = closeConnModal;
  connModal.addEventListener('click', (e) => {
    if (e.target === connModal) closeConnModal();
  });
  $('conn-asr-mode').onchange = syncConnFields;
  $('conn-trans-mode').onchange = syncConnFields;
  $('btn-diag').onclick = () => window.open('/diagnostics', '_blank');
  $('error-banner-close').onclick = () => {
    state.lastErrorDismissed = true;
    paint();
  };
  $('btn-settings').onclick = () => $('settings').classList.toggle('open');
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.settings-wrap')) $('settings').classList.remove('open');
  });
  $('profile-select').onchange = (e) => changeProfile(e.target.value);
  $('btn-load').onclick = () => changeProfile($('profile-select').value);
  $('set-partials').onchange = (e) => { state.settings.showPartials = e.target.checked; paint(); };
  $('set-scroll').onchange = (e) => { state.settings.autoScroll = e.target.checked; };
  $('set-display').onchange = (e) => { state.settings.displayMode = e.target.value; paint(); };
  $('set-font').oninput = (e) => {
    state.settings.fontPx = Number(e.target.value);
    $('set-font-out').textContent = state.settings.fontPx + 'px';
    paint();
  };
  window.addEventListener('beforeunload', () => { stopCapture(); ws && ws.close(); });

  connectWs();
  loadProfiles();
  syncOverlayStatus();
  paint();
})();
