from __future__ import annotations


def qt_overlay_html(ws_url: str, font_px: int) -> str:
    return subtitle_overlay_html(
        ws_url=ws_url,
        body_css="align-items: end; display: grid; padding: 28px 42px 34px;",
        main_font=f"{font_px}px",
        partial_font=f"{max(16, round(font_px * 0.72))}px",
        main_weight="750",
        main_line_height="1.32",
        partial_weight="600",
        partial_line_height="1.35",
        partial_margin_top="8px",
        status_font="16px",
        status_weight="650",
        initial_status="Connecting to CrispASR...",
        connected_status="CrispASR connected",
        show_connected_briefly=True,
    )


def obs_overlay_html(ws_url: str) -> str:
    return subtitle_overlay_html(
        ws_url=ws_url,
        body_css="align-items: end; box-sizing: border-box; display: grid; padding: 0 7vw 9vh;",
        main_font="clamp(28px, 4.2vw, 58px)",
        partial_font="clamp(20px, 2.8vw, 38px)",
        main_weight="780",
        main_line_height="1.28",
        partial_weight="650",
        partial_line_height="1.32",
        partial_margin_top="10px",
        status_font="22px",
        status_weight="700",
        initial_status="Waiting for subtitles",
        connected_status="Waiting for subtitles",
        show_connected_briefly=False,
    )


def subtitle_overlay_html(
    *,
    ws_url: str,
    body_css: str,
    main_font: str,
    partial_font: str,
    main_weight: str,
    main_line_height: str,
    partial_weight: str,
    partial_line_height: str,
    partial_margin_top: str,
    status_font: str,
    status_weight: str,
    initial_status: str,
    connected_status: str,
    show_connected_briefly: bool,
) -> str:
    render_delay_ms = 650 if show_connected_briefly else 0
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
#subtitle {{
  text-align: center;
  text-shadow: 0 2px 4px #000, 0 0 14px #000, 0 0 28px #000;
  width: 100%;
}}
#main {{
  font-size: {main_font};
  font-weight: {main_weight};
  line-height: {main_line_height};
  overflow-wrap: anywhere;
}}
#partial {{
  color: rgba(235, 244, 255, .74);
  display: none;
  font-size: {partial_font};
  font-style: italic;
  font-weight: {partial_weight};
  line-height: {partial_line_height};
  margin-top: {partial_margin_top};
  overflow-wrap: anywhere;
}}
#status {{
  color: rgba(235, 244, 255, .72);
  font-size: {status_font};
  font-weight: {status_weight};
}}
</style>
</head>
<body>
<main id="subtitle">
  <div id="status">{initial_status}</div>
  <div id="main"></div>
  <div id="partial"></div>
</main>
<script>
(() => {{
  const wsUrl = {ws_url!r};
  const status = document.getElementById('status');
  const mainLine = document.getElementById('main');
  const partialLine = document.getElementById('partial');
  const rowsByKey = new Map();
  const finalSeqToKey = new Map();

  function rowKey(ev) {{
    return ev.utterance_id != null ? `u:${{ev.utterance_id}}` : `s:${{ev.seq}}`;
  }}

  function render() {{
    const rows = Array.from(rowsByKey.values());
    const finalRow = rows.slice().reverse().find((row) => row.kind === 'final');
    const finalId = finalRow?.utterance_id ?? null;
    const partialRow = rows.slice().reverse().find((row) =>
      row.kind === 'partial' &&
      row.text &&
      (finalId == null || row.utterance_id == null || row.utterance_id !== finalId)
    );

    const main = finalRow?.translation || finalRow?.text || '';
    const partial = partialRow?.text || '';
    status.style.display = main || partial ? 'none' : 'block';
    status.textContent = 'Waiting for subtitles';
    mainLine.textContent = main || partial || '';
    partialLine.textContent = main && partial ? partial : '';
    partialLine.style.display = main && partial ? 'block' : 'none';
  }}

  function connect() {{
    rowsByKey.clear();
    finalSeqToKey.clear();
    status.style.display = 'block';
    status.textContent = {initial_status!r};
    const ws = new WebSocket(wsUrl);
    window.__crispasrWs = ws;

    ws.onopen = () => {{
      status.textContent = {connected_status!r};
      setTimeout(render, {render_delay_ms});
    }};

    ws.onmessage = (event) => {{
      const msg = JSON.parse(event.data);
      if (msg.type === 'transcript') {{
        const key = rowKey(msg);
        rowsByKey.set(key, {{ ...(rowsByKey.get(key) || {{}}), ...msg, key }});
        if (msg.kind === 'final' && msg.seq != null) finalSeqToKey.set(msg.seq, key);
        render();
      }} else if (msg.type === 'translation') {{
        const key = finalSeqToKey.get(msg.seq) || `s:${{msg.seq}}`;
        rowsByKey.set(key, {{
          ...(rowsByKey.get(key) || {{ key, kind: 'final' }}),
          translation: msg.text || ''
        }});
        render();
      }} else if (msg.type === 'translation_error') {{
        const key = finalSeqToKey.get(msg.seq) || `s:${{msg.seq}}`;
        rowsByKey.set(key, {{
          ...(rowsByKey.get(key) || {{ key, kind: 'final' }}),
          translation: msg.message || 'Translation failed'
        }});
        render();
      }}
    }};

    ws.onerror = () => {{
      status.style.display = 'block';
      status.textContent = 'CrispASR WebSocket error';
    }};

    ws.onclose = () => {{
      status.style.display = 'block';
      status.textContent = 'CrispASR disconnected; reconnecting...';
      setTimeout(connect, 1500);
    }};
  }}

  window.addEventListener('beforeunload', () => {{
    if (window.__crispasrWs && window.__crispasrWs.readyState < 2) {{
      window.__crispasrWs.close(1000, 'overlay closed');
    }}
  }});

  connect();
}})();
</script>
</body>
</html>"""
