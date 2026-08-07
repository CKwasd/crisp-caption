from __future__ import annotations


def qt_overlay_html(
    ws_url: str,
    font_px: int,
    *,
    mode: str = "both",
    hold_sec: float = 2.0,
    fade_sec: float = 4.0,
) -> str:
    return subtitle_overlay_html(
        ws_url=ws_url,
        body_css="align-items: end; display: grid; padding: 28px 42px 34px;",
        main_font=f"{font_px}px",
        partial_font=f"{max(16, round(font_px * 0.72))}px",
        trans_font=f"{max(16, round(font_px * 0.88))}px",
        main_weight="750",
        main_line_height="1.32",
        partial_weight="600",
        partial_line_height="1.35",
        partial_margin_top="8px",
        trans_weight="680",
        trans_margin_top="6px",
        status_font="16px",
        status_weight="650",
        initial_status="Connecting to CrispASR...",
        connected_status="CrispASR connected",
        show_connected_briefly=True,
        mode=mode,
        hold_sec=hold_sec,
        fade_sec=fade_sec,
    )


def obs_overlay_html(
    ws_url: str,
    *,
    mode: str = "both",
    hold_sec: float = 2.0,
    fade_sec: float = 4.0,
    font: float = 1.0,
    pos: str = "bottom",
    demo: bool = False,
    interj_len: int = 3,
    interj_ratio: float = 0.4,
    interj_gap_sec: float = 2.0,
) -> str:
    body_css = (
        "align-items: start; display: grid; padding: 9vh 7vw 0;"
        if pos == "top"
        else "align-items: end; display: grid; padding: 0 7vw 9vh;"
    )
    return subtitle_overlay_html(
        ws_url=ws_url,
        body_css=body_css,
        main_font=f"clamp({28 * font:.0f}px, {4.2 * font:.2f}vw, {58 * font:.0f}px)",
        partial_font=f"clamp({20 * font:.0f}px, {2.8 * font:.2f}vw, {38 * font:.0f}px)",
        trans_font=f"clamp({24 * font:.0f}px, {3.4 * font:.2f}vw, {48 * font:.0f}px)",
        main_weight="780",
        main_line_height="1.28",
        partial_weight="650",
        partial_line_height="1.32",
        partial_margin_top="10px",
        trans_weight="700",
        trans_margin_top="8px",
        status_font="22px",
        status_weight="700",
        initial_status="Waiting for subtitles",
        connected_status="Waiting for subtitles",
        show_connected_briefly=False,
        mode=mode,
        hold_sec=hold_sec,
        fade_sec=fade_sec,
        demo=demo,
        interj_len=interj_len,
        interj_ratio=interj_ratio,
        interj_gap_sec=interj_gap_sec,
    )


def subtitle_overlay_html(
    *,
    ws_url: str,
    body_css: str,
    main_font: str,
    partial_font: str,
    trans_font: str,
    main_weight: str,
    main_line_height: str,
    partial_weight: str,
    partial_line_height: str,
    partial_margin_top: str,
    trans_weight: str,
    trans_margin_top: str,
    status_font: str,
    status_weight: str,
    initial_status: str,
    connected_status: str,
    show_connected_briefly: bool,
    mode: str,
    hold_sec: float,
    fade_sec: float,
    demo: bool = False,
    interj_len: int = 3,
    interj_ratio: float = 0.4,
    interj_gap_sec: float = 2.0,
) -> str:
    render_delay_ms = 650 if show_connected_briefly else 0
    hold_ms = round(hold_sec * 1000)
    fade_ms = round(fade_sec * 1000)
    interj_gap_ms = round(interj_gap_sec * 1000)
    demo_js = "true" if demo else "false"
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* {{
  box-sizing: border-box;
}}
html,
body {{
  background: transparent;
  color: #fff;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  height: 100%;
  margin: 0;
  overflow: hidden;
}}
body {{
  {body_css}
}}
#status {{
  color: rgba(235, 244, 255, .72);
  font-size: {status_font};
  font-weight: {status_weight};
  text-align: center;
  text-shadow: 0 2px 4px #000, 0 0 14px #000;
  width: 100%;
}}
#subtitle {{
  opacity: 1;
  text-align: center;
  text-shadow: 0 2px 4px #000, 0 0 14px #000, 0 0 28px #000;
  transition: opacity 300ms ease;
  width: 100%;
}}
#subtitle.hidden {{
  opacity: 0;
}}
#main {{
  display: -webkit-box;
  font-size: {main_font};
  font-weight: {main_weight};
  line-height: {main_line_height};
  min-height: {main_line_height}em;
  overflow: hidden;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}}
#trans {{
  color: rgba(235, 244, 255, .92);
  font-size: {trans_font};
  font-weight: {trans_weight};
  line-height: 1.3;
  min-height: 1.3em;
  margin-top: {trans_margin_top};
  overflow-wrap: anywhere;
}}
#partial {{
  color: rgba(235, 244, 255, .74);
  font-size: {partial_font};
  font-style: italic;
  font-weight: {partial_weight};
  line-height: {partial_line_height};
  min-height: {partial_line_height}em;
  margin-top: {partial_margin_top};
  overflow-wrap: anywhere;
}}
@keyframes lineIn {{
  from {{ opacity: 0; }}
  to {{ opacity: 1; }}
}}
@keyframes partialIn {{
  from {{ opacity: .3; }}
  to {{ opacity: 1; }}
}}
</style>
</head>
<body>
<div id="status">{initial_status}</div>
<main id="subtitle">
  <div id="trans"></div>
  <div id="main"></div>
  <div id="partial"></div>
</main>
<script>
(() => {{
  const opts = {{
    wsUrl: {ws_url!r},
    initialStatus: {initial_status!r},
    connectedStatus: {connected_status!r},
    renderDelayMs: {render_delay_ms},
    mode: {mode!r},
    holdMs: {hold_ms},
    fadeMs: {fade_ms},
    demo: {demo_js},
    interjLen: {interj_len},
    interjRatio: {interj_ratio},
    interjGapMs: {interj_gap_ms},
  }};
  const status = document.getElementById('status');
  const mainLine = document.getElementById('main');
  const transLine = document.getElementById('trans');
  const partialLine = document.getElementById('partial');
  const subtitleEl = document.getElementById('subtitle');
  const rowsByKey = new Map();
  const finalSeqToKey = new Map();
  const MAX_ROWS = 100;
  const DEMO_LINES = [
    'これはサンプル字幕です',
    'This is a sample subtitle',
    '字幕は表示時間と大きさを調整できます',
  ];
  let lastEpoch = null;
  let mainShownAt = 0;
  let pendingMain = null;
  let swapTimer = 0, fadeTimer = 0, demoTimer = 0;
  let visible = true;
  let demoIdx = 0;
  let displayed = {{ main: '', trans: '', partial: '', sourceKey: null }};

  function rowKey(ev) {{
    return ev.utterance_id != null ? `u:${{ev.utterance_id}}` : `s:${{ev.seq}}`;
  }}

  function isInterj(F, P) {{
    const lenF = F.text.length;
    if (lenF > opts.interjLen) return false;
    if (lenF / Math.max(P.text.length, 1) >= opts.interjRatio) return false;
    if (typeof F.t1 === 'number' && typeof P.t1 === 'number' && (F.t1 - P.t1) * 1000 >= opts.interjGapMs) return false;
    return true;
  }}

  function desired() {{
    const rows = Array.from(rowsByKey.values());
    const finals = rows.filter((r) => r.kind === 'final' && r.text);
    let base = null;
    const merged = [];
    for (let i = 0; i < finals.length; i++) {{
      const f = finals[i];
      if (base === null) {{
        base = f;
        continue;
      }}
      if (isInterj(f, base)) {{
        merged.push(f);
        continue;
      }}
      base = f;
      merged.length = 0;
    }}
    const baseId = base?.utterance_id ?? null;
    const partialRow = rows.slice().reverse().find((row) =>
      row.kind === 'partial' &&
      row.text &&
      (baseId == null || row.utterance_id == null || row.utterance_id !== baseId)
    );
    let main = '';
    let trans = '';
    if (base) {{
      main = base.text + merged.map((m) => ' ' + m.text).join('');
      trans = (base.translation || '') + merged.map((m) => (m.translation ? ' ' + m.translation : '')).join('');
    }} else if (partialRow) {{
      main = partialRow.text;
    }}
    return {{
      main,
      trans,
      partial: base ? (partialRow?.text || '') : '',
      sourceKey: (base || partialRow)?.key ?? null,
      partialMode: base === null && !!partialRow,
    }};
  }}

  function demoDesired() {{
    const line = DEMO_LINES[demoIdx % DEMO_LINES.length];
    demoIdx += 1;
    return {{ main: line, trans: '', partial: '', sourceKey: 'demo', partialMode: false }};
  }}

  function prune() {{
    while (rowsByKey.size > MAX_ROWS) {{
      rowsByKey.delete(rowsByKey.keys().next().value);
    }}
    while (finalSeqToKey.size > MAX_ROWS) {{
      finalSeqToKey.delete(finalSeqToKey.keys().next().value);
    }}
  }}

  function commit() {{
    prune();
    const d = opts.demo ? demoDesired() : desired();
    const mainChanged = d.main !== displayed.main || d.trans !== displayed.trans;
    const partialChanged = d.partial !== displayed.partial;
    if (!mainChanged && !partialChanged) return;

    if (pendingMain && d.sourceKey === pendingMain.sourceKey) {{
      pendingMain = {{ main: d.main, trans: d.trans, sourceKey: d.sourceKey }};
      if (partialChanged) {{
        applyPartial({{ main: displayed.main, trans: displayed.trans, partial: d.partial, sourceKey: displayed.sourceKey }});
      }}
      return;
    }}

    if (mainChanged && d.sourceKey === displayed.sourceKey) {{
      clearTimeout(swapTimer);
      pendingMain = null;
      apply(d, !d.partialMode, partialChanged);
      return;
    }}

    if (!mainChanged) {{
      applyPartial(d);
      return;
    }}

    const now = Date.now();
    if (mainChanged && mainShownAt > 0 && now - mainShownAt < opts.holdMs) {{
      pendingMain = {{ main: d.main, trans: d.trans, sourceKey: d.sourceKey }};
      clearTimeout(swapTimer);
      swapTimer = setTimeout(() => {{
        const fresh = opts.demo ? demoDesired() : desired();
        apply({{ main: pendingMain.main, trans: pendingMain.trans, partial: fresh.partial, sourceKey: pendingMain.sourceKey }}, true, partialChanged);
      }}, opts.holdMs - (now - mainShownAt));
      return;
    }}

    clearTimeout(swapTimer);
    pendingMain = null;
    apply(d, true, partialChanged);
  }}

  function applyPartial(d) {{
    if (displayed.main || displayed.trans) {{
      partialLine.textContent = d.partial;
      partialLine.style.visibility = d.partial ? 'visible' : 'hidden';
      if (d.partial) {{
        partialLine.style.animation = 'none';
        void partialLine.offsetWidth;
        partialLine.style.animation = 'partialIn 120ms ease';
      }}
      displayed = {{ ...displayed, partial: d.partial }};
      restartFade();
      return;
    }}
    apply(d, false, true);
  }}

  function apply(d, animateMain, animatePartial) {{
    if (d.main !== displayed.main || d.trans !== displayed.trans) {{
      mainShownAt = Date.now();
    }}
    displayed = d;
    const showMain = !!d.main;
    const showTrans = !!d.trans;
    const hasPartial = !!d.partial;
    let primary = mainLine;
    let primaryText = d.main;
    if (opts.mode === 'trans') {{
      primary = transLine;
      primaryText = d.trans || d.main;
      transLine.textContent = primaryText;
      transLine.style.visibility = showMain || showTrans ? 'visible' : 'hidden';
      mainLine.style.visibility = 'hidden';
    }} else if (opts.mode === 'both') {{
      mainLine.textContent = d.main;
      transLine.textContent = d.trans;
      mainLine.style.visibility = showMain ? 'visible' : 'hidden';
      transLine.style.visibility = showTrans ? 'visible' : 'hidden';
    }} else {{
      mainLine.textContent = d.main;
      transLine.textContent = '';
      mainLine.style.visibility = showMain ? 'visible' : 'hidden';
      transLine.style.visibility = 'hidden';
    }}
    partialLine.textContent = d.partial;
    partialLine.style.visibility = hasPartial ? 'visible' : 'hidden';
    status.style.display = showMain || showTrans || hasPartial ? 'none' : 'block';
    if (animateMain && primaryText) {{
      primary.style.animation = 'none';
      void primary.offsetWidth;
      primary.style.animation = 'lineIn 200ms ease';
    }}
    if (animatePartial && hasPartial) {{
      partialLine.style.animation = 'none';
      void partialLine.offsetWidth;
      partialLine.style.animation = 'partialIn 120ms ease';
    }}
    showSubtitle(!!(showMain || showTrans || hasPartial));
    restartFade();
  }}

  function showSubtitle(show) {{
    if (show === visible) return;
    visible = show;
    subtitleEl.classList.toggle('hidden', !show);
  }}

  function restartFade() {{
    clearTimeout(fadeTimer);
    if (opts.fadeMs <= 0) return;
    if (!displayed.main && !displayed.trans && !displayed.partial) return;
    showSubtitle(true);
    fadeTimer = setTimeout(() => showSubtitle(false), opts.fadeMs);
  }}

  function connect() {{
    rowsByKey.clear();
    finalSeqToKey.clear();
    status.style.display = 'block';
    status.textContent = opts.initialStatus;
    showSubtitle(false);
    const ws = new WebSocket(opts.wsUrl);
    window.__crispasrWs = ws;

    ws.onopen = () => {{
      status.textContent = opts.connectedStatus;
      setTimeout(commit, opts.renderDelayMs);
    }};

    ws.onmessage = (event) => {{
      const msg = JSON.parse(event.data);
      if (msg.type === 'transcript') {{
        const key = rowKey(msg);
        rowsByKey.set(key, {{ ...(rowsByKey.get(key) || {{}}), ...msg, key }});
        if (msg.kind === 'final' && msg.seq != null) finalSeqToKey.set(msg.seq, key);
        commit();
      }} else if (msg.type === 'translation') {{
        const key = finalSeqToKey.get(msg.seq) || `s:${{msg.seq}}`;
        rowsByKey.set(key, {{
          ...(rowsByKey.get(key) || {{ key, kind: 'final' }}),
          translation: msg.text || ''
        }});
        commit();
      }} else if (msg.type === 'translation_error') {{
        const key = finalSeqToKey.get(msg.seq) || `s:${{msg.seq}}`;
        rowsByKey.set(key, {{
          ...(rowsByKey.get(key) || {{ key, kind: 'final' }}),
          translation: msg.message || 'Translation failed'
        }});
        commit();
      }} else if (msg.type === 'health') {{
        if (msg.crisp_epoch != null && msg.crisp_epoch !== lastEpoch) {{
          lastEpoch = msg.crisp_epoch;
          rowsByKey.clear();
          finalSeqToKey.clear();
          commit();
        }}
      }}
    }};

    ws.onerror = () => {{
      status.style.display = 'block';
      status.textContent = 'CrispASR WebSocket error';
    }};

    ws.onclose = () => {{
      status.style.display = 'block';
      status.textContent = 'CrispASR disconnected; reconnecting...';
      showSubtitle(false);
      setTimeout(connect, 1500);
    }};
  }}

  window.addEventListener('beforeunload', () => {{
    if (window.__crispasrWs && window.__crispasrWs.readyState < 2) {{
      window.__crispasrWs.close(1000, 'overlay closed');
    }}
  }});

  if (opts.demo) {{
    demoTimer = setInterval(commit, 3000);
    commit();
  }} else {{
    connect();
  }}
}})();
</script>
</body>
</html>"""
