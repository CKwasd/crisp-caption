const fs = require('fs');
const vm = require('vm');

let timers = [];
let now = 0;
let els = {};

function el() {
  const style = { _val: '', _sets: 0 };
  Object.defineProperty(style, 'animation', {
    get() { return this._val; },
    set(v) { this._val = v; this._sets += 1; },
  });
  return {
    style,
    textContent: '',
    offsetWidth: 0,
    classList: { _hidden: false, toggle(c, force) { this._hidden = force === undefined ? !this._hidden : !!force; } },
  };
}

function setup(html) {
  timers = [];
  now = 0;
  els = { status: el(), main: el(), trans: el(), partial: el(), subtitle: el() };
  globalThis.Date.now = () => now;
  globalThis.setTimeout = (fn, ms) => { const id = timers.length; timers.push({ id, at: now + (ms || 0), fn }); return id; };
  globalThis.clearTimeout = (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); };
  globalThis.setInterval = () => 0;
  globalThis.clearInterval = () => {};
  globalThis.document = { getElementById: (id) => els[id] };
  globalThis.window = { addEventListener: () => {}, __crispasrWs: null };
  class FakeWS { constructor(url) { this.readyState = 0; FakeWS.last = this; globalThis.window.__crispasrWs = this; } close() {} }
  globalThis.WebSocket = FakeWS;
  vm.runInThisContext(html);
  return FakeWS;
}

function fire(WS, data) { WS.last.onmessage({ data: JSON.stringify(data) }); }

function advance(ms) {
  const end = now + ms;
  for (;;) {
    const due = timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at);
    if (!due.length) break;
    const t = due[0];
    now = t.at;
    timers.splice(timers.indexOf(t), 1);
    t.fn();
  }
  now = end;
}

function assert(cond, msg) { if (!cond) { console.error('FAIL:', msg); process.exit(1); } }

const script = fs.readFileSync(process.argv[2], 'utf8');
const transScript = script.replace("mode: 'both'", "mode: 'trans'");
const sourceScript = script.replace("mode: 'both'", "mode: 'source'");

// Scenario 1: hold — short final cannot overwrite within holdMs (trans mode primary = #trans)
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: 'AAAA' });
  assert(els.trans.textContent === 'AAAA', 'first final shown immediately');
  advance(500);
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: 'BBBB' });
  assert(els.trans.textContent === 'AAAA', 'second final held within holdMs');
  advance(1500);
  assert(els.trans.textContent === 'BBBB', 'held final swaps after holdMs');
  assert(els.subtitle.classList._hidden === false, 'subtitle visible after swap');
}

// Scenario 2: fade out after inactivity, reappears on new content
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: 'AAAA' });
  advance(4100);
  assert(els.subtitle.classList._hidden === true, 'subtitle fades out after fadeMs');
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: 'BBBB' });
  assert(els.subtitle.classList._hidden === false, 'subtitle reappears on new content');
}

// Scenario 3: mode both (default) — source on #main, translation on #trans, both visible
{
  const WS = setup(script);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: 'HELLO' });
  fire(WS, { type: 'translation', seq: 1, text: 'こんにちは' });
  assert(els.main.textContent === 'HELLO', 'both mode: main = source');
  assert(els.main.style.visibility === 'visible', 'both mode: main line visible');
  assert(els.trans.textContent === 'こんにちは', 'both mode: trans line = translation');
  assert(els.trans.style.visibility === 'visible', 'both mode: trans line visible');
}

// Scenario 4: partial-as-main shown immediately on primary line; refresh updates immediately
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'pre' });
  assert(els.trans.textContent === 'pre', 'first partial shown immediately (trans mode primary)');
  assert(els.main.style.visibility === 'hidden', 'trans mode: source line hidden');
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'pre view' });
  assert(els.trans.textContent === 'pre view', 'partial refresh updates immediately');
}

// Scenario 5: demo mode cycles sample lines without a socket
{
  setup(transScript.replace('demo: false', 'demo: true'));
  advance(3100);
  assert(els.trans.textContent !== '', 'demo shows sample line');
  assert(els.subtitle.classList._hidden === false, 'demo subtitle visible');
}

// Scenario 6: translation for a held (pending) final must not leak into display
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: 'AAAA' });
  advance(500);
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: 'BBBB' });
  fire(WS, { type: 'translation', seq: 2, text: 'BBBB翻訳' });
  assert(els.trans.textContent === 'AAAA', 'held line stays while pending final gets its translation');
  advance(1500);
  assert(els.trans.textContent === 'BBBB翻訳', 'pending final + translation swap in after hold');
}

// Scenario 7: partial -> final of same utterance swaps immediately (no hold)
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 9, utterance_id: 9, text: 'hee' });
  advance(130);
  assert(els.trans.textContent === 'hee', 'partial shown on primary line');
  fire(WS, { type: 'transcript', kind: 'final', seq: 9, utterance_id: 9, text: 'HELLO' });
  assert(els.trans.textContent === 'HELLO', 'final of same utterance replaces partial immediately');
}

// Scenario 8: rapid partial refresh updates immediately, no stale text
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'aaa' });
  assert(els.trans.textContent === 'aaa', 'first partial shown immediately');
  advance(100);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'aaa bbb' });
  assert(els.trans.textContent === 'aaa bbb', 'rapid refresh shows latest immediately');
  advance(100);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'aaa bbb ccc' });
  assert(els.trans.textContent === 'aaa bbb ccc', 'latest partial shown on each refresh');
}

// Scenario 9: partial line under a shown final updates immediately, translation untouched
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: 'AAA' });
  fire(WS, { type: 'translation', seq: 1, text: '中文翻譯' });
  advance(100);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 2, utterance_id: 2, text: 'bbb' });
  fire(WS, { type: 'transcript', kind: 'partial', seq: 2, utterance_id: 2, text: 'bbb ccc' });
  assert(els.trans.textContent === '中文翻譯', 'translation line stable during partial refresh');
  assert(els.partial.textContent === 'bbb ccc', 'partial line shows latest immediately');
  assert(els.partial.style.visibility === 'visible', 'partial slot visible');
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: 'bbb ccc' });
  assert(els.trans.textContent === '中文翻譯', 'held: translation stays during hold');
  assert(els.partial.style.visibility === 'visible', 'partial slot stays during hold');
  advance(2000);
  assert(els.trans.textContent === 'bbb ccc', 'final swaps in after hold');
  assert(els.partial.style.visibility === 'hidden', 'partial slot reserved but hidden when empty');
}

// Scenario 10: short final (interjection) merges into current sentence, does not replace it
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: '今天天氣真好', t1: 100.0 });
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: '嗯', t1: 100.4 });
  assert(els.trans.textContent === '今天天氣真好 嗯', 'interjection merged into current sentence');
  fire(WS, { type: 'transcript', kind: 'final', seq: 3, utterance_id: 3, text: '我想去公園', t1: 104.0 });
  assert(els.trans.textContent === '今天天氣真好 嗯', 'merged sentence held within holdMs');
  advance(2100);
  assert(els.trans.textContent === '我想去公園', 'next real final replaces merged sentence after hold');
}

// Scenario 11: interjection translation merged into #trans when it arrives
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: '今天天氣真好', t1: 100.0 });
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: '嗯', t1: 100.4 });
  fire(WS, { type: 'translation', seq: 1, text: '天氣真好啊' });
  assert(els.trans.textContent === '天氣真好啊', 'base translation shown before interj translation');
  fire(WS, { type: 'translation', seq: 2, text: '嗯嗯' });
  assert(els.trans.textContent === '天氣真好啊 嗯嗯', 'interjection translation merged in');
}

// Scenario 12: long gap after previous final -> not an interjection -> normal swap
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: '我想去公園', t1: 100.0 });
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: '好', t1: 103.0 });
  assert(els.trans.textContent === '我想去公園', 'held while within holdMs');
  advance(2100);
  assert(els.trans.textContent === '好', 'short final after long gap replaces (real utterance)');
}

// Scenario 13: consecutive interjections all merge into the base sentence
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: '今天天氣真好', t1: 100.0 });
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: '嗯', t1: 100.4 });
  fire(WS, { type: 'transcript', kind: 'final', seq: 3, utterance_id: 3, text: '哦', t1: 100.8 });
  assert(els.trans.textContent === '今天天氣真好 嗯 哦', 'all trailing interjections merged in order');
}

// Scenario 14: longer interjection beyond MAX_CHARS is a real sentence
{
  const WS = setup(transScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: '今天天氣真好', t1: 100.0 });
  fire(WS, { type: 'transcript', kind: 'final', seq: 2, utterance_id: 2, text: '嗯嗯嗯嗯', t1: 100.4 });
  assert(els.trans.textContent === '今天天氣真好', 'held while within holdMs');
  advance(2100);
  assert(els.trans.textContent === '嗯嗯嗯嗯', '4+ char final treated as real sentence');
}

// Scenario 15: partial-as-main (both mode, #main primary) refresh does NOT replay lineIn, restarts fade
{
  const WS = setup(script);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'pre' });
  assert(els.main.textContent === 'pre', 'both mode: partial-as-main on #main');
  assert(els.main.style.visibility === 'visible', 'both mode: main visible');
  const animSetsAfterFirst = els.main.style._sets;
  assert(animSetsAfterFirst >= 2, 'first partial-as-main runs lineIn (none + lineIn)');
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'pre view' });
  assert(els.main.textContent === 'pre view', 'partial-as-main refresh updates immediately');
  assert(els.main.style._sets === animSetsAfterFirst, 'partial-as-main refresh does not replay lineIn');
  advance(4100);
  assert(els.subtitle.classList._hidden === true, 'partial-as-main fades out after fadeMs');
  fire(WS, { type: 'transcript', kind: 'partial', seq: 5, text: 'pre view 2' });
  assert(els.subtitle.classList._hidden === false, 'partial-as-main refresh restarts fade');
}

// Scenario 16: bottom-slot partial under shown final uses partialIn and restarts fade after fade-out
{
  const WS = setup(script);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: 'HELLO' });
  fire(WS, { type: 'translation', seq: 1, text: 'こんにちは' });
  advance(100);
  fire(WS, { type: 'transcript', kind: 'partial', seq: 2, utterance_id: 2, text: 'bbb' });
  assert(els.partial.textContent === 'bbb', 'bottom-slot partial shown under final');
  assert(els.partial.style.animation.indexOf('partialIn') >= 0, 'bottom-slot partial uses partialIn');
  advance(4100);
  assert(els.subtitle.classList._hidden === true, 'bottom-slot partial fades out after fadeMs');
  fire(WS, { type: 'transcript', kind: 'partial', seq: 2, utterance_id: 2, text: 'bbb ccc' });
  assert(els.partial.textContent === 'bbb ccc', 'bottom-slot partial refresh updates immediately');
  assert(els.subtitle.classList._hidden === false, 'bottom-slot partial refresh restarts fade');
  assert(els.partial.style.visibility === 'visible', 'bottom-slot partial visible after refresh');
}

// Scenario 17: mode source — source on #main, translation never shown
{
  const WS = setup(sourceScript);
  WS.last.onopen();
  advance(700);
  fire(WS, { type: 'transcript', kind: 'final', seq: 1, utterance_id: 1, text: 'HELLO' });
  fire(WS, { type: 'translation', seq: 1, text: 'こんにちは' });
  assert(els.main.textContent === 'HELLO', 'source mode: main = source');
  assert(els.trans.style.visibility === 'hidden', 'source mode: trans line hidden');
}

console.log('overlay JS timing OK');
